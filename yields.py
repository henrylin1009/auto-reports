# -*- coding: utf-8 -*-
"""證券殖利率 —— 債券配置的「報酬」那一側。

    殖利率 = 證券利息收入 ÷ 平均(AC + OCI)部位

## 分母為什麼不含 Trading

**因為分子不含。** 附註自己寫「上表不含透過損益按公允價值衡量之金融資產或金融負債
所產生者」(中信/富邦明印;另三家把 Trading 利息放在 FVTPL 那個附註的獨立欄位)。

這件事不是小數點問題 —— 實測把 Trading 放進分母:

    橫斷面極差   0.37~0.66pt  →  0.14~0.31pt   (被壓掉一半)
    排名         兆豐最低      →  兆豐最高       (整個翻過來)

因為 Trading 佔比五家差很多(兆豐 4.5~5.1%、玉山 20~29%),含 Trading 等於
系統性懲罰 Trading 多的銀行。第一版就是這樣得出「最保守的兆豐報酬最高、
所以冒險沒被補償」的假結論。

## 富邦是另一把尺

富邦的附註只印「按攤銷後成本衡量之債務工具投資利息」= **只有 AC 桶**,
其餘四家印的是全證券(AC+OCI)。scope 由 capital.verify_interest 判好存在紀錄上,
這裡照著分流,**不併成同一欄**。只有 202404 那一份富邦同時印了兩桶,那格可比。

## 分桶殖利率

國泰與玉山的附表「利息收入明細表」把證券利息再拆成 AC / OCI 兩列。
中信與兆豐沒有這張表(它們的附表只寫「請參閱附註」),不是抄漏。
"""
import json

import capital
import config
import docid

#: 銀行清單只有一份(`config.BANKS`)—— 見 `capital.py` 同一處的說明。
BANKS = config.BANKS

#: 圖表上的排列順序。**刻意不是 `config.BANKS` 的全部** —— 這是分析頁的
#: 呈現順序,只列真的有殖利率資料的五家;新加入而還沒有資料的銀行
#: (華南/第一)排進來只會多兩條空線。
ORDER = ["中信", "兆豐", "國泰", "富邦", "玉山"]
E = 1e5          # 仟元 → 億元
CLASSES = ("AC", "OCI")


def positions(path="data.json", classes=CLASSES):
    """回 {(年, 銀行): 部位(億)}。**類別總額**,不受 wide/wide_cost 分桶錯位影響
    (實測 HEAD 與重建版只有 4 格差 0.01~0.09%,見 memory: wide-cost-bucket-alignment)。
    """
    D = json.load(open(path, encoding="utf-8"))
    out = {}
    for key, w in D["wide"].items():
        per, bank = key.split("|")
        if not per.endswith("H2") or not w:      # 有些期別是 null(那年沒抽到)
            continue
        out[(int(per[:4]), bank)] = sum(
            v or 0 for k, v in w.items() if k.split("_")[0] in classes)
    return out


def _year(raw):
    """period 正規化成西元年。各 section 的格式不同,這是坑:

        capital / fair_value   "2025-12-31"
        pnl / interest         "2025"
        equity                 "2022" 或 "113"   ← 民國與西元混用

    認不出來的回 None(由呼叫端跳過),不亂猜。
    """
    s = str(raw or "").strip()[:4].rstrip("-")
    if not s.isdigit():
        return None
    y = int(s)
    if y < 1911:                       # 民國年(equity 有幾筆是這樣印的)
        y += 1911
    return y if 1990 <= y <= 2100 else None


