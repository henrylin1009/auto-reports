#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ingest_policy.py — C3-a A2 的白名單注入測試(T1-T6)

    T1  只有 check_buckets 失敗 → FILED(歸檔且進人審佇列)、不擴頁(注入 → 必須紅)
    T2  只有 check_cross 失敗   → FILED(同上)(注入 → 必須紅)

⚠️ 2026-07-31 改版:歸檔閘砍成兩道(①② 與 ④)之後,⑤/③ 不再讓
   `transcribe.verify()` 回 False,所以「注入 TRIGGERS 讓它去擴頁」這個舊注入
   **打不到判斷點了**(`classify_outcome` 在 `if ok:` 就分流完)。注入改打
   `expand_policy.NEVER`:把 check_buckets/check_cross 從 NEVER 拿掉 →
   Gate 2 訊號變空 → outcome 從 FILED 變成 PASS → 主張必須變紅。
   **這才是今天真正的判斷點** —— 注入要打在會出錯的地方,不是打在歷史上的地方。
    T3  check_identity 失敗    → 擴頁、retries +1(注入 → 必須紅)
    T4  check_identity + check_buckets 同時失敗 → 擴頁,理由只提 ①,不提 ⑤(注入 → 必須紅)
    T5  ingest 不准自己重寫一份觸發判斷 —— 唯一來源是 core.expand_policy
    T6  結構化檢查結果與 transcribe.verify() 的結論同進同出(注入 → 必須紅)

執行方式: python3 test_ingest_policy.py
exit 0 = 全綠
"""
import inspect
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline
import transcribe
from core import expand_policy as ep
from core import ingest

PASS = 0
FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  {detail}" if detail else ""))


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


class _FakeLoc:
    def __init__(self, anchors, expand_pages=None):
        self.anchors = anchors
        self._expand_pages = expand_pages or {}

    def expand(self, cls, level):
        return self._expand_pages.get(level, [])


def _with_triggers(triggers, fn):
    orig = ep.TRIGGERS
    try:
        ep.TRIGGERS = triggers
        return fn()
    finally:
        ep.TRIGGERS = orig


def _with_never(never, fn):
    """暫時換掉 `expand_policy.NEVER` —— 今天決定 PASS/FILED 的就是它。"""
    orig = ep.NEVER
    try:
        ep.NEVER = never
        return fn()
    finally:
        ep.NEVER = orig


# ── T1:只有 check_buckets 失敗 ──────────────────────────────────────────
def _t1_case():
    """單列,名字兩邊都推不出桶(buckets.SYN 認不得,rules.propose 也提不出)—
    避免被 `_taxonomy_gap` 先攔成 BLOCKED。金額/錨都對得上,只有分桶失敗。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "113年12月31日", "printed_total": 500,
           "rows": [{"name": "測試專用不存在的分類名稱ZZZ",
                     "cols": {"113年12月31日": 500}}]}
    # expand_pages 一定要給得出新頁 —— 否則「白名單允許擴頁」與「擴不出新頁」
    # 兩條路都會落到同一個 REJECT,注入測試會分不出是白名單擋下來的還是純粹沒新頁。
    loc = _FakeLoc({"Trading": 500}, expand_pages={1: [99]})
    return rec, loc


def T1():
    rec, loc = _t1_case()
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 3,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = r["outcome"] == "FILED" and r["retries"] == 3
    return _ok(cond, "T1 只有⑤失敗→FILED(歸檔+進佇列)、不擴頁", r)


def T1_inject():
    """注入:把 check_buckets 從 NEVER 拿掉 → Gate 2 訊號變空 → 這一格會變成
    乾淨 PASS(不進人審佇列),「T1 的斷言(FILED)」必須變紅。"""
    rec, loc = _t1_case()
    r = _with_never(ep.NEVER - {"check_buckets"},
                    lambda: ingest.classify_outcome(
                        "X", "Trading", [rec], loc, 0, [1], 3,
                        pipeline.MAX_LEVEL, use_policy=True))
    would_hold = r["outcome"] == "FILED" and r["retries"] == 3
    return _ok(would_hold is False, "T1-注入(必須紅)", r)


