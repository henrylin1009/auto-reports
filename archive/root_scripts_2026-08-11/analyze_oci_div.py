# -*- coding: utf-8 -*-
"""OCI 佔比 × 現金股利變異 —— 產生 docs/oci_股利分析.md 的那張表。

兩個輸入,兩種驗收:

    OCI 佔比   data.json(已過 v3 管線驗收)
    現金股利   capital.json + review/capital_queue.jsonl,再過本檔三道檢查

## 三道檢查(不需要外部真值)

  ① 列內  該列各欄加總 == 表自己印的「權益總額」欄
  ② 期別  doc `20YY04` 是 FY YY 的年報,表上只會有 YY 與 YY-1 兩欄
  ③ 跨份  中間年度會出現在兩份年報裡(202304 有 2022+2023、202404 有 2023+2024),
          兩支 PDF、兩次獨立模型呼叫,對得上才收

②③ 合起來抓到 **202504 的中信與富邦被整份往前偏移一年**。gemini 重跑兩次結果完全
相同(系統性誤讀,不是抖動),換 claude reader 才修好。**預設 reader 應該用 claude**
—— 實測 claude 6/6 整表過驗收,gemini 40 個 doc-year 只過 1 個。

## 口徑:分母要排掉貨幣市場

機制是「存續期間 → 浮虧 → 其他權益」。貨幣市場工具沒有存續期間、不生浮虧,
放進分母只是稀釋。而且它**不是均勻稀釋** —— OCI 桶裡幾乎沒有貨幣市場
(0.1%~17.2%),全堆在 PL 與 AC,所以含與不含會把每家拉開不同的幅度:

    兆豐 36.3% → 77.8%     中信 16.0% → 28.5%
    玉山 30.9% → 55.9%     富邦 12.0% → 18.3%
    國泰 27.1% → 46.2%

排序不變,所以 Spearman 不動(+0.80);Pearson 由 +0.73 掉到 +0.63(間距被拉開)。

## 「無此列」有兩種意思

整表過了驗收的紀錄裡沒有現金股利列 = **那年真的沒配現金**(玉山 2023,兩份年報
獨立驗證,只發股票股利並辦現金增資);沒過驗收的則可能只是抄漏,丟掉不猜。
當成缺值會剛好刪掉最極端的那一格。
"""
import json
import re
import statistics as st
from collections import defaultdict

BANKS = {"5841": "中信", "5843": "兆豐", "5835": "國泰", "5836": "富邦", "5847": "玉山"}

#: 有存續期間的債券。排除「股票」(權益工具,不走這條機制)與「貨幣市場」(見 docstring)。
DUR_KINDS = ("GB", "公司債", "金融債", "資產基礎", "其他")
CLASSES = ("Trading", "OCI", "AC")          # Trading 就是 PL;三者佔比加總 = 1

#: 用**構詞**認,不是列舉版型。實測 5 家印成三種:「現金股利」「普通股現金股利」
#: 「股東紅利－現金」。共同點是「現金」+(股利|紅利);「股票股利」「股東紅利－股票」
#: 一定要排掉 —— 股票股利不出錢,混進來會把配息高估。
DIV_PAT = re.compile(r"現金.*(股利|紅利)|(股利|紅利).*現金")
DIV_ANTI = re.compile(r"股票")
#: 淨利列。「綜合損益總額」是 淨利+其他綜合損益 的**小計**,抓進來會重複計。
NET_PAT = re.compile(r"淨利|淨損益")
NET_ANTI = re.compile(r"綜合")

E = 1e5     # 仟元 → 億元


def _flat(s):
    return re.sub(r"\s+", "", str(s))


def _year(p):
    """'110' / '2021' / '113年度' → 西元年。"""
    m = re.search(r"\d+", str(p))
    if not m:
        return None
    n = int(m.group())
    return n + 1911 if n < 1911 else n


# ---------- OCI 佔比 ----------

def oci_shares(path="data.json", kinds=DUR_KINDS):
    """回 {銀行: (OCI佔比均值, 期數)}。逐期算佔比再平均,不是先加總再算 ——
    後者會被部位大的期別主導。"""
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for b in d["banks"]:
        v = []
        for p in d["periods"]:
            c = d["wide"].get(f"{p}|{b}")
            if not c:
                continue
            t = {cl: sum(c.get(f"{cl}_{k}") or 0 for k in kinds) for cl in CLASSES}
            s = sum(t.values())
            if s > 0:
                v.append(t["OCI"] / s * 100)
        if v:
            out[b] = (st.mean(v), len(v))
    return out


# ---------- 現金股利 ----------

def _pick(moves, pat, anti):
    """回 (金額仟元, 失敗原因)。命中列可能不只一筆(普通股/特別股),加總。"""
    hit = [m for m in moves
           if pat.search(_flat(m["name"])) and not anti.search(_flat(m["name"]))]
    if not hit:
        return None, "無此列"
    tot, notes = 0, []
    for m in hit:
        if any(v is None for v in m["cols"].values()):
            return None, f"「{m['name']}」有 null"
        s = sum(m["cols"].values())
        if m.get("total") is not None and abs(s - m["total"]) > 1:      # ① 列內
            notes.append(f"「{m['name']}」{s:,} != 印出總額 {m['total']:,}")
        tot += s
    return (None, "; ".join(notes)) if notes else (tot, None)


