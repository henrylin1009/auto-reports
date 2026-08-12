# -*- coding: utf-8 -*-
"""視圖層的回歸:**證明「取不到就 null」是真的,而不是取不到就湊一個。**

這一層最危險的失敗長得像成功:wide 有數字、總額對得上、網站畫得出來,
但每一桶都是另一個口徑的數字(memory/oracle-basis-mismatch 那個已發布的 bug)。
所以這裡驗的不是「算得對」,是**該空的時候真的空**。

跑法:python3 test_wide.py
"""
import copy
import json

import buckets
import transcribe
import wide

CELLS = json.load(open("scratchpad/rows_v3.json", encoding="utf-8"))
CTBC_H1 = "202302_中信_個體|OCI"      # 單一附註、逐項成本 → 帳面在文件裡不存在
MEGA = "202404_兆豐_個體|Trading"     # 明細表雙欄,成本欄有抄欄合計 44,631,513
CATHAY = "202404_國泰_個體|OCI"
FUBON = "202404_富邦_個體|Trading"    # 附註把跨桶科目併成「其他」→ 來源不可用


def case_cost_only_gives_null():
    """全部來源都是成本 → **帳面必須是 null**,不准拿成本頂替。"""
    v = wide.view(CELLS[CTBC_H1], "帳面")
    yield ("帳面 = null", v.book is None, f"{v.book}")
    yield ("而且說得出理由", "成本" in (v.reason or ""), f"{v.reason}")
    c = wide.view(CELLS[CTBC_H1], "成本")
    yield ("成本則取得到(對照組,證明不是整格壞掉)", c.ok, f"{c.reason} {c.book}")


def case_col_total_catches_error():
    """第 6 道:欄合計對不上必須報失敗,而且指得出是哪一欄。"""
    rec = copy.deepcopy(CELLS[MEGA][1])
    yield ("原樣通過", transcribe.check_col_totals(rec) is None,
           f"{transcribe.check_col_totals(rec)}")
    rec["rows"][0]["cols"]["取得成本"] += 1
    msg = transcribe.check_col_totals(rec)
    yield ("成本欄 +1 → 失敗", bool(msg), f"{msg}")
    yield ("訊息指得出是「取得成本」那欄", "取得成本" in (msg or ""), f"{msg}")


def case_cost_needs_verifiable_total():
    """沒抄欄合計 → 成本欄**不准採用**(驗不到的數字不上網)。"""
    recs = copy.deepcopy(CELLS[CATHAY])
    v = wide.view(recs, "成本")
    yield ("有欄合計時取得到", v.ok, f"{v.reason}")
    for r in recs:
        r.pop("printed_totals", None)
    v2 = wide.view(recs, "成本")
    yield ("拿掉欄合計就變 null", v2.book is None, f"{v2.book}")
    yield ("理由要講「驗不到」", "驗不到" in (v2.reason or ""), f"{v2.reason}")


def case_unknown_blocks():
    """有列進不了 7 桶 → 這個 view 不算 ok,即使加總剛好對得上。"""
    recs = copy.deepcopy(CELLS[CATHAY])
    # ⚠️ 要改**實際被取用的那份** —— 第一版改了附註 p37,而帳面口徑取的是明細表
    # p133(公允獨立成欄,優先),結果注入完全沒作用、測試綠著什麼都沒驗到。
    used = wide.pick(recs, "帳面")[0]
    used["rows"][0]["name"] = "某個沒人認得的名目"
    v = wide.view(recs, "帳面")
    yield ("認不得的列會被列出來", len(v.unknown) == 1, f"{v.unknown}")
    yield ("而且讓 view 不 ok", not v.ok, f"ok={v.ok}")
    yield ("金額沒有被偷偷算進任何桶",
           v.total + sum(v.side.values()) != v.expected,
           f"{v.total} vs {v.expected}")


def case_side_not_in_wide():
    """衍生與評價調整**不進 7 桶**,但恆等式要三段對得起來。"""
    v = wide.view(CELLS[MEGA], "帳面")
    yield ("兆豐 Trading 有衍生", v.side[wide.DERIVATIVE] > 0, f"{v.side}")
    yield ("三段恆等式成立", v.ok, f"{v.total}+{v.side} vs {v.expected}")
    yield ("債券MV 不大於類別合計(子集不得大於全集)",
           v.bond_mv <= v.expected, f"{v.bond_mv} vs {v.expected}")


def case_coarse_source_refused():
    """**跨桶合併列的來源不准拿來分桶** —— 這是「全綠但每一桶都錯」那個形狀。

    富邦 202404 Trading 附註 p38 把 政府公債 1,799,570 + 公司債 3,565,242 併進
    「其他 16,378,254」(明細表註:各項未超過本項目 5%)。附註六道檢查全過、
    合計等於錨,拿它分桶卻會讓三個桶同時錯 —— 沒有任何一道檢查看得到。
    """
    recs = copy.deepcopy(CELLS[FUBON])
    yield ("附註 p38 被判為跨桶合併來源",
           transcribe.coarse(recs, buckets) == {38},
           f"{transcribe.coarse(recs, buckets)}")
    v = wide.view(recs, "帳面")
    yield ("帳面改取明細表 p151", v.rec["source_page"] == 151,
           f"p{v.rec['source_page']}")
    yield ("公債 = 1,799,570 + 1,225,795(用附註只會是 1,225,795)",
           v.book["GB"] == 3025365, f"{v.book['GB']:,}")
    yield ("公司債沒有消失(用附註會少掉 3,565,242)",
           v.book["公司債"] == 15387901, f"{v.book['公司債']:,}")
    # 注入:把明細表其中一列改掉 → 三列加起來不再等於那一列 → **不准再判成合併列**
    bad = copy.deepcopy(CELLS[FUBON])
    bad[1]["rows"][2]["cols"]["公允價值總額"] += 1
    msg = transcribe.check_cross(bad, buckets)
    yield ("加不起來就不准判合併列", "合併列" not in (msg or ""), f"{msg}")
    yield ("而且要報硬失敗", (msg or "").startswith("金額對不上"), f"{msg}")
    yield ("此時也不再排除 p38(不是靠版型記住的)",
           transcribe.coarse(bad, buckets) == set(),
           f"{transcribe.coarse(bad, buckets)}")


def main():
    bad = 0
    for case in (case_cost_only_gives_null, case_col_total_catches_error,
                 case_cost_needs_verifiable_total, case_unknown_blocks,
                 case_side_not_in_wide, case_coarse_source_refused):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