# ── T2:只有 check_cross 失敗 ────────────────────────────────────────────
def _t2_case():
    """兩份 record,同金額但兩邊掛的桶不同 → check_cross 產生「金額對不上,
    兩邊的桶不同」的硬失敗;check_identity/check_anchor/check_buckets 均通過。"""
    rec1 = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
            "total_col": "c", "printed_total": 100,
            "rows": [{"name": "公司債", "cols": {"c": 100}}]}
    rec2 = {"doc": "X", "class": "Trading", "source_page": 2, "source_kind": "明細表",
            "total_col": "c", "printed_total": 100,
            "rows": [{"name": "金融債", "cols": {"c": 100}}]}
    loc = _FakeLoc({"Trading": 100}, expand_pages={1: [99]})
    return rec1, rec2, loc


def T2():
    rec1, rec2, loc = _t2_case()
    r = ingest.classify_outcome("X", "Trading", [rec1, rec2], loc, 0, [1, 2], 5,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = r["outcome"] == "FILED" and r["retries"] == 5
    return _ok(cond, "T2 只有③失敗→FILED(歸檔+進佇列)、不擴頁", r)


def T2_inject():
    """注入同 T1:把 check_cross 從 NEVER 拿掉 → 變成乾淨 PASS,主張必須變紅。"""
    rec1, rec2, loc = _t2_case()
    r = _with_never(ep.NEVER - {"check_cross"},
                    lambda: ingest.classify_outcome(
                        "X", "Trading", [rec1, rec2], loc, 0, [1, 2], 5,
                        pipeline.MAX_LEVEL, use_policy=True))
    would_hold = r["outcome"] == "FILED" and r["retries"] == 5
    return _ok(would_hold is False, "T2-注入(必須紅)", r)


# ── T3:check_identity 失敗 → 擴頁、retries+1 ────────────────────────────
def _t3_case():
    """單列,名字認得(不觸發 gap),但列相加 != printed_total → ①失敗。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "c", "printed_total": 999,
           "rows": [{"name": "公司債", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 999}, expand_pages={1: [99]})
    return rec, loc


def T3():
    """⚠️ **2026-08-12 改寫。** 這一格現在**在推導層就被攔下**,不再走到
    `expand_policy`。

    原因:`core.derive.derive_record()` 會**重新推導** `printed_total`
    (挑出「列和 == 推導目標」的那一欄),所以「列相加 ≠ printed_total」的
    record 根本過不了推導層 —— 換句話說 **① `check_identity` 在推導層
    之後是打不到的**。人工路徑(`fill._attempt`)本來就是這個行為,實測
    同一筆資料回同一句 `0 個欄命中`。

    這支測試以前會過,**正是因為自動路徑 `classify_outcome` 漏跑了推導層**
    (v7 R2-3 用第一銀行實跑才抓到,見 `core.derive.prepare()` 的說明)——
    它測的其實是那個 bug 本身。修好之後斷言改成「推導層攔下、仍然擴頁重試」。
    """
    rec, loc = _t3_case()
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = (r["outcome"] == "RETRY" and r["retries"] == 1
            and "個欄命中" in (r.get("reason") or ""))
    return _ok(cond, "T3 ①在推導層被攔下→擴頁、retries+1", r)


def T3_inject():
    """注入:**讓 `derive.prepare` 變成直通**(模擬修好之前那個漏跑推導層的
    bug)→ 這一格會改由 `transcribe.verify` 的 ① 判失敗,理由不再是
    「0 個欄命中」,T3 的斷言必須變紅。

    這個注入點就是真實出過的那個 bug,所以它同時是回歸鎖。"""
    rec, loc = _t3_case()
    real = ingest.derive.prepare
    try:
        ingest.derive.prepare = lambda recs, loc, cls, log=None: (recs, None)
        r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                     pipeline.MAX_LEVEL, use_policy=True)
    finally:
        ingest.derive.prepare = real
    would_hold = (r["outcome"] == "RETRY" and r["retries"] == 1
                  and "個欄命中" in (r.get("reason") or ""))
    return _ok(would_hold is False, "T3-注入(必須紅)", r)


def T3b_model_output_shape():
    """**回歸鎖:模型照 prompt 輸出 `record_total` 時,自動路徑必須收得下。**

    `fill.py` 的 prompt 教模型每份 record 填 `record_total`,而
    `facts.validate()` 要的是 `total_col`/`printed_total` —— 中間那一步翻譯
    是推導層做的。自動路徑漏跑推導層時,**每一格新資料都必然
    「缺必要欄位 ['total_col','printed_total']」**,這正是 v7 R2-3
    第一銀行三格全 REJECT 的根因(reader 其實抄對了)。
    """
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "record_total": 500, "rows": [{"name": "公司債", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 500})
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = r["outcome"] in ("PASS", "FILED")
    return _ok(cond, "T3b 模型輸出的 record_total 會被推導成 total_col/printed_total",
               (r["outcome"], r.get("reason") or r.get("message")))


def T3b_inject():
    """注入:推導層直通 → `record_total` 沒被翻譯 → 必須因缺必要欄位失敗。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "record_total": 500, "rows": [{"name": "公司債", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 500})
    real = ingest.derive.prepare
    try:
        ingest.derive.prepare = lambda recs, loc, cls, log=None: (recs, None)
        r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                     pipeline.MAX_LEVEL, use_policy=True)
    finally:
        ingest.derive.prepare = real
    would_hold = r["outcome"] in ("PASS", "FILED")
    return _ok(would_hold is False, "T3b-注入(必須紅)",
               (r["outcome"], r.get("reason")))


