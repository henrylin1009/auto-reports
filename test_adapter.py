#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_adapter.py — v4/adapter.py 與 W5(check_bucket_complete)驗收。

docs/plan_v5_統一.md P1-2 兩條閘門各要一個「注入錯誤後必須變紅」的測試,
不是只驗綠燈——恆真的測試抓不到「桶沒接好、錢悄悄消失」這種 bug
(見 memory/checks-must-fail)。

執行方式: python3 test_adapter.py       exit 0 = 全綠
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))


from v4 import adapter, witness

GOOD_ROWS = [
    {"group": "", "name": "政府公債", "amount": 100},
    {"group": "", "name": "公司債", "amount": 200},
    {"group": "", "name": "金融債", "amount": 50},
]
GOOD_SUBTOTAL = 350


def a1_split_matches_first_before_splitting():
    """T1:「定期存單-可轉讓」本身就是 buckets.SYN 的既有鍵(字序倒裝),
    先拆再查會拆散它、查不到 —— 這是實測抓到的真 bug(P1-1 開發時)。
    這條測試釘住「先整條查、查不到才拆」這個順序不能被之後的改動悄悄倒退。"""
    row = {"group": "", "name": "定期存單-可轉讓", "amount": 100}
    check("T1 整條原名優先於拆開的結果",
          adapter.bucket_row(row) == "可轉讓定存單", adapter.bucket_row(row))


def a2_group_split_resolves_generic_plus_group():
    """T2:「其他」配段落「衍生金融資產」要能透過 GROUP_SYN 解出「衍生」——
    這是 P1-1 改 prompt 要求 group/name 分開兩欄之後才通的路。"""
    row = {"group": "衍生金融資產", "name": "其他", "amount": 100}
    check("T2 GENERIC 名字配 group 解出衍生桶",
          adapter.bucket_row(row) == "衍生", adapter.bucket_row(row))


def a3_aggregate_green_on_clean_rows():
    """基準情境:乾淨的三列,桶都認得、Σ桶等於小計 → 應該合格。"""
    agg = adapter.aggregate(GOOD_ROWS, GOOD_SUBTOTAL)
    check("T3 乾淨資料 aggregate 合格", agg.ok, agg.reason)
    check("T3 七桶裡有對應金額",
          agg.book["GB"] == 100 and agg.book["公司債"] == 200 and agg.book["金融債"] == 50)


def a4_unknown_row_must_fail_not_silently_drop():
    """**注入錯誤測試(閘門一):有列對不到桶。**
    拿基準情境,加一列分桶表完全不認得的科目名 —— 這筆錢不准悄悄從
    七桶加總裡消失,aggregate 必須回報不合格,不能算出一個「看起來對」
    但漏了一列的七桶。"""
    bad_rows = GOOD_ROWS + [{"group": "", "name": "不存在的科目名稱ZZZ", "amount": 999}]
    agg = adapter.aggregate(bad_rows, GOOD_SUBTOTAL + 999)
    check("T4 有列對不到桶 → aggregate 不合格(閘門會抓,不是自主觀察)",
          not agg.ok, agg.reason)
    check("T4 unknown 清單裡點得到是哪一列",
          any("不存在的科目名稱ZZZ" in u[0] for u in agg.unknown), agg.unknown)


def a5_sum_mismatch_must_fail():
    """**注入錯誤測試(閘門二):Σ七桶 ≠ 小計。**
    每一列單獨看都認得桶,但給一個跟實際加總對不起來的 printed_subtotal
    (模擬:模型把小計抄錯,或某一列金額被改過但小計沒同步改)——
    aggregate 必須抓到,不能因為「每一列都查得到桶」就放行。"""
    agg = adapter.aggregate(GOOD_ROWS, GOOD_SUBTOTAL + 1)
    check("T5 Σ桶≠小計 → aggregate 不合格", not agg.ok, agg.reason)
    check("T5 差額有算出來(1)", "1" in (agg.reason or ""), agg.reason)


def a6_witness_w5_mismatch_forces_not_green():
    """**串到 W5**:`check_bucket_complete` 遇到對不到桶的列要回 MISMATCH,
    這樣 `ledger.classify_cell()` 才會判 RED,不會因為前面幾道 witness
    OK 就放行成 GREEN —— 這是這道 witness 存在的唯一理由,見 witness.py W5。"""
    good_book = {"rows": GOOD_ROWS, "printed_subtotal": GOOD_SUBTOTAL}
    bad_book = {"rows": GOOD_ROWS + [{"name": "查無此科目", "amount": 999}],
                "printed_subtotal": GOOD_SUBTOTAL + 999}
    check("T6a 乾淨 book → W5 OK",
          witness.check_bucket_complete(good_book)["status"] == "OK")
    check("T6b 有列對不到桶的 book → W5 MISMATCH(不是 no_witness、不是 OK)",
          witness.check_bucket_complete(bad_book)["status"] == "MISMATCH")


def a7_subtotal_rows_filtered_not_treated_as_unknown():
    """`合計`/`小計` 這類列不是投資標的,normalize_rows 要濾掉,不能被
    bucket_row 判成「對不到桶」而製造假警報(P1-1 prompt 規則的程式端保險絲)。"""
    rows, dropped = adapter.normalize_rows(
        GOOD_ROWS + [{"group": "", "name": "小計", "amount": GOOD_SUBTOTAL}])
    check("T7 小計列被濾掉,不進 rows", len(rows) == len(GOOD_ROWS))
    check("T7 小計列有被記錄在 dropped 裡(不是憑空消失)", len(dropped) == 1)


if __name__ == "__main__":
    for fn in (a1_split_matches_first_before_splitting,
               a2_group_split_resolves_generic_plus_group,
               a3_aggregate_green_on_clean_rows,
               a4_unknown_row_must_fail_not_silently_drop,
               a5_sum_mismatch_must_fail,
               a6_witness_w5_mismatch_forces_not_green,
               a7_subtotal_rows_filtered_not_treated_as_unknown):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
