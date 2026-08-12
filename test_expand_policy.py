# -*- coding: utf-8 -*-
"""core.expand_policy 的注入測試 + 等價/回歸(R4/R.6)。

X1/X2/X3/X4/X5 用注入驗證判準本身;X6/X7 用 `locate.EXPAND_TRUTH` 當清單來源
(不自己硬編一份),對算術家族斷言行為不變、對分類家族斷言確實停住。
C3 之前沒有 ingest,所以這裡對兩個家族都用**手寫 fixture**
(brief §R.6:玉山 202102 的兩列小計是規格給的範例),真實端到端驗證留到 C3。
"""
import buckets
import locate
from core import expand_policy as ep


class _Anchors:
    def __init__(self, mapping):
        self.anchors = mapping


def _signals(rec, anchors):
    """跑三道結構檢查(識別/錨/分桶),回傳失敗的檢查名稱集合。"""
    import transcribe
    failed = set()
    if transcribe.check_identity(rec):
        failed.add("check_identity")
    if transcribe.check_anchor(rec, anchors):
        failed.add("check_anchor")
    if transcribe.check_buckets(rec, buckets):
        failed.add("check_buckets")
    return failed


def _ok(cond, label, detail):
    mark = "✓" if cond else "✗"
    print(f"  {mark} {label} → {detail}")
    return cond


def _with_triggers(triggers, fn):
    """暫時替換 ep.TRIGGERS 執行 fn(),還原後回傳結果。模擬「注入」情境。"""
    orig = ep.TRIGGERS
    try:
        ep.TRIGGERS = triggers
        return fn()
    finally:
        ep.TRIGGERS = orig


def X1():
    """只有 ⑤ 失敗 → 不擴頁。"""
    failed = {"check_buckets"}
    got, reason = ep.may_expand(failed)
    return _ok(got is False, "X1", (got, reason))


def X1_inject():
    """注入:把 check_buckets 加進 TRIGGERS → 原本「不擴頁」的斷言必須變紅。"""
    got, reason = _with_triggers(ep.TRIGGERS | {"check_buckets"},
                                  lambda: ep.may_expand({"check_buckets"}))
    assertion_would_hold = (got is False)
    return _ok(assertion_would_hold is False, "X1-注入(必須紅)", (got, reason))


def X2():
    """只有 ③ 失敗 → 不擴頁。"""
    got, reason = ep.may_expand({"check_cross"})
    return _ok(got is False, "X2", (got, reason))


def X2_inject():
    """注入:把 check_cross 加進 TRIGGERS → 必須紅。"""
    got, reason = _with_triggers(ep.TRIGGERS | {"check_cross"},
                                  lambda: ep.may_expand({"check_cross"}))
    assertion_would_hold = (got is False)
    return _ok(assertion_would_hold is False, "X2-注入(必須紅)", (got, reason))


def X3():
    """① 失敗 → 擴頁。"""
    got, reason = ep.may_expand({"check_identity"})
    return _ok(got is True, "X3", (got, reason))


def X3_inject():
    """注入:把它從 TRIGGERS 拿掉 → 必須紅。"""
    got, reason = _with_triggers(ep.TRIGGERS - {"check_identity"},
                                  lambda: ep.may_expand({"check_identity"}))
    assertion_would_hold = (got is True)
    return _ok(assertion_would_hold is False, "X3-注入(必須紅)", (got, reason))


def X4():
    """⑤ 失敗時 consumes_budget() 為 False。"""
    got = ep.consumes_budget({"check_buckets"})
    return _ok(got is False, "X4", got)


def X4_inject():
    """注入:把 check_buckets 加進 TRIGGERS(讓 consumes_budget 變 True)→ 必須紅。"""
    got = _with_triggers(ep.TRIGGERS | {"check_buckets"},
                          lambda: ep.consumes_budget({"check_buckets"}))
    assertion_would_hold = (got is False)
    return _ok(assertion_would_hold is False, "X4-注入(必須紅)", got)


def X5():
    """① + ⑤ 同時失敗 → 擴頁(理由要指名是 ①,不是 ⑤)。"""
    got, reason = ep.may_expand({"check_identity", "check_buckets"})
    return _ok(got is True and "check_buckets" not in reason and "check_identity" in reason,
                "X5", (got, reason))