# ── T4:①+⑤ 同時失敗 → 擴頁,理由只提 ① ──────────────────────────────────
def _t4_case():
    """單列,名字兩邊都推不出桶(⑤失敗)且列相加也不等於印出合計(①失敗)。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "c", "printed_total": 999,
           "rows": [{"name": "測試專用不存在的分類名稱ZZZ", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 999}, expand_pages={1: [99]})
    return rec, loc


def T4():
    """⚠️ **2026-08-12 改寫,理由同 T3。** ①+⑤ 同時失敗時,**①(算術)
    在推導層就被攔下**,根本走不到「⑤ 要不要一起算進擴頁理由」那一步。

    要守的不變量沒有變、只是搬家了:**算術失敗優先於分類失敗**,不會因為
    同一格也有分類問題就改判成 FILED 歸檔。這裡就斷言這件事:
    outcome 是 RETRY(擴頁重抄),不是 FILED(歸檔+進佇列)。
    """
    rec, loc = _t4_case()
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = (r["outcome"] == "RETRY" and "個欄命中" in (r.get("reason") or ""))
    return _ok(cond, "T4 ①+⑤同時失敗→算術優先,擴頁重抄(不是 FILED 歸檔)",
               (r["outcome"], r.get("reason")))


def T4_inject():
    """注入:推導層直通 → ① 不再被攔,這一格會落到 Gate2-only 的判斷、
    被當成「只有分類沒過」而 **FILED 歸檔**(算術錯的資料進了事實庫)。
    T4 的斷言必須變紅 —— 這正是這道閘門要擋的後果。"""
    rec, loc = _t4_case()
    real = ingest.derive.prepare
    try:
        ingest.derive.prepare = lambda recs, loc, cls, log=None: (recs, None)
        r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                     pipeline.MAX_LEVEL, use_policy=True)
    finally:
        ingest.derive.prepare = real
    would_hold = (r["outcome"] == "RETRY" and "個欄命中" in (r.get("reason") or ""))
    return _ok(would_hold is False, "T4-注入(必須紅)",
               (r["outcome"], r.get("reason")))


# ── T5:唯一觸發來源是 core.expand_policy ────────────────────────────────
def T5():
    src = inspect.getsource(ingest)
    uses_policy = ("expand_policy.may_expand(" in src
                   and "expand_policy.consumes_budget(" in src)
    # ingest.py 不准另外複製一份與 TRIGGERS/NEVER 完全相同的集合字面值 ——
    # 那就是「另寫一份觸發判斷」。_CHECK_NAMES 只是「有哪些 check_* 函式可呼叫」
    # 的清單(給 _structured_checks 組結構化結果用),本身**不是**任何 may_expand
    # 的判準來源 —— 判準一律外送給 expand_policy.may_expand()。
    no_duplicate_triggers = (repr(sorted(ep.TRIGGERS)) not in src.replace(" ", "")
                              and repr(sorted(ep.NEVER)) not in src.replace(" ", ""))
    cond = uses_policy and no_duplicate_triggers
    return _ok(cond, "T5 唯一來源是 expand_policy(無重複 TRIGGERS/NEVER 字面值)",
               {"uses_policy": uses_policy, "no_duplicate_triggers": no_duplicate_triggers})


# ── T6:結構化檢查結果與 verify() 同進同出 ───────────────────────────────
def T6():
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "c", "printed_total": 999,
           "rows": [{"name": "公司債", "cols": {"c": 500}}]}   # ①失敗
    loc = _FakeLoc({"Trading": 999})
    structured_ok, verify_ok = ingest.consistent_with_verify([rec], loc, [1])
    cond = (structured_ok == verify_ok) and (verify_ok is False)
    return _ok(cond, "T6 結構化結論與 verify() 一致(都判失敗)",
               (structured_ok, verify_ok))


def T6_inject():
    """注入:讓 ingest._is_hard 永遠回 False(假裝沒有任何硬失敗)→
    structured_ok 會被硬拗成 True,而 verify() 仍然正確判失敗 → 兩者矛盾,
    T6 的一致性斷言必須變紅。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "c", "printed_total": 999,
           "rows": [{"name": "公司債", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 999})
    orig = ingest._is_hard
    try:
        ingest._is_hard = lambda v: False
        structured_ok, verify_ok = ingest.consistent_with_verify([rec], loc, [1])
    finally:
        ingest._is_hard = orig
    would_hold = (structured_ok == verify_ok)
    return _ok(would_hold is False, "T6-注入(必須紅)", (structured_ok, verify_ok))


