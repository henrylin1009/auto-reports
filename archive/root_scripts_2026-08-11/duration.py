# -*- coding: utf-8 -*-
"""從浮虧率反推 AC / OCI 的**相對**久期。

## 為什麼是相對的

沒有殖利率序列,所以算不出「幾年」。但五家吃的是同一波升息,所以

    浮虧率(t) ≈ −D × (市場殖利率 − 平均買進殖利率)

同一天跨行比,右邊那個括號對五家幾乎一樣,**比值就是久期的比值**。
要絕對值得另外接一組公債殖利率,那是另一件事。

## 兩個一定要做的修正

① **扣掉貨幣市場**。AC 帳上 35~88% 是可轉讓定期存單、央行定期存單、短期票券,
   那些不生浮虧。中信 2022 全帳算是 −3.62%,扣掉才是 −7.15%,差一倍。
   兆豐自己就只揭露「債券投資」那段(scope='扣貨幣市場'),不必再扣。

② **還原新購稀釋**。用差分而不是水準:買進成本那一項在差分裡消掉。
   新券以零浮虧進來會稀釋比率,所以 δ = m₁×(B₁/B₀) − m₀ 而不是 m₁ − m₀。
   ⚠️ 這個修正在部位變動大的年份會反過來主導結果(玉山 OCI 一年長 33%,
   修正後的 δ 只剩 +0.23pt,比值就爆掉)。所以**水準比與差分比要一起看**,
   兩個差很多的那一格不要用。

## 這支不做的事

不外插到沒有資料的年份、不把兩家的結果推廣到五家。n=5 的跨行相關做不出顯著
(精確雙尾 p:即使 ρ=1.0 也只有 0.017),這裡只出數字,不出「有顯著關係」的話。
"""
import json
import statistics as st

import capital

BANKS = ("中信", "兆豐", "國泰", "富邦", "玉山")
DUR = ("GB", "公司債", "金融債", "資產基礎", "其他")   # 有存續期間;排掉股票與貨幣市場
CLASSES = ("Trading", "OCI", "AC")
CODE = {v: k for k, v in capital.BANKS.items()}


