#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-1 驗收:`v4/reader` 的產出 → `facts/` records,不得扭曲資料。

**這支存在的理由**(docs/plan_工具化.md 缺 1):在 `to_facts_records()` 之前,
v4 的產出停在 `v4/raw/` 進不了 `facts/` —— 於是同一件事有兩個事實庫、
兩個 ratify、兩套人審介面,每條規則都要做兩次。

核心命題:**同一份 v4 產出,走 facts 路徑與走 v4 自己的 `aggregate()`,
七個桶必須逐格相同。** 只驗總額會漏掉分桶錯位(見 memory/wide-cost-bucket-alignment)。

⚠️ **跑遍 `v4/raw/` 全部,不是挑一份。** 初版只用 `202502_5836`(半年報),
三個類別的 `cost` 全是空的,於是「成本 record 必須帶取得成本鉤子」那條斷言
在空集合上恆為真 —— 注入錯誤測不出來,是個恆真閘門(memory/checks-must-fail)。
現在用 `COST_SEEN_MIN` 守住:沒真的驗到成本 record 就算失敗。

執行: python3 test_v4_to_facts.py     exit 0 = 全綠
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import facts as facts_mod
import wide
from v4 import adapter

PASS = FAIL = 0
_BAS = {"公允": "帳面", "成本": "成本"}
#: 至少要驗到這麼多份成本 record,否則成本那幾條斷言等於沒跑。
#: 現況 `v4/raw` 有 14 份年報帶成本明細表,取一個遠低於它但大於 0 的下限。
COST_SEEN_MIN = 10