def _records():
    """(doc, rec, 是否整表過驗收)。

    ⚠️ 佇列是 append-only,重跑不會清掉舊的失敗紀錄。某份 doc 一旦整表過了驗收,
    它先前的佇列殘骸就是**已被取代的舊讀數**,再撿進來只會製造假的跨份衝突。
    """
    store = json.load(open("capital.json", encoding="utf-8")).get("equity", {})
    out = [(doc, r, True) for doc, rs in store.items() for r in rs]
    for line in open("review/capital_queue.jsonl", encoding="utf-8"):
        d = json.loads(line)
        # rec 是 None 的是 PARSE_FAIL(輸出不是 JSON),整份沒東西可撿。
        if d.get("kind") == "equity" and d.get("rec") and d["doc"] not in store:
            out.append((d["doc"], d["rec"], False))
    return out


def dividends():
    """回 (series, rejected)。series = {銀行: {年: {div, net}}},單位億元。"""
    obs, bad = defaultdict(list), []
    for doc, r, passed in _records():
        bank, yr, fy = BANKS.get(doc.split("_")[1]), _year(r.get("period")), int(doc[:4])
        if not bank or not yr:
            continue
        if yr not in (fy, fy - 1):                                      # ② 期別
            bad.append((bank, yr, doc, f"期別 {yr} 不屬於 FY{fy} 年報的兩欄(整份偏移)"))
            continue
        div, why = _pick(r.get("moves") or [], DIV_PAT, DIV_ANTI)
        net, _ = _pick(r.get("moves") or [], NET_PAT, NET_ANTI)
        if div is None and why == "無此列" and passed:
            div = 0                                                     # 見 docstring
        elif div is None:
            bad.append((bank, yr, doc, f"現金股利:{why}"))
            continue
        obs[(bank, yr)].append({"doc": doc, "div": -div / E,
                                "net": None if net is None else net / E})

    series = defaultdict(dict)
    for (b, y), lst in sorted(obs.items()):                             # ③ 跨份
        vs = {round(o["div"], 1) for o in lst}
        if len(vs) > 1:
            bad.append((b, y, "—", "兩份年報讀出來不一致:"
                        + " / ".join(f"{v:.1f}億" for v in sorted(vs))))
            continue
        series[b][y] = lst[0]
    return series, bad


# ---------- 統計 ----------

def pearson(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** .5
    return num / den


def spearman(xs, ys):
    rank = lambda v: [sorted(v).index(x) + 1 for x in v]                # noqa: E731
    return pearson(rank(xs), rank(ys))


def table():
    oci, (ser, bad) = oci_shares(), dividends()
    rows = []
    for b, ys in ser.items():
        v = [c["div"] for c in ys.values()]
        if len(v) < 2 or b not in oci:
            continue
        # 配息率要**錯開一年**:Y 年表上的現金股利,分的是 Y-1 年的盈餘。
        payout = [ys[y]["div"] / ys[y - 1]["net"] * 100
                  for y in ys if y - 1 in ys and ys[y - 1]["net"]]
        rows.append({"bank": b, "oci": oci[b][0], "n": len(v),
                     "cv": st.stdev(v) / st.mean(v) * 100,
                     "psd": st.stdev(payout) if len(payout) >= 2 else None,
                     "years": dict(sorted((y, c["div"]) for y, c in ys.items()))})
    rows.sort(key=lambda r: -r["oci"])
    return rows, bad


def main():
    rows, bad = table()
    print("| 銀行 | OCI佔比 | n | 股利CV | 配息率SD |")
    print("|---|---:|---:|---:|---:|")
    for r in rows:
        psd = f"{r['psd']:.0f}pt" if r["psd"] is not None else "—"
        print(f"| {r['bank']} | {r['oci']:.1f}% | {r['n']} | {r['cv']:.1f}% | {psd} |")

    xs = [r["oci"] for r in rows]
    for lab, key in (("股利CV", "cv"), ("配息率SD", "psd")):
        sub = [r for r in rows if r[key] is not None]
        if len(sub) < 3:
            continue
        x, y = [r["oci"] for r in sub], [r[key] for r in sub]
        print(f"\nOCI佔比 vs {lab}:  n={len(sub)}  "
              f"Pearson {pearson(x, y):+.2f}   Spearman {spearman(x, y):+.2f}")
        # 留一法 —— n 這麼小,不做這個就不知道結論是不是單點撐起來的
        for r in sub:
            o = [q for q in sub if q["bank"] != r["bank"]]
            xo, yo = [q["oci"] for q in o], [q[key] for q in o]
            print(f"    拿掉 {r['bank']:<3} → Pearson {pearson(xo, yo):+.2f}"
                  f"   Spearman {spearman(xo, yo):+.2f}")

    print("\n=== 現金股利序列(億元)===")
    for r in rows:
        print(f"  {r['bank']:<4} " + "  ".join(f"{y}:{v:,.0f}" for y, v in r["years"].items()))
    if bad:
        print("\n=== 沒進表的(三道檢查擋下)===")
        for b, y, doc, why in bad:
            print(f"  {b} {y} ({doc}): {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
