# -*- coding: utf-8 -*-
"""Gemini API 的唯一出口 —— 多把 key 輪替 + 節流 + 429 重試。

抽自 `extract_v2.py`(`docs/plan_schema_derive.md` D3)。根因:`fill_auto.py`
只用得到 `extract_v2._gen()` 這一個函式,卻要 import 整支 786 行的舊視覺管線
(`memory/feedback-no-old-pipeline` 已裁示不准用)。混淆的地方在於它自己也定義
了一套 `printed_total` 語意,容易讓人以為抄列管線跟它有關係 —— 其實只借了
這一個 API 包裝函式。

`extract_v2.py` 自己也還在用這個包裝(它有獨立的呼叫點),所以搬家後
`extract_v2.py` 改成從這裡 import,不重複定義。
"""
import os
import time

from config import MIN_GAP

# 多把 key 輪替:免費層是【每把 key】各自 500/天(RPD)+ 少量 RPM。
# 舊寫法只挑一把 key 並快取,跑到一半那把爆日配額(RESOURCE_EXHAUSTED)就整批卡死。
# 改:蒐集所有非空 key(_3→_2→_1→base 順序),爆配額時自動換下一把,換完才真的失敗。
_KEYS = None
_KI = [0]          # 目前用第幾把 key
_CLIENT = None
_DEAD = set()      # 本次執行已爆配額的 key index(不再回頭用)


def _load_env(path=".env"):
    """把 .env 的 KEY=VALUE 塞進環境變數(不覆蓋既有)。"""
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _keys():
    _load_env()
    seen, out = set(), []
    for name in ("GEMINI_API_KEY_3", "GEMINI_API_KEY_2", "GEMINI_API_KEY_1",
                 "GEMINI_API_KEY", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"):
        v = os.environ.get(name, "").strip()
        if v and v not in seen:
            seen.add(v); out.append(v)
    return out


def _build_client(key):
    from google import genai
    from google.genai import types as _gt
    # HTTP 超時 90 秒:呼叫卡住會自動斷線重試,不會像先前無 timeout 一樣 hang 死。
    return genai.Client(api_key=key, http_options=_gt.HttpOptions(timeout=90_000))


def _client():
    global _CLIENT, _KEYS
    if _KEYS is None:
        _KEYS = _keys()
        if not _KEYS:
            raise RuntimeError("找不到任何 GEMINI_API_KEY(檢查 .env / 環境變數)")
    if _CLIENT is None:
        _CLIENT = _build_client(_KEYS[_KI[0]])
    return _CLIENT


def _rotate_key():
    """把目前 key 標記為爆配額,換到下一把還沒爆的 key。全部爆掉 → 回 False(交給上層 sleep/放棄)。"""
    global _CLIENT
    _DEAD.add(_KI[0])
    for j in range(len(_KEYS or [])):
        if j not in _DEAD:
            _KI[0] = j
            _CLIENT = _build_client(_KEYS[j])
            return True
    return False


def _is_quota(e):
    """RESOURCE_EXHAUSTED / 429 / quota:配額類錯誤(可能是每分鐘 RPM 或每日 RPD)。"""
    m = str(e).lower()
    return ("resource_exhausted" in m or "429" in m or "quota" in m or "exhausted" in m)


# 全域節流:免費 Flash RPM 有限,強制每次 API 呼叫間隔 ≥ MIN_GAP 秒。
_last_call = [0.0]


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < MIN_GAP:
        time.sleep(MIN_GAP - dt)
    _last_call[0] = time.time()


def generate(**kw):
    """唯一的 generate_content 出口:節流 → 呼叫 →(遇配額)換 key 重試。
       配額錯誤先換下一把 key 立即重試(對 RPD/RPM 都有效:換 key 換到另一個配額桶);
       所有 key 都爆 → 拋出,交給呼叫端的重試邏輯睡一分鐘等 RPM 回補(RPD 就等隔天)。
    """
    while True:
        _throttle()
        try:
            return _client().models.generate_content(**kw)
        except Exception as e:
            if _is_quota(e) and _rotate_key():
                continue          # 換到新 key,重試同一個呼叫
            raise
