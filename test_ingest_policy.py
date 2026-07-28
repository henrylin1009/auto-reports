#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ingest_policy.py — C3-a A2 的白名單注入測試(T1-T6)

    T1  只有 check_buckets 失敗 → 不擴頁、retries 不增加(注入 → 必須紅)
    T2  只有 check_cross 失敗   → 不擴頁、retries 不增加(注入 → 必須紅)
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
    cond = (r["outcome"] != "RETRY") and (r["retries"] == 3)
    return _ok(cond, "T1 只有⑤失敗→不擴頁、retries不變", r)


def T1_inject():
    """注入:把 check_buckets 塞進 TRIGGERS → 這一格應該會被擴頁,
    「T1 的斷言(不擴頁)」必須變紅。"""
    rec, loc = _t1_case()
    r = _with_triggers(ep.TRIGGERS | {"check_buckets"},
                        lambda: ingest.classify_outcome(
                            "X", "Trading", [rec], loc, 0, [1], 3,
                            pipeline.MAX_LEVEL, use_policy=True))
    would_hold = (r["outcome"] != "RETRY") and (r["retries"] == 3)
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
    cond = (r["outcome"] != "RETRY") and (r["retries"] == 5)
    return _ok(cond, "T2 只有③失敗→不擴頁、retries不變", r)


def T2_inject():
    rec1, rec2, loc = _t2_case()
    r = _with_triggers(ep.TRIGGERS | {"check_cross"},
                        lambda: ingest.classify_outcome(
                            "X", "Trading", [rec1, rec2], loc, 0, [1, 2], 5,
                            pipeline.MAX_LEVEL, use_policy=True))
    would_hold = (r["outcome"] != "RETRY") and (r["retries"] == 5)
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
    rec, loc = _t3_case()
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                 pipeline.MAX_LEVEL, use_policy=True)
    cond = (r["outcome"] == "RETRY") and (r["retries"] == 1)
    return _ok(cond, "T3 ①失敗→擴頁、retries+1", r)


def T3_inject():
    """注入:把 check_identity 從 TRIGGERS 拿掉 → 這一格不該再擴頁,
    T3 的斷言(擴頁)必須變紅。"""
    rec, loc = _t3_case()
    r = _with_triggers(ep.TRIGGERS - {"check_identity"},
                        lambda: ingest.classify_outcome(
                            "X", "Trading", [rec], loc, 0, [1], 0,
                            pipeline.MAX_LEVEL, use_policy=True))
    would_hold = (r["outcome"] == "RETRY") and (r["retries"] == 1)
    return _ok(would_hold is False, "T3-注入(必須紅)", r)


# ── T4:①+⑤ 同時失敗 → 擴頁,理由只提 ① ──────────────────────────────────
def _t4_case():
    """單列,名字兩邊都推不出桶(⑤失敗)且列相加也不等於印出合計(①失敗)。"""
    rec = {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
           "total_col": "c", "printed_total": 999,
           "rows": [{"name": "測試專用不存在的分類名稱ZZZ", "cols": {"c": 500}}]}
    loc = _FakeLoc({"Trading": 999}, expand_pages={1: [99]})
    return rec, loc


def T4():
    rec, loc = _t4_case()
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 0,
                                 pipeline.MAX_LEVEL, use_policy=True)
    why = r.get("why") or ""
    cond = (r["outcome"] == "RETRY" and "check_identity" in why
            and "check_buckets" not in why)
    return _ok(cond, "T4 ①+⑤同時失敗→擴頁,理由只提①", (r["outcome"], why))


def T4_inject():
    """注入:把 check_buckets 也塞進 TRIGGERS → 理由會提到 ⑤,
    T4 的斷言(理由不提⑤)必須變紅。"""
    rec, loc = _t4_case()
    r = _with_triggers(ep.TRIGGERS | {"check_buckets"},
                        lambda: ingest.classify_outcome(
                            "X", "Trading", [rec], loc, 0, [1], 0,
                            pipeline.MAX_LEVEL, use_policy=True))
    why = r.get("why") or ""
    would_hold = (r["outcome"] == "RETRY" and "check_identity" in why
                  and "check_buckets" not in why)
    return _ok(would_hold is False, "T4-注入(必須紅)", (r["outcome"], why))


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
    print("T3 ① 失敗 → 擴頁、retries+1")
    allok &= T3(); allok &= T3_inject()
    print("T4 ①+⑤ 同時失敗 → 擴頁,理由只提 ①")
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
