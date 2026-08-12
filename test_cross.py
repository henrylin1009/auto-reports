# -*- coding: utf-8 -*-
"""第 3 道(雙表互對)的靈敏度回歸:**證明它會失敗**。

為什麼需要這支:第 3 道是四道檢查裡唯一驗得到「名字↔金額配對」的,
而它一旦悄悄變成恆真,整條管線就沒有東西在看配對了 —— 前三道加的是金額欄,
名字整排錯位照樣全綠(見 check_identity 的 docstring)。

實測抓到過的洞(2026-07-26):原本只比**金額集合**,把明細表的「公司債」與
「金融債券」名字互換,兩邊金額集合一模一樣 → 完全驗不到。修法是同一筆金額
在兩邊掛的名字,桶必須一致。這支測試就是那個洞的守門員。

跑法:python3 test_cross.py   (沒有 pytest,本檔自己就是可執行的)
"""
import copy
import json

import buckets
import transcribe as T

KEY = "202404_兆豐_個體|Trading"          # 兆豐 2024:附註逐項成本、明細表逐項公允


def _find(rec, name):
    return [x for x in rec["rows"] if x["name"] == name][0]


def _swap_names(recs):
    a, b = _find(recs[1], "公司債"), _find(recs[1], "金融債券")
    a["name"], b["name"] = b["name"], a["name"]


#: (說明, 改動, 期望). 期望 "△"=降級、"✗"=必須報失敗
CASES = [
    ("原樣:5 項逐列對上,股票因顆粒度降級", lambda r: None, "△"),
    ("明細表 公司債↔金融債券 名字互換", _swap_names, "✗"),
    ("明細表 政府債券 取得成本 +1",
     lambda r: _find(r[1], "政府債券")["cols"].__setitem__("取得成本", 163_519), "✗"),
    ("明細表 出現分桶表認不得的名字",
     lambda r: _find(r[1], "證券化商品").__setitem__("name", "阿貓阿狗"), "✗"),
]


def main():
    data = json.load(open("scratchpad/rows_r2.json", encoding="utf-8"))
    bad = 0
    for label, mut, want in CASES:
        recs = copy.deepcopy(data[KEY])
        mut(recs)
        got = T.check_cross(recs, buckets)
        # None=通過、PARTIAL 開頭=降級、其餘字串=失敗
        kind = "✓" if got is None else ("△" if got.startswith(T.PARTIAL) else "✗")
        ok = kind == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} 期望{want} 得{kind}  {label}")
        if not ok:
            print(f"      → {got}")
    print("\n全過" if not bad else f"\n{bad} 項不符 —— 第 3 道的靈敏度變了")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
