# -*- coding: utf-8 -*-
"""取數層 —— 四根軸要的原始量,全部在這裡換算單位。

**所有單位換算集中在這一支**(計劃 §12.6 陷阱4)。出了這支的數字一律是「億元」,
下游不准再乘除 `yields.E`。

## 兩個檔、兩種單位

    data.json     債券部位  億元    wide(公允/帳面) + wide_cost(取得成本)
    capital.json  資本/損益 仟元    走 yields.interest(),免費得到跨份對帳

## 為什麼要挑 data.json 的版本

working tree 的 `data.json` 有單邊分桶(某券種公允有值、成本 0,或反過來),
分券種相減就會生出假浮虧 —— 富邦 2022H2 會算成 −11.41%(真值 −2.15%)。
**但這件事只在「軸②揭露端真正用到的那 25×5 格」上才重要**,所以閘門就照那個範圍驗,
不做全表普查(全表有很多格是年報根本沒印成本口徑,擋了也沒意義)。

實測 2026-08-06:HEAD 版 0 處、working tree 7 處 → 目前會落到 HEAD。
等 build.py 修好單邊分桶,working tree 自己就會通過,這支不用改。
"""
import json
import subprocess

import yields

E = yields.E                     # 1e5  仟元 → 億元
#: 有久期的券種。**排除 股票 與 貨幣市場** —— 貨幣市場是存單票券,浮虧實測 0.00%
#: (拿 OCI 桶的公允/成本對照過),混進來只會稀釋分母。
K = ("GB", "公司債", "金融債", "資產基礎", "其他")
CLASSES = ("AC", "OCI", "Trading")
YEARS = (2021, 2022, 2023, 2024, 2025)


def BANKS():
    """2026-08-12:`yields.ORDER` 那份寫死 5 家清單已經退場,改呼叫
    `yields.order()` 現算(哪些銀行真的有殖利率資料)。**故意是函式,不是
    模組層常數**——常數會在 `import sim.state` 當下就讀檔,任何理由
    (capital.json 格式還沒接上、data.json 缺資料)都會讓整個模組連 import
    都失敗;維持函式讓失敗只發生在真的要用銀行清單的當下,跟這支模組其餘
    I/O(`json.load(open(...))` 到處都是)一樣是呼叫時才發生。"""
    return yields.order()

_cache = {}


def onesided(D, years=YEARS):
    """回 OCI 券種裡「公允有值但成本 0(或反過來)」的格。這是假浮虧的來源。

    ⚠️ **一邊整個口徑不存在的格不算單邊**(2026-08-10 修)。`rate()` 開頭的
    `if not p: return None` 已經讓那種格留白、不會造出假數字,所以它不是這支
    閘門要擋的東西。把它算進來的後果實測過:`build.py` 砍掉舊管線保底之後,
    「該口徑在文件裡不存在」的格誠實地變成 null,這裡卻從 7 處暴增到 30 處 ——
    **資料越誠實、閘門越常誤報**,模擬器會被永遠釘在 HEAD 版(也就是那份還
    混著舊管線數字的),而那正好是相反的效果。

    真正會生出假浮虧的是**同一格兩邊都有、但個別券種對不齊**:分券種相減時
    一邊是 0、一邊有值,差額整個變成假浮虧(富邦 2022H2 曾算成 −11.41%,
    真值 −2.15%)。那種才留在清單裡。
    """
    bad = []
    for y in years:
        for b in BANKS():
            w = D["wide"].get(f"{y}H2|{b}") or {}
            c = D["wide_cost"].get(f"{y}H2|{b}") or {}
            if not (any(w.get(f"OCI_{k}") is not None for k in K)
                    and any(c.get(f"OCI_{k}") is not None for k in K)):
                continue
            for k in K:
                if ((w.get(f"OCI_{k}") or 0) == 0) != ((c.get(f"OCI_{k}") or 0) == 0):
                    bad.append((y, b, k))
    return bad


def wide(path="data.json"):
    """回 (data, 來源標記)。**一律用工作區**,對不齊的格逐格留白(見 `misaligned()`)。

    ⚠️ **2026-08-10 拿掉了「整份退回 HEAD」。** 原本只要有一處單邊分桶就整份
    改讀 `git show HEAD:data.json`。那在 `build.py` 還會回退舊管線數字的年代
    說得通(HEAD 是當時唯一乾淨的一版);砍掉保底之後方向反過來了 ——
    HEAD 那份混著沒驗過的舊管線數字,工作區才是全部過閘門的那份,
    為了一個銀行年度的錯位把整份換成比較沒驗過的版本,划不來也不誠實。

    改成外科手術:錯位只影響**那一格的分券種軸**,就只讓那一格留白
    (`ac_hidden()` 對玉山 2021 缺 fair_value 就是這樣處理的,同一個做法),
    其餘照用。留白的格會經由 `axes.flags()` 在前端標出理由。
    """
    if "wide" in _cache:
        return _cache["wide"]
    D = json.load(open(path, encoding="utf-8"))
    _cache["wide"] = (D, "工作區")
    return _cache["wide"]


