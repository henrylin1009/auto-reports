# -*- coding: utf-8 -*-
"""S6 同義詞產生器的回歸:**證明它真的長得出來,而且長錯時會擋。**

「跑起來沒報錯」對這支程式毫無意義 —— 它現在的輸出是「2 組已涵蓋、0 組要推定」,
因為那兩組正是我先前手工塞進 SYN 的。所以要證明的是**把手工那條拿掉、它自己長回來**,
以及三種長錯的路各自會被擋下(見 memory/checks-must-fail:寫完檢查就注入錯誤)。

跑法:python3 test_synonyms.py
"""
import copy
import json

import buckets
import synonyms

CELLS = json.load(open("scratchpad/rows_v3.json", encoding="utf-8"))
CATHAY = "202404_5835_AI3|OCI"          # 附註「金融債」 / 明細表「金融債券」 29,073,073
MEGA = "202404_5843_AI3|Trading"        # 跨口徑:附註成本 ↔ 明細表「取得成本」欄


class without:
    """暫時把某些名字從分桶表拿掉 —— 模擬「這個名目第一次出現」。"""

    def __init__(self, *names):
        self.names = [buckets.norm(n) for n in names]

    def __enter__(self):
        self.saved = dict(buckets._SYN_N)
        for n in self.names:
            buckets._SYN_N.pop(n, None)

    def __exit__(self, *a):
        buckets._SYN_N.clear()
        buckets._SYN_N.update(self.saved)


def case_grows():
    """核心:一邊認得、一邊不認得 → **自動推定出正確的桶**。"""
    with without("金融債券"):
        res = synonyms.scan({CATHAY: CELLS[CATHAY]})
    got = res.get(synonyms.PROPOSE, [])
    yield ("拿掉「金融債券」後會被提出來", len(got) == 1, f"{res}")
    yield ('推定的桶是「金融債」而不是別的',
           bool(got) and '"金融債券": "金融債",' in got[0][3], f"{got}")


def case_cross_basis():
    """口徑不同的格子也長得出來 —— 靠 align 挑明細表的「取得成本」欄。

    這條容易默默失效:align 回 None 時 candidates 直接回空,**看起來就像沒同義詞**。
    """
    with without("公司債券"):
        res = synonyms.scan({MEGA: CELLS[MEGA]})
    got = res.get(synonyms.PROPOSE, [])
    yield ("兆豐(附註成本 vs 明細表雙欄)長得出候選", len(got) >= 1, f"{res}")
    yield ('"公司債券" 推定為「公司債」',
           any('"公司債券": "公司債",' in g[3] for g in got), f"{got}")


def case_conflict():
    """兩邊都認得、桶卻不同 → 必須報衝突,不准當成同義詞吞下去。"""
    cell = copy.deepcopy(CELLS[CATHAY])
    for r in cell[1]["rows"]:
        if r["name"] == "金融債券":
            r["name"] = "政府公債"        # 明細表被抄成另一個桶的名字
    res = synonyms.scan({CATHAY: cell})
    yield ("同金額掛到不同桶 → 衝突", len(res.get(synonyms.CONFLICT, [])) == 1, f"{res}")
    yield ("--check 會 exit 1", synonyms.scan({CATHAY: cell}).get(synonyms.CONFLICT),
           "衝突未被歸類")


def case_ambiguous_amount():
    """同一欄裡金額重複 → **不准配對**(誰對誰是猜的)。"""
    a = {"doc": "x", "class": "OCI", "source_page": 1, "total_col": "c",
         "printed_total": 200, "rows": [{"name": "公司債", "cols": {"c": 100}},
                                        {"name": "政府公債", "cols": {"c": 100}}]}
    b = copy.deepcopy(a)
    b["source_page"] = 2
    b["rows"] = [{"name": "甲名目", "cols": {"c": 100}},
                 {"name": "乙名目", "cols": {"c": 100}}]
    yield ("兩邊各有兩列同額 → 0 組候選", synonyms.candidates([a, b]) == [],
           f"{synonyms.candidates([a, b])}")
    # 對照組:同一組資料改成金額相異,就該長得出來 —— 否則上一條是恆真通過
    a2, b2 = copy.deepcopy(a), copy.deepcopy(b)
    a2["rows"][1]["cols"]["c"] = b2["rows"][1]["cols"]["c"] = 50
    yield ("金額相異的對照組長得出 2 組(證明上一條不是恆真)",
           len(synonyms.candidates([a2, b2])) == 2, f"{synonyms.candidates([a2, b2])}")


def case_pending_not_guessed():
    """人審佇列裡的名字,**不准**被金額配對自動推定掉。

    ⚠️ 用臨時塞的假名字,**不准拿真的待審名目當測資** —— 第一版拿了
    「國外機構發行債券」,結果那個決定一做完(2026-07-26 判為公債)這條就綠著
    失效了。測的是機制,綁到會被解決的資料上等於幫自己裝了一個定時失效的檢查。
    """
    a = {"doc": "x", "class": "OCI", "source_page": 1, "total_col": "c",
         "printed_total": 100, "rows": [{"name": "金融債", "cols": {"c": 100}}]}
    b = copy.deepcopy(a)
    b["source_page"] = 2
    b["rows"] = [{"name": "某個分不出來的債券", "cols": {"c": 100}}]
    buckets.PENDING["某個分不出來的債券"] = "測試用"
    buckets._PEND_N.add(buckets.norm("某個分不出來的債券"))
    try:
        res = synonyms.scan({"fake": [a, b]})
    finally:
        buckets.PENDING.pop("某個分不出來的債券")
        buckets._PEND_N.discard(buckets.norm("某個分不出來的債券"))
    yield ("待人審的名字不會被推定", not res.get(synonyms.PROPOSE), f"{res}")
    yield ("而是留在人審", len(res.get(synonyms.HUMAN, [])) == 1, f"{res}")


def main():
    bad = 0
    for case in (case_grows, case_cross_basis, case_conflict,
                 case_ambiguous_amount, case_pending_not_guessed):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
