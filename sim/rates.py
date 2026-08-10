# -*- coding: utf-8 -*-
"""利率序列與 β 估計 —— 軸② 的三種定義裡,後兩種要用這支。

    python3 -m sim.rates --fetch     重抓並更新 sim/rates.json
    python3 -m sim.rates             用快取印出序列、相關係數與 β

## 兩個來源(都是官方,不是財經網站)

    美國 10Y   FRED DGS10(日頻)          https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10
    台灣 10Y   中央銀行「十年期中央政府公債次級市場利率」(月頻)
               https://www.cbc.gov.tw/public/data/economic/statistics/key/interest.pdf
               央行這份的原始資料來自櫃買中心,是官方口徑

★ 一定要用 **10 年期**,不是政策利率:2022 年聯邦資金 +425bp、美國 10Y 只有 +240bp,
差 1.8 倍(計劃 §12.7)。

## ⚠️ 只能用年頻,n=4 —— 這是資料的硬限制,不是偷懶

計劃 §12.5 原本寫「Δ浮虧率(半年,9 個變動點)」。**做不到**:浮虧率要「公允 − 取得成本」,
而 `data.json` 的 `wide_cost` **只有年報有**;半年期別那些鍵是存在的,但值全是 `null`。
(踩過一次:只檢查「有沒有這個 dict」會誤判成滿的,要檢查值。)
所以只有 5 個年底觀測 → **4 個變動點**。

後果要誠實講:R² 看起來很高(0.81~0.99),但那幾乎是 2022 那一點撐起來的
(ΔUS +2.36pt,其餘三年都在 ±0.7 以內)。**β 是「2022 那次升息的實際反應」,
不是一個穩健的迴歸係數。** 前端顯示時要把 n=4 標出來。
"""
import csv
import io
import json
import os
import re
import ssl
import statistics as st
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "rates.json")
US_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2020-01-01"
TW_URL = "https://www.cbc.gov.tw/public/data/economic/statistics/key/interest.pdf"


def _open(url, timeout=60):
    """央行的憑證缺 Subject Key Identifier,Python 3.13+ 預設的嚴格模式會擋掉。

    只關 `VERIFY_X509_STRICT` 這一個旗標 —— **憑證鏈與主機名仍然照驗**,
    不是 verify=False。計劃 §12.7 記過這個坑,這裡是同一招。
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return urllib.request.urlopen(url, timeout=timeout, context=ctx)


def _fetch_us():
    """FRED 日頻 → 取每月最後一個有值日。"""
    raw = _open(US_URL).read().decode()
    out = {}
    for r in csv.DictReader(io.StringIO(raw)):
        v = r["DGS10"]
        if v in (".", ""):          # FRED 用 "." 表示當日無報價(假日)
            continue
        y, m, _ = r["observation_date"].split("-")
        out[f"{y}-{int(m):02d}"] = float(v)
    return out


def _fetch_tw():
    """央行那份 PDF 是一張大表,最後一欄就是十年期公債次級市場利率。

    民國年要轉西元。欄數寫死成 8 是刻意的 —— 欄數變了就抓不到,
    寧可抓不到也不要抓錯欄(隔壁是商業本票利率,數量級很像,錯了不會被發現)。
    """
    import pypdfium2

    blob = _open(TW_URL).read()
    doc = pypdfium2.PdfDocument(io.BytesIO(blob))
    txt = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    out = {}
    for m in re.finditer(r"(\d{2,3})年(\d{2})月((?:\s+-?[\d.]+){8})", txt):
        cols = m.group(3).split()
        out[f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}"] = float(cols[-1])
    if len(out) < 100:
        raise ValueError(f"央行 PDF 只解析到 {len(out)} 個月,格式可能變了")
    return out


def fetch(path=CACHE):
    data = {"us_10y": _fetch_us(), "tw_10y": _fetch_tw(),
            "src": {"us": US_URL, "tw": TW_URL}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    return data


def load(path=CACHE):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} 不在,先跑 python3 -m sim.rates --fetch")
    return json.load(open(path, encoding="utf-8"))


def year_end(years=(2021, 2022, 2023, 2024, 2025), path=CACHE):
    """回 {"US": {年: 殖利率}, "TW": {...}} —— 年底(12月)值。"""
    d = load(path)
    return {"US": {y: d["us_10y"][f"{y}-12"] for y in years},
            "TW": {y: d["tw_10y"][f"{y}-12"] for y in years}}


def _ols(x, y):
    mx, my = st.mean(x), st.mean(y)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    a0 = my - b * mx
    ss = sum((c - my) ** 2 for c in y)
    rs = sum((c - (a0 + b * a)) ** 2 for a, c in zip(x, y))
    return b, (1 - rs / ss if ss else float("nan"))


def betas(series, years=(2021, 2022, 2023, 2024, 2025), path=CACHE):
    """`series` = {(年, 銀行): 浮虧率%} → {(幣別, 銀行): {"beta":…, "r2":…, "n":…}}。

    β 的單位:**升息 100bp,浮虧率變動幾個百分點**(負 = 更虧)。
    """
    ye = year_end(years, path)
    out = {}
    banks = sorted({b for _, b in series})
    for cur in ("US", "TW"):
        dy = [ye[cur][years[i]] - ye[cur][years[i - 1]] for i in range(1, len(years))]
        for b in banks:
            s = [series.get((y, b)) for y in years]
            if any(v is None for v in s):
                continue
            dv = [s[i] - s[i - 1] for i in range(1, len(s))]
            beta, r2 = _ols(dy, dv)
            out[(cur, b)] = {"beta": beta, "r2": r2, "n": len(dv)}
    return out


def correlation(years=(2021, 2022, 2023, 2024, 2025), path=CACHE):
    """★ §12.7 的那道題:corr(ΔUS, ΔTW) 決定雙因子值不值得做。"""
    ye = year_end(years, path)
    dU = [ye["US"][years[i]] - ye["US"][years[i - 1]] for i in range(1, len(years))]
    dT = [ye["TW"][years[i]] - ye["TW"][years[i - 1]] for i in range(1, len(years))]
    return st.correlation(dU, dT), len(dU)


def main():
    import sys
    if "--fetch" in sys.argv:
        d = fetch()
        print(f"已更新 {CACHE}:美國 {len(d['us_10y'])} 個月、台灣 {len(d['tw_10y'])} 個月")
    ye = year_end()
    print("\n年底 10 年期公債殖利率(%)")
    print("      " + "".join(f"{y:>8}" for y in sorted(ye["US"])))
    for cur in ("US", "TW"):
        print(f"  {cur}  " + "".join(f"{ye[cur][y]:8.2f}" for y in sorted(ye[cur])))
    r, n = correlation()
    print(f"\n★ corr(ΔUS, ΔTW) = {r:.3f} (n={n})")
    print("  → 高度共線,**雙因子不要做**(兩個 β 會互相吸收,係數沒有意義)。")
    print("    單因子分開估、讓使用者切幣別,才是這份資料撐得住的做法。")


if __name__ == "__main__":
    main()