def misaligned():
    """回 `{(年, 銀行)}` —— 分券種對不齊、不能拿來算浮虧的格。

    實例(2026-08-10 唯一一處):富邦 2021H2 OCI,附註 p41 印「其他 1,078,988」,
    明細表 p150 把同一筆印成「可轉讓定期存單 1,076,605」。**兩邊分桶都是對的**
    (`BUCKET_RULES`:印著「其他」的才進其他桶;可轉讓定存單自成一桶進貨幣市場),
    錯位是文件自己兩張表的顆粒度不同造成的,修不掉。
    後果量過:那一格浮虧率會算成 2.01%,對齊後是 0.85% —— 差 1.16 個百分點,
    而這根軸的典型值就在 −2% ~ −8% 之間,不留白就是發布一個錯的比較。
    """
    if "misaligned" not in _cache:
        D, _ = wide()
        _cache["misaligned"] = frozenset((y, b) for y, b, _ in onesided(D))
    return _cache["misaligned"]


def _row(D, y, b, kind="wide"):
    return D[kind].get(f"{y}H2|{b}") or {}


def bonds(y, b, classes=CLASSES, kind="wide"):
    """券種加總(億)。`classes` 給 ("OCI",) 就是揭露口徑。"""
    D, _ = wide()
    r = _row(D, y, b, kind)
    return sum(r.get(f"{c}_{k}", 0) or 0 for c in classes for k in K)


def gov(y, b, classes=CLASSES):
    D, _ = wide()
    r = _row(D, y, b)
    return sum(r.get(f"{c}_GB", 0) or 0 for c in classes)


def has_basis(y, b, kind):
    """這一格的 OCI 在 `kind`(wide / wide_cost)裡**真的有揭露**嗎。

    `bonds()` 是 `or 0` 加總,分不出「部位是 0」與「這個口徑不存在」——
    兩者都回 0。分不出來的後果是 `100*(p-q)/p` 在 q 這邊整個口徑不存在時
    算出 **100% 浮虧**(實測玉山 2021/2022 就是這樣冒出兩個 100.00),
    所以要看的是「有沒有非 null 的桶」,不是「加起來是不是 0」。
    """
    D, _ = wide()
    r = _row(D, y, b, kind)
    return any(r.get(f"OCI_{k}") is not None for k in K)


def oci_unrealized(y, b):
    """OCI 已入權益的浮虧:(公允, 成本),億元。兩邊都排除股票與貨幣市場。

    兩種情況回 `None`,都是「算出來會是假的」:
      · 任一邊整個口徑沒揭露 —— 相減等於拿部位總額當浮虧
      · 分券種對不齊 —— 見 `misaligned()`
    """
    if (y, b) in misaligned():
        return None
    if not (has_basis(y, b, "wide") and has_basis(y, b, "wide_cost")):
        return None
    return bonds(y, b, ("OCI",), "wide"), bonds(y, b, ("OCI",), "wide_cost")


def ac_hidden(y, b):
    """AC 沒入權益的隱藏浮虧 → (浮虧億, 對應的債券部位億, scope) 或 None。

    金額出自 capital.json 的 `fair_value`(附註「按攤銷後成本衡量之債務工具投資」
    的公允價值揭露)。**分母不用文件印的 book**:四家「全帳」的 book 含貨幣市場
    (國泰有 66% 是存單),拿去跟只有債券的 OCI 浮虧率並列就是兩把尺。
    改成把浮虧全歸給債券部位,代價是假設「貨幣市場浮虧≈0」——
    這個假設用 OCI 桶的貨幣市場實測過:五家幾乎全期 0.00%,最大 −0.39%。

    兆豐的 scope 是「扣貨幣市場」,它的 book 本來就只有債券(實測 894 = AC 券種加總),
    不需要這個假設 —— 但它跟另外四家不同源,標記帶出去給前端顯示。
    """
    rec = yields.interest(kind="fair_value", field="fair").get((y, b))
    if not rec:
        return None
    loss = (rec["fair"] - rec["book"]) / E
    return loss, bonds(y, b, ("AC",)), rec.get("scope")


def capital(y, b):
    """資本適足(仟元原樣)。缺就回 None —— 兆豐 2025 不在檔案裡(計劃 §12.6 陷阱8)。"""
    return yields.interest(kind="capital", field="cet1").get((y, b))


def yield_pct(y, b):
    """證券殖利率(層1 票息,%)。分母鎖平均(AC+OCI),已知的坑,不開放切換。"""
    rec = yields.table().get((y, b))
    return (rec["yield"], rec.get("scope")) if rec else None


def yield_record(y, b):
    """`yields.table()` 的完整那筆(含 pos = 平均(AC+OCI)部位,億)。報酬四層要用。"""
    return yields.table().get((y, b))


def pnl(y, b):
    """capital.json 的 pnl 那筆(仟元原樣):net_income/oci_realized/ac_derecog/oci_debt_ovi。"""
    return yields.interest(kind="pnl", field="net_income").get((y, b))


_p3 = {}


def pillar3():
    """第三支柱揭露(§7.0b)。含 `exposure`(暴險總額)—— capital.json 沒有這個量,
    這是軸③「真槓桿」與「RWA密度」唯一的來源。跟 capital.json 對過帳:
    四家重疊的 CET1/RWA 差 0.000%,而且它多了兆豐 2025(capital.json 缺這格)。
    """
    if "d" not in _p3:
        _p3["d"] = json.load(open("pillar3.json", encoding="utf-8"))
    return _p3["d"]


def pillar3_rec(y, b, basis="個體"):
    """`y` 是西元年,轉成 pillar3 的民國年底期別(如 2025→"114H2")。
    **一律只取「個體」** —— 跟 capital.json 同一條規則(計劃 §12.6 陷阱2)。
    """
    period = f"{y - 1911}H2"
    return pillar3().get(b, {}).get(period, {}).get(basis)
