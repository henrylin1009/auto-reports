# -*- coding: utf-8 -*-
"""事實庫邊界驗證的回歸:**證明壞資料真的會被 validate() 抓到**。

只驗「會通過」沒有意義 —— 閘門沒接好也會全綠。所以先注入五種壞資料,
逐一確認 validate() 回報非空清單,再驗現有 19 格全部通過。

跑法:python3 test_facts.py
"""
import copy

import facts

GOOD_KEY = "202404_5843_AI3|Trading"
GOOD_REC = {
    "doc": "202404_5843_AI3", "class": "Trading",
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


def case_existing_facts_pass():
    """現有 19 格全部通過。"""
    cells = facts.load()
    yield ("19 格", len(cells) == 19, f"len={len(cells)}")
    problems = facts.validate(cells)
    yield ("現有事實庫零問題", not problems, problems)


def main():
    bad = 0
    for case in (case_missing_total_col, case_float_in_cols, case_empty_rows,
                 case_key_content_mismatch, case_unknown_field,
                 case_existing_facts_pass):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