def _ok(cond, label, detail):
    mark = "✓" if cond else "✗"
    print(f"  {mark} {label} → {detail}")
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    return cond


def main():
    print("=" * 60)
    print("test_ingest_policy.py — C3-a A2 白名單注入測試 (T1-T6)")
    print("=" * 60)
    allok = True
    print("T1 只有 ⑤ 失敗 → 不擴頁、retries 不增加")
    allok &= T1(); allok &= T1_inject()
    print("T2 只有 ③ 失敗 → 不擴頁、retries 不增加")
    allok &= T2(); allok &= T2_inject()
    print("T3 ① 失敗 → 在推導層被攔下、擴頁、retries+1")
    allok &= T3(); allok &= T3_inject()
    print("T3b 模型輸出的 record_total 必須被推導層翻譯(v7 R2-3 回歸鎖)")
    allok &= T3b_model_output_shape(); allok &= T3b_inject()
    print("T4 ①+⑤ 同時失敗 → 算術優先,擴頁重抄")
    allok &= T4(); allok &= T4_inject()
    print("T5 ingest 不准自己重寫觸發判斷")
    allok &= T5()
    print("T6 結構化結果與 verify() 同進同出")
    allok &= T6(); allok &= T6_inject()

    print("=" * 60)
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    print("RESULT:", "OK" if allok else "FAIL")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