def interest(path="capital.json", kind="interest", field="securities"):
    """回 {(年, 銀行): rec}。只讀過驗收的,佇列裡的不撿。

    `kind` 可換成 pnl / capital / fair_value / equity —— 換 kind 就換一張表,
    而且免費得到下面的跨份對帳。period 格式的差異由 _year() 吸收。

    同一年會出現在兩份年報(當期欄與前期欄)。兩份都過驗收而且**數字相同**,
    等於兩次獨立抄讀互相背書 —— 這是免費的跨份對帳。不同就是有事,
    要嘛抄錯、要嘛財報重編,**不可以靜靜覆蓋**。
    已知的重編登記在 capital.RESTATED,照它挑;沒登記的不一致一律拋錯。
    """
    all_kinds = json.load(open(path, encoding="utf-8"))
    if kind not in all_kinds:
        raise KeyError(f"{path} 沒有 section「{kind}」;有的是 {sorted(all_kinds)}")
    store = all_kinds[kind]
    obs = {}
    for doc, recs in store.items():
        bank = docid.bank_of(doc) if docid.is_valid(doc) else None
        for r in recs:
            y = _year(r.get("period"))
            if bank and y and r.get("basis_norm") == "個體":
                obs.setdefault((y, bank), []).append((doc, r))
    if store and not obs:
        # 靜靜回空 dict 會讓下游整欄留白卻不報錯 —— 踩過一次(period 格式沒吃掉)。
        raise ValueError(f"{kind}:{len(store)} 份文件一格都沒撿到。"
                         f"檢查 basis_norm 與 period 格式(見 _year)")
    out = {}
    for (y, b), lst in obs.items():
        vals = {r.get(field) for _, r in lst}
        if len(vals) == 1:
            out[(y, b)] = lst[0][1]
            continue
        # 口徑不同不是衝突,是揭露詳略不同。富邦 202404 的附註同時印了 AC 與 OCI
        # 兩列(FY2024 = 31,302,894),202504 只印 AC(FY2024 = 26,023,280) ——
        # 同一年同一家,兩個數都對,只是範圍不同。**取比較完整的那個**。
        rich = [(d, r) for d, r in lst if r.get("scope") == "AC+OCI"]
        if rich and len({r.get(field) for _, r in rich}) == 1:
            out[(y, b)] = rich[0][1]
            continue
        pick = capital.prefer_doc(b, y, [d for d, _ in lst])
        if pick is None:
            raise ValueError(f"{y}|{b} 兩份年報讀出來不一致:{sorted(vals)};"
                             f"若是財報重編請登記到 capital.RESTATED")
        out[(y, b)] = next(r for d, r in lst if d == pick)
    return out


def table(years=(2021, 2022, 2023, 2024, 2025), data="data.json"):
    """回 {(年, 銀行): {yield, scope, ...}}。部位缺或利息缺的那格就不出現。"""
    pos, ints = positions(data), interest()
    out = {}
    for (y, b), rec in ints.items():
        if y not in years:
            continue
        # 富邦的分子只涵蓋 AC,分母就必須也只有 AC —— 兩把尺對齊比併欄重要。
        cls = ("AC",) if rec.get("scope") == "僅AC" else CLASSES
        p = positions(data, cls) if cls != CLASSES else pos
        a, z = p.get((y - 1, b)), p.get((y, b))
        if not a or not z:
            continue
        avg = (a + z) / 2
        out[(y, b)] = {"yield": rec["securities"] / E / avg * 100,
                       "interest": rec["securities"] / E, "pos": avg,
                       "scope": rec.get("scope"),
                       "ac": rec.get("sec_ac"), "oci": rec.get("sec_oci")}
    return out


def main():
    t = table()
    years = sorted({y for y, _ in t})
    print("證券殖利率 = 證券利息 ÷ 平均(AC+OCI)部位")
    print(f"{'銀行':>4} {'口徑':>7} " + "".join(f"{y:>9}" for y in years))
    for b in ORDER:
        scopes = {t[(y, b)]["scope"] for y in years if (y, b) in t}
        row = "".join(f"{t[(y,b)]['yield']:8.2f}%" if (y, b) in t else "—".rjust(9)
                      for y in years)
        print(f"{b:>4} {'/'.join(sorted(scopes)) or '—':>7} {row}")
    print(f"{'極差':>4} {'':>7} " + "".join(
        (lambda v: f"{max(v)-min(v):8.2f}pt" if len(v) > 1 else "—".rjust(9))(
            [t[(y, b)]["yield"] for b in ORDER
             if (y, b) in t and t[(y, b)]["scope"] != "僅AC"])
        for y in years))

    print("\n分桶殖利率(只有國泰/玉山的附表有拆;富邦 2023-24 的附註有兩列)")
    pac, poci = positions(classes=("AC",)), positions(classes=("OCI",))
    hit = False
    for (y, b), r in sorted(t.items()):
        if r["ac"] is None or r["oci"] is None:
            continue
        hit = True
        for lbl, amt, p in (("AC", r["ac"], pac), ("OCI", r["oci"], poci)):
            a, z = p.get((y - 1, b)), p.get((y, b))
            if a and z:
                print(f"   {y} {b} {lbl:>3}  {amt/E:7.1f}億 ÷ {(a+z)/2:6.0f}億"
                      f" = {amt/E/((a+z)/2)*100:5.2f}%")
    if not hit:
        print("   (還沒有分桶資料)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
