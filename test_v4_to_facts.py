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
        return adapter.aggregate(sub["rows"],
                                 sub.get("printed_subtotal") or sub.get("total"))

    b, c = agg("book"), agg("cost")
    book_is_cost = b is not None and b.basis == "成本"
    return {"帳面": None if book_is_cost else b,
            "成本": b if book_is_cost else c}



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
    _test_file_cell_roundtrip()
    print(f"  掃過 {docs} 份 v4/raw,驗到 {cost_seen} 份成本 record")
    eq(f"驗到的成本 record 不得少於 {COST_SEEN_MIN}(否則成本斷言是空轉)",
       cost_seen >= COST_SEEN_MIN, True)


def _test_subtotal_rows_dropped():
    """合計/小計列不准進 record —— **獨立於 `aggregate()` 的斷言。**

    不能用「跟 `aggregate()` 比」來守這條:`_SUBTOTAL_WORDS` 是兩邊共用的常數,
    弄壞它會讓兩條路徑一起降級,對照就看不出差異(實測:清空常數後 397 條全綠)。
    所以這裡直接餵合成資料驗結果。

    這條擋的是真事故:`202302_兆豐_個體|Trading` 的 v4 產出含「小計 49,737,828」
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


def _test_file_cell_roundtrip():
    """端到端:`v4/raw` → `to_facts_records()` → `file_cell()` → `facts/` → 讀得回來。

    這是 A-1 那條接縫**真的接上了**的證據 —— 前面幾條只驗轉換結果,
    這條驗它進得了事實庫、讀得回來、而且身分正確。

    兩條身分斷言不可省:
      · 機器寫的不准帶 `_src`(那是人工標記)—— 帶了會把自己標成人工裁示過,
        反而擋住之後所有機器更新
      · 人工裁示過的格,機器不准覆蓋(2026-08-10 選項 1)
    """
    import shutil
    import tempfile
    from core import webdata

    raw = json.load(open("v4/raw/202502_富邦_個體.json", encoding="utf-8"))
    doc, parsed = raw["doc"], raw["parsed"]
    ws = tempfile.mkdtemp(prefix="fc_")
    try:
        for cls in ("Trading", "OCI", "AC"):
            recs = adapter.to_facts_records(doc, cls, parsed[cls], parsed.get("bs_date"))
            webdata.file_cell(doc, cls, recs, via="v4/reader", facts_dir=ws)
        back = facts_mod.load(ws)
        eq("E1 三格都進得了事實庫", len(back), 3)
        eq("E2 機器寫的不帶 _src",
           any("_src" in row for recs in back.values()
               for rec in recs for row in rec["rows"]), False)
        eq("E3 _by.via 標成 v4/reader",
           {rec["_by"]["via"] for recs in back.values() for rec in recs}, {"v4/reader"})

        key = f"{doc}|OCI"
        cells = facts_mod.load(ws)
        cells[key][0]["rows"][0]["_src"] = {"by": "henrylin", "at": "now"}
        facts_mod.save(cells, ws)
        try:
            webdata.file_cell(doc, "OCI",
                              adapter.to_facts_records(doc, "OCI", parsed["OCI"],
                                                       parsed.get("bs_date")),
                              via="v4/reader", facts_dir=ws)
            eq("E4 機器覆蓋人工裁示過的格必須被擋", "沒擋", "要擋")
        except webdata.EditError:
            eq("E4 機器覆蓋人工裁示過的格被擋下", True, True)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    print("== A-1 v4 → facts ==")
    main()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