# ── X6:算術家族行為不變 ─────────────────────────────────────────────────
ARITH_DOCS = {"202102_國泰_個體", "202401_中信_合併", "202501_中信_合併",
              "202502_中信_合併", "202502_中信_個體"}
#: 分類家族。原本有 5 格,其中 `202102_5847_AI2` 與 `202102_玉山_個體` 是
#: **同一份 PDF 被重複抓兩次**(sha256 逐字相同),2026-08-12 doc id 改名時
#: 併回同一個名字,所以剩 4 格 —— 少的那格不是掉了案例,是本來就重複。
CLASS_DOCS = {"202102_玉山_個體", "202302_玉山_個體",
              "202402_玉山_個體", "202502_玉山_個體"}


def _arith_fixture(doc, cls):
    """第一層只看到局部頁(跨頁/前一頁小計未含),sum(rows) != printed_total,
    但 printed_total 這裡填成「錨」——精準重現 M4 的算術失敗形狀:①②失敗、④綠。"""
    anchor = 100_000_000
    rec = {"doc": doc, "class": cls, "source_page": 1, "source_kind": "附註",
           "total_col": "113年12月31日", "printed_total": anchor,
           "rows": [{"name": "只抄到局部的一列", "cols": {"113年12月31日": 40_000_000}}]}
    return rec, _Anchors({cls: anchor})


def X6():
    truth = [t for t in locate.EXPAND_TRUTH if t[0] in ARITH_DOCS]
    assert len(truth) == 5, f"算術家族應有 5 格,取得 {len(truth)}"
    allok = True
    for doc, cls, _need in truth:
        rec, anchors = _arith_fixture(doc, cls)
        failed = _signals(rec, anchors)
        got, reason = ep.may_expand(failed)
        allok &= _ok(got is True, f"X6 {doc} {cls}", (sorted(failed), reason))
    return allok


# ── X7:分類家族確實停住 ─────────────────────────────────────────────────
def _class_fixture(doc, cls):
    """規格範例(brief §R.6):玉山 202102 主附註兩列小計,精準等於錨,
    兩列 bucket() 皆 None(M3:提不出候選的名字裡,這兩個是小計)。"""
    anchor = 287_711_177
    rec = {"doc": doc, "class": cls, "source_page": 23, "source_kind": "附註",
           "total_col": "110年6月30日", "printed_total": anchor,
           "rows": [
               {"name": "透過其他綜合損益按公允價值衡量之權益工具投資",
                "cols": {"110年6月30日": 16_018_428}},
               {"name": "透過其他綜合損益按公允價值衡量之債務工具投資",
                "cols": {"110年6月30日": 271_692_749}},
           ]}
    return rec, _Anchors({cls: anchor})


def X7():
    truth = [t for t in locate.EXPAND_TRUTH if t[0] in CLASS_DOCS]
    assert len(truth) == 4, f"分類家族應有 4 格,取得 {len(truth)}"
    allok = True
    for doc, cls, _need in truth:
        rec, anchors = _class_fixture(doc, cls)
        failed = _signals(rec, anchors)
        # Gate 1(存檔):①②④ 全綠;Gate 2(發布):⑤ 擋住
        gate1 = "check_identity" not in failed and "check_anchor" not in failed
        got, reason = ep.may_expand(failed)
        allok &= _ok(failed == {"check_buckets"}, f"X7 {doc} {cls} 失敗訊號",
                     sorted(failed))
        allok &= _ok(gate1 is True, f"X7 {doc} {cls} Gate1(可歸檔)", gate1)
        allok &= _ok(got is False, f"X7 {doc} {cls} may_expand==False", (got, reason))
    return allok


def main():
    print("X1 只有 ⑤ 失敗 → 不擴頁")
    ok = X1()
    ok &= X1_inject()
    print("X2 只有 ③ 失敗 → 不擴頁")
    ok &= X2()
    ok &= X2_inject()
    print("X3 ① 失敗 → 擴頁")
    ok &= X3()
    ok &= X3_inject()
    print("X4 ⑤ 失敗時 consumes_budget() 為 False")
    ok &= X4()
    ok &= X4_inject()
    print("X5 ①+⑤ 同時失敗 → 擴頁,理由指名 ①")
    ok &= X5()
    print("X6 算術家族(M4 五格)行為不變")
    ok &= X6()
    print("X7 分類家族(玉山五格)確實停住")
    ok &= X7()
    print(f"\n{'全部通過' if ok else '有失敗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
