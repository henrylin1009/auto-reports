# -*- coding: utf-8 -*-
"""事實庫邊界驗證的回歸:**證明壞資料真的會被 validate() 抓到**。

只驗「會通過」沒有意義 —— 閘門沒接好也會全綠。所以先注入五種壞資料,
逐一確認 validate() 回報非空清單,再驗現有 19 格全部通過。

跑法:python3 test_facts.py
"""
import copy

import facts

#: 事實庫格數的下限(不是等於)。抄列只會讓它變大;變小代表有格子掉了。
#: 22 = T0 搬進來的 19 格 + T3 驗收跑出的 202504_國泰_個體 三格。
FLOOR = 22

GOOD_KEY = "202404_兆豐_個體|Trading"
GOOD_REC = {
    "doc": "202404_兆豐_個體", "class": "Trading",
    "source_page": 31, "source_kind": "附註",
    "total_col": "帳面金額", "printed_total": 100,
    "rows": [{"name": "公司債", "cols": {"帳面金額": 100}}],
}


def _cells(rec):
    return {GOOD_KEY: [rec]}


def case_missing_total_col():
    """缺 total_col 這個必要欄位。"""
    rec = copy.deepcopy(GOOD_REC)
    del rec["total_col"]
    problems = facts.validate(_cells(rec))
    yield ("缺必要欄位被抓到", bool(problems), problems)


def case_float_in_cols():
    """cols 的 value 是 float,不是 int。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["rows"][0]["cols"]["帳面金額"] = 100.0
    problems = facts.validate(_cells(rec))
    yield ("cols 有 float 被抓到", bool(problems), problems)


def case_empty_rows():
    """rows 是空 list。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["rows"] = []
    problems = facts.validate(_cells(rec))
    yield ("rows 空被抓到", bool(problems), problems)


def case_key_content_mismatch():
    """key 的 doc/class 與 record 內的 doc/class 不一致。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["class"] = "OCI"
    problems = facts.validate(_cells(rec))
    yield ("key 與內容不一致被抓到", bool(problems), problems)


def case_unknown_field():
    """出現未知欄位(例如已停用的 basis)。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["basis"] = "cost"
    problems = facts.validate(_cells(rec))
    yield ("未知欄位被抓到", bool(problems), problems)


def case_row_src_accepted():
    """`_src`(人工列的稽核欄位,2026-07-30 加)不准被當成未知欄位擋下來——
    否則 W2 的「網頁改一列」整個立刻被 Gate 1 擋死,跟沒加一樣。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["rows"][0]["_src"] = {"by": "henrylin", "at": "2026-07-30T12:00",
                              "why": "文字層缺一位千分位,用印出合計反推"}
    problems = facts.validate(_cells(rec))
    yield ("帶 _src 的列通過驗證", not problems, problems)


def case_row_src_does_not_bypass_schema():
    """`_src` 只是多一個欄位,**不是通行證**——名字還是不准是空字串,
    cols 還是不准塞 float。人工列一樣要守格式,只是不用守六道語意檢查。"""
    rec = copy.deepcopy(GOOD_REC)
    rec["rows"][0]["_src"] = {"by": "henrylin", "at": "2026-07-30T12:00", "why": "x"}
    rec["rows"][0]["cols"]["帳面金額"] = 100.5
    problems = facts.validate(_cells(rec))
    yield ("有 _src 也擋得住 float", bool(problems), problems)


def case_existing_facts_pass():
    """現有事實庫全部通過。

    ⚠️ **不要把格數寫死。** 事實庫會隨 `/fill` 長大,寫死格數等於每抄一格就紅一次,
    而這個案例要驗的是「現有資料乾淨」,不是「現在有幾格」。只守一個下限:
    抄過的格子不該憑空消失。
    """
    cells = facts.load()
    yield (f"至少 {FLOOR} 格(實際 {len(cells)})", len(cells) >= FLOOR, f"len={len(cells)}")
    problems = facts.validate(cells)
    yield ("現有事實庫零問題", not problems, problems)


def main():
    bad = 0
    for case in (case_missing_total_col, case_float_in_cols, case_empty_rows,
                 case_key_content_mismatch, case_unknown_field,
                 case_row_src_accepted, case_row_src_does_not_bypass_schema,
                 case_existing_facts_pass):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