def eq(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


def _agg_view(blk):
    """期望值:走 v4 自己那條路徑該得到什麼。

    ⚠️ **不可以用 `aggregate()` 自報的 basis 當 key。** 年報的 book(帳面)與
    cost(取得成本)**兩邊都沒有評價調整列**,`aggregate()` 因此兩邊都回報
    「公允」,後者會把前者蓋掉 —— 初版就是這樣寫的,結果 6 份年報的期望值
    整個錯位。`aggregate()` 天生分不出 book/cost,那正是 `to_facts_records()`
    改用欄名當鉤子要解決的事。

    也**不重新實作一次 `wide.pick()`** —— 那樣測試就變成套套邏輯。這裡用的是
    v4 raw 自己的 side 語意(book 是帳面、cost 是取得成本),它是獨立於
    `wide.py` 的真值來源:
        帳面 = book,除非 book 自己算出是成本(有評價調整列,如 AC 的備抵損失)
        成本 = 那個成本的 book,否則 cost

    ⚠️ **回傳 `Aggregated` 本身,不是被閘門過濾後的 book。** `wide.view()`
    **永遠**回傳 book,閘門是靠 `View.ok`/`View.unknown` 表達的;
    `aggregate()` 則是不合格就 `ok=False`。拿 `view.book` 去比「被閘門擋掉後
    的 None」是在比蘋果和橘子 —— 初版就是這樣寫的,32 條假失敗全出於此。
    數字和閘門要**分開比**,兩者都必須一致。
    """
    def agg(side):
        sub = (blk or {}).get(side) or {}
        if not sub.get("rows"):
            return None
        printed = sub.get("printed_subtotal") or sub.get("total")
        return _relax(adapter.aggregate(sub["rows"], printed), printed)

    b, c = agg("book"), agg("cost")
    book_is_cost = b is not None and b.basis == "成本"
    return {"帳面": None if book_is_cost else b,
            "成本": b if book_is_cost else c}


class _Ok:
    """把一個「只因 null 金額而不合格」的 Aggregated 視為合格。"""

    def __init__(self, a):
        self.book, self.side, self.basis, self.ok = a.book, a.side, a.basis, True


def _relax(a, printed):
    """`aggregate()` 把「金額是 null」的列一律判不合格(錢不准悄悄消失);
    `wide.view()` 的規則是「缺欄 = 未揭露,不是 0」,跳過那幾列。

    **當 unknown 全是 null 金額、而且印出的合計恆等式仍然成立時,後者才是對的。**
    印出的合計就是見證人:那幾列若真的該有數字,等式不會剛好對上。
    實測 `202004_5847_AI3|Trading` 成本 —— 明細表 6 列沒揭露取得成本,
    其餘 686,786,752 + 衍生 481,932 = 687,268,684 = 文件印的成本合計。

    這不是放寬閘門,是**認出 v4 那側在這個情況下過度保守**;兩條管線合併時
    必須挑一個,挑的是有見證人的那個。恆等式**在這裡自己驗**,不是把判斷推給
    `wide.view()` —— 推過去測試就變成套套邏輯。
    """
    if a is None or a.ok or not a.unknown:
        return a
    if not all(u[1] is None for u in a.unknown):
        return a                                  # 有真的分不到桶的列,不放行
    if printed is None or sum(a.book.values()) + sum(a.side.values()) != printed:
        return a                                  # 恆等式不成立,不放行
    return _Ok(a)


def main():
    docs = cost_seen = 0
    for path in sorted(glob.glob("v4/raw/*.json")):
        raw = json.load(open(path, encoding="utf-8"))
        parsed = raw.get("parsed")
        if not isinstance(parsed, dict):
            continue                  # parse_ok=False 的舊檔,不是本單的事
        doc = raw["doc"]
        docs += 1
        cells = {}
        for cls in ("Trading", "OCI", "AC"):
            blk = parsed.get(cls)
            if not isinstance(blk, dict):
                continue
            recs = adapter.to_facts_records(doc, cls, blk, parsed.get("bs_date"))
            if not recs:
                continue
            cells[f"{doc}|{cls}"] = recs

            agg = _agg_view(blk)
            for basis in ("帳面", "成本"):
                # **比「最後會發布什麼」,不是分開比 book 和 ok。**
                # `build.py` 是 `book = v[basis] if ok else None` —— 不合格就寫
                # null。兩條路徑對「不合格」的表達方式不同(facts 這側可能整份
                # record 就不成立而回 None,aggregate 那側是 book 照給、ok=False),
                # 分開比會生出一堆「兩邊都不發布卻算不一致」的假失敗。
                v, a = wide.view(recs, basis), agg[basis]
                eq(f"{doc}|{cls}|{basis} 發布結果相同",
                   v.book if v.ok else None,
                   None if a is None else (a.book if a.ok else None))

            for r in recs:
                if r["source_kind"] != "明細表":
                    continue
                cost_seen += 1
                eq(f"{doc}|{cls} 成本 total_col 是「取得成本」",
                   r["total_col"], "取得成本")
                # 文件有印合計才給鉤子。沒印就不給 —— `wide.pick()` 因此認不到
                # 成本口徑,理由字串「明細表也沒抄下取得成本欄的合計(驗不到)」
                # 講的就是這件事。自己加總一個數字塞進去等於偽造文件沒有的東西。
                printed = ((blk.get("cost") or {}).get("total"))
                eq(f"{doc}|{cls} 有印合計才有「取得成本」鉤子",
                   "取得成本" in (r.get("printed_totals") or {}),
                   isinstance(printed, int) and not isinstance(printed, bool))

            # 欄名是 `wide.pick()` 的鉤子:用 BOOK_COLS 當欄名會繞過 basis_of,
            # AC 那種「逐項毛額 + 一整筆備抵」的表就會產出不存在的逐桶帳面。
            eq(f"{doc}|{cls} book 不可用 BOOK_COLS 當欄名",
               any(c in ("帳面金額", "公允價值總額")
                   for r in recs for c in (r.get("printed_totals") or {})), False)

        if cells:
            eq(f"{doc} 格式檢查通過", facts_mod.validate(cells), [])

    _test_subtotal_rows_dropped()
    print(f"  掃過 {docs} 份 v4/raw,驗到 {cost_seen} 份成本 record")
    eq(f"驗到的成本 record 不得少於 {COST_SEEN_MIN}(否則成本斷言是空轉)",
       cost_seen >= COST_SEEN_MIN, True)


def _test_subtotal_rows_dropped():
    """合計/小計列不准進 record —— **獨立於 `aggregate()` 的斷言。**

    不能用「跟 `aggregate()` 比」來守這條:`_SUBTOTAL_WORDS` 是兩邊共用的常數,
    弄壞它會讓兩條路徑一起降級,對照就看不出差異(實測:清空常數後 397 條全綠)。
    所以這裡直接餵合成資料驗結果。

    這條擋的是真事故:`202302_5843_AI3|Trading` 的 v4 產出含「小計 49,737,828」
    「合計 55,717,136」兩列,漏濾就會進 `facts/`、分不到桶、落進 `View.unknown`,
    同一份資料兩個閘門給出相反答案。
    """
    blk = {"book": {"page": 1, "printed_subtotal": 300,
                    "rows": [{"name": "政府公債", "group": None, "amount": 100},
                             {"name": "公司債", "group": None, "amount": 200},
                             {"name": "小計", "group": None, "amount": 300},
                             {"name": "合計", "group": None, "amount": 300}]}}
    recs = adapter.to_facts_records("X_AI3", "AC", blk, "113/12/31")
    names = [r["name"] for rec in recs for r in rec["rows"]]
    eq("合計/小計列不進 facts record", names, ["政府公債", "公司債"])


if __name__ == "__main__":
    print("== A-1 v4 → facts ==")
    main()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