def _load(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


def ac_marks():
    """回 {銀行: {年: 浮虧率%}}。只收驗過的(capital.json),佇列裡的不撿。

    scope='全帳' 的要自己扣貨幣市場:整筆浮虧都落在有久期那段,
    所以是 (公允−帳面) / (帳面−貨幣市場),不是 (公允−帳面)/帳面。
    """
    store = (_load("capital.json", {}) or {}).get("fair_value", {})
    out, seen = {}, {}
    for doc, recs in store.items():
        bank = capital.BANKS.get(doc.split("_")[1])
        for r in recs:
            if r.get("basis_norm") != "個體":
                continue
            yr = int(str(r["period"])[:4])
            book, fair = r["book"], r["fair"]
            if r.get("scope") == "扣貨幣市場":
                base = book
            else:
                full, ex = capital.ac_totals(f"{yr}04_{CODE[bank]}_AI3")
                if not ex:
                    continue
                base = ex
            m = (fair - book) / base * 100
            # 跨份:中間年度出現在兩份年報,兩次獨立抄讀要一致
            key = (bank, yr)
            if key in seen and abs(seen[key] - m) > 0.05:
                out.setdefault(bank, {}).pop(yr, None)
                seen[key] = None
                continue
            if seen.get(key) is None and key in seen:
                continue
            seen[key] = m
            out.setdefault(bank, {})[yr] = m
    return out


def oci_marks(path="data.json"):
    """回 {銀行: {年: 浮虧率%}}。OCI 的成本欄只有年報有,所以只取 H2。"""
    d = _load(path)
    out = {}
    for b in BANKS:
        for p in d["periods"]:
            if not p.endswith("H2"):
                continue
            w, c = d["wide"].get(f"{p}|{b}"), d["wide_cost"].get(f"{p}|{b}")
            if not w or not c:
                continue
            bv = sum(w.get(f"OCI_{k}") or 0 for k in DUR)
            cv = sum(c.get(f"OCI_{k}") or 0 for k in DUR)
            if cv:
                out.setdefault(b, {})[int(p[:4])] = (bv / cv - 1) * 100
    return out


def weights(path="data.json"):
    """回 {銀行: {年: {類別: 佔比%}}}(只算有久期的部位)。"""
    d = _load(path)
    out = {}
    for b in BANKS:
        for p in d["periods"]:
            if not p.endswith("H2") or not d["wide"].get(f"{p}|{b}"):
                continue
            w = d["wide"][f"{p}|{b}"]
            t = {cl: sum(w.get(f"{cl}_{k}") or 0 for k in DUR) for cl in CLASSES}
            s = sum(t.values())
            if s:
                out.setdefault(b, {})[int(p[:4])] = {k: v / s * 100 for k, v in t.items()}
    return out


def ratios(ac, oci):
    """回 {銀行: {'水準': [...], '差分': [...]}} 的 AC/OCI 久期比。"""
    out = {}
    for b in BANKS:
        a, o = ac.get(b) or {}, oci.get(b) or {}
        yrs = sorted(set(a) & set(o))
        lvl = [(y, a[y] / o[y]) for y in yrs if abs(o[y]) > 0.5]
        dif = []
        for y in yrs:
            if y - 1 not in a or y - 1 not in o:
                continue
            da, do = a[y] - a[y - 1], o[y] - o[y - 1]
            if abs(do) > 0.5:
                dif.append((y, da / do))
        out[b] = {"水準": lvl, "差分": dif, "年": yrs}
    return out


def report():
    ac, oci, wt = ac_marks(), oci_marks(), weights()
    rat = ratios(ac, oci)
    yrs = sorted({y for v in oci.values() for y in v})

    print("AC 浮虧率(已扣貨幣市場,%)      —— 空白 = 尚未抽到或跨份不一致")
    print(f"{'銀行':<6}" + "".join(f"{y:>9}" for y in yrs))
    for b in BANKS:
        print(f"{b:<6}" + "".join(
            f"{ac[b][y]:8.2f}%" if y in (ac.get(b) or {}) else f"{'—':>9}" for y in yrs))

    print("\nOCI 浮虧率(%)")
    print(f"{'銀行':<6}" + "".join(f"{y:>9}" for y in yrs))
    for b in BANKS:
        print(f"{b:<6}" + "".join(
            f"{oci[b][y]:8.2f}%" if y in (oci.get(b) or {}) else f"{'—':>9}" for y in yrs))

    print("\nAC / OCI 久期比")
    print(f"{'銀行':<6}{'水準比(中位)':>14}{'n':>4}{'差分比(中位)':>14}{'n':>4}")
    for b in BANKS:
        L = [v for _, v in rat[b]["水準"]]
        D = [v for _, v in rat[b]["差分"]]
        f = lambda v: f"{st.median(v):13.2f}" if v else f"{'—':>13}"   # noqa: E731
        print(f"{b:<6}{f(L)} {len(L):>3}{f(D)} {len(D):>3}")

    print("\n曝險路徑:利率風險有多少走 AC(不進權益/CET1)")
    print(f"{'銀行':<6}{'AC權重':>9}{'OCI權重':>9}{'AC/OCI久期':>12}{'AC藏住':>9}")
    for b in BANKS:
        L = [v for _, v in rat[b]["水準"]]
        if not L or not wt.get(b):
            print(f"{b:<6}{'—':>9}{'—':>9}{'—':>12}{'—':>9}")
            continue
        y = max(wt[b])
        w, r = wt[b][y], st.median(L)
        tot = w["AC"] * r + w["OCI"]
        print(f"{b:<6}{w['AC']:8.1f}%{w['OCI']:8.1f}%{r:12.2f}{w['AC']*r/tot*100:8.0f}%")


if __name__ == "__main__":
    report()
