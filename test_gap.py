# -*- coding: utf-8 -*-
"""`fill._taxonomy_gap` 的回歸:**分類表缺口與兩層附註小計必須分得開**。

兩者的症狀一模一樣(第 5 道「列皆可分桶」失敗),處置卻相反:

    分類表缺口 → 擴頁永遠修不好,要短路產提案(混合情況也算,見 case_mixed)
    兩層附註小計 → 擴頁正好修得好,不准短路

⚠️ 2026-07-29:BLOCKED 出口在 `use_policy=True` 已經退場(方案 B,見
core.ingest.classify_outcome)——「短路」現在的意思是「產出提案、FILED 歸檔、
進 review 佇列」,不再是「整格擋著不歸檔」。`_taxonomy_gap` 本身回不回
`None` 的判準沒變,這裡只是把過時的措辭改掉。

判錯任一邊都有代價:把小計當缺口 → 那格的明細永遠抓不到;
把缺口當小計 → 白燒擴頁(level 2 的頁文字是 level 0 的 4.7 倍)。

跑法:python3 test_gap.py
"""
import copy
import json

import fill
import locate

DOC, CLS = "202504_國泰_個體", "Trading"
KEY = f"{DOC}|{CLS}"

#: 用**真實**的一格當底,只換名字 —— 假造金額會讓別道檢查先破,測不到要測的東西。
#: 第一版就是栽在這裡:自造的 printed_total 讓第 4 道失敗,短路正確地沒觸發,
#: 於是「測過了」卻完全沒驗到真實情境。
_REAL = json.load(open(f"facts/{DOC}.json", encoding="utf-8"))[KEY]
_LOC = locate.locate(f"pdf_cache/{DOC}.pdf")


def _rename(mapping):
    """把真實 record 裡的某些名字換掉,其餘(含金額)原封不動。"""
    recs = copy.deepcopy(_REAL)
    for r in recs:
        r.pop("_by", None)
        for row in r["rows"]:
            row["name"] = mapping.get(row["name"], row["name"])
    return recs


def case_taxonomy_gap():
    """真的新科目名 → 判為缺口,產出提案。

    ⚠️ 這一格有**兩份** record(附註 p35 + 明細表 p135),未收錄的名字兩邊都有,
    所以第 3 道「雙表互對」也會跟著報「兩邊都對不到桶」。那是同一個根因的第二個症狀
    —— 舊版判準要求「所有失敗都是第 5 道」,在這裡就會漏判,等於整個修沒作用。
    """
    gap = fill._taxonomy_gap(_rename({"基金受益憑證": "基金收益憑證"}), _LOC)
    yield ("判為分類表缺口", gap is not None, gap)
    if gap:
        yield ("提案指向股票", gap[0]["bucket"] == "股票", gap)
        yield ("只提一個名字", len(gap) == 1, gap)


def case_two_layer_subtotal():
    """兩層附註的小計列 → **不准**判為缺口(擴頁才修得好)。

    名字取自玉山 2021H1 OCI 主附註 p23 的實際兩列:相加剛好等於錨、前四道全綠,
    只有第 5 道攔得下來,而明細在子附註 p24 —— 這種一定要擴。
    """
    gap = fill._taxonomy_gap(
        _rename({"公司債": "透過其他綜合損益按公允價值衡量之債務工具投資"}), _LOC)
    yield ("不判為缺口(留給擴張)", gap is None, gap)


def case_mixed():
    """一個提得出、一個提不出 → **仍判為缺口**,不是保守走擴張。

    fill.py 的說明明確寫著:提不出來的那個不代表是小計,也可能是既有科目
    沒收錄的註腳變體(實測玉山 202504 AC:「國外機構發行債券（註二）」propose
    不出來,但它就是「國外機構發行債券」本身)。只要**至少一個**名字生得出
    提案,整組就判定缺口;生不出提案的名字 bucket=None,一併送人審。

    這條原本的斷言是「gap is None」,鎖的是舊行為(2026-07-29 之前)。
    fill.py 已經明確改掉且寫了理由,測試沒跟上 —— 這正是 core.ingest 那份
    複製品悄悄漂移、被 test_ingest_equiv 的 E5 抓到的同一個根因。"""
    gap = fill._taxonomy_gap(
        _rename({"基金受益憑證": "基金收益憑證",
                 "公司債": "透過其他綜合損益按公允價值衡量之債務工具投資"}), _LOC)
    yield ("混合時判為缺口(至少一個提得出提案)", gap is not None, gap)
    if gap:
        names = {p["name"] for p in gap}
        yield ("兩個名字都在提案裡", names == {
            "基金收益憑證", "透過其他綜合損益按公允價值衡量之債務工具投資"}, gap)
        resolved = {p["name"]: p["bucket"] for p in gap}
        yield ("提得出的那個有桶", resolved["基金收益憑證"] == "股票", gap)
        yield ("提不出的那個 bucket=None(送人審,不是猜)",
               resolved["透過其他綜合損益按公允價值衡量之債務工具投資"] is None, gap)


def case_amount_broken_too():
    """名字沒收錄,**而且**金額被動過 → 收錄了也不會過,不准短路。

    這條在守「模擬」那一步:光看名字提不提得出來不夠,還要問收錄之後整格過不過。
    """
    recs = _rename({"基金受益憑證": "基金收益憑證"})
    recs[0]["rows"][0]["cols"][recs[0]["total_col"]] += 1      # 算術破掉
    gap = fill._taxonomy_gap(recs, _LOC)
    yield ("算術也破時不短路", gap is None, gap)


def case_already_covered():
    """全部都分得到桶 → 沒有缺口可言。"""
    gap = fill._taxonomy_gap(_rename({}), _LOC)
    yield ("無未收錄名字時回 None", gap is None, gap)


def main():
    bad = 0
    for case in (case_taxonomy_gap, case_two_layer_subtotal, case_mixed,
                 case_amount_broken_too, case_already_covered):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
