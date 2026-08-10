"""從 pillar3_cache/*.pdf 抽【附表三】資本適足比率 → pillar3.json。

制式表,五家同格式,列序固定,所以用「數字列依序對應欄位」而不是逐家寫規則。
可信度由六道對帳保證(都印在同一張表上,不需外部真值):
  CET1/RWA==印出的比率 · 自有資本==CET1+其他T1+T2 · 自有資本/RWA==BIS
  RWA==信用+作業+市場 · 第一類/RWA==第一類比率 · 槓桿==第一類淨額/暴險
任何一格沒過就標 fail,不寫進乾淨區。
"""
import json, re, hashlib
from pathlib import Path
import pdfplumber

CACHE = Path("pillar3_cache")
FIELDS = ["cet1", "other_t1", "t2", "own_funds", "rwa_credit", "rwa_op", "rwa_mkt",
          "rwa", "cet1_pct", "t1_pct", "bis_pct", "lev_t1", "exposure", "lev_pct"]
NUM = re.compile(r"-?[\d,]+\.?\d*%?")


def numline(line):
    """回這一行的數值 token(至少 2 個才算數字列)。

    ⚠️ 日期表頭「114年12月31日 113年12月31日…」會被讀成 12 個數字,必須先排除,
    否則欄寬判定會被它帶走(實測整批只剩 1 列)。
    """
    if re.search(r"[年月日]", line):
        return []
    # ⚠️ 不可用「長度 >= 2」過濾:兆豐的其他第一類資本、中信早期的第二類資本都是 0,
    #    「0」被濾掉整列就消失,後面每一列往上位移一格,六道對帳會全紅(實測 26 格)。
    # ⚠️ 中信 111H2 的第二類資本用「-」表示零(不是 0),不補也會整列位移。
    line = re.sub(r"(?<=\s)[-–—－](?=\s)", " 0 ", f" {line} ")
    toks = [t for t in NUM.findall(line) if re.search(r"\d", t)]
    out = []
    for t in toks:
        pct = t.endswith("%")
        v = t.rstrip("%").replace(",", "")
        try:
            out.append(float(v) if (pct or "." in v) else int(v))
        except ValueError:
            return []
    return out if len(out) >= 2 else []


def find_table(pdf):
    """回 (頁碼, 該頁文字)。附表三 = 含『加權風險性資產合計數』那頁。"""
    for i, pg in enumerate(pdf.pages):
        t = pg.extract_text() or ""
        if "加權風險性資產合計數" in t.replace(" ", ""):
            return i + 1, t
    return None, None


def parse(text):
    rows = [r for r in (numline(l) for l in text.split("\n")) if r]
    if not rows:
        return 0, []
    from collections import Counter
    width = Counter(len(r) for r in rows).most_common(1)[0][0]   # 取眾數,不是最大值
    return width, [r for r in rows if len(r) == width]


def gates(d, tol=0.011):
    """六道對帳。回 list of 失敗說明。"""
    f = []
    if not (d.get("rwa") and d.get("cet1")):
        return ["缺 cet1/rwa"]
    if abs(d["cet1"] / d["rwa"] * 100 - d["cet1_pct"]) > tol:
        f.append(f"CET1/RWA {d['cet1']/d['rwa']*100:.4f} != {d['cet1_pct']}")
    # 容差 5 千元:中信 110H1 合併的印刷值就差 1(文件自己的四捨五入),不是抄錯
    if d.get("own_funds") and abs(d["cet1"] + d.get("other_t1", 0) + d.get("t2", 0) - d["own_funds"]) > 5:
        f.append("自有資本加總不符")
    if d.get("own_funds") and abs(d["own_funds"] / d["rwa"] * 100 - d["bis_pct"]) > tol:
        f.append("BIS 不符")
    if d.get("rwa_credit") and d["rwa_credit"] + d["rwa_op"] + d["rwa_mkt"] != d["rwa"]:
        f.append("RWA 三項加總不符")
    if abs((d["cet1"] + d.get("other_t1", 0)) / d["rwa"] * 100 - d["t1_pct"]) > tol:
        f.append("第一類比率不符")
    if d.get("exposure") and d.get("lev_pct") and \
            abs(d["lev_t1"] / d["exposure"] * 100 - d["lev_pct"]) > tol:
        f.append("槓桿比率不符")
    return f


out, bad = {}, []
for p in sorted(CACHE.glob("*.pdf")):
    per, bank = p.stem.split("_")
    with pdfplumber.open(p) as pdf:
        pgno, text = find_table(pdf)
        if text is None:
            bad.append((per, bank, "找不到附表三")); continue
        # 兆豐把槓桿比率拆成另一個檔,補讀同期 04.pdf 不做;此處容許 11 列
        width, rows = parse(text)
    n = min(len(rows), len(FIELDS))
    if n < 11:
        bad.append((per, bank, f"數字列只有 {len(rows)} 列")); continue
    # 欄序:本行當期 | 本行前期 | 合併當期 | 合併前期
    rec = {}
    for basis, col in [("個體", 0), ("合併", 2)]:
        if col >= width:
            continue
        d = {f: rows[i][col] for i, f in enumerate(FIELDS[:n])}
        d["_fails"] = gates(d)
        rec[basis] = d
    rec["_src"] = {"file": p.name, "page": pgno, "sha1": hashlib.sha1(p.read_bytes()).hexdigest()[:8],
                   "cols": width, "rows": len(rows)}
    out.setdefault(bank, {})[per] = rec

Path("pillar3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

ok = sum(1 for b in out.values() for r in b.values()
         for k, v in r.items() if k != "_src" and not v["_fails"])
tot = sum(1 for b in out.values() for r in b.values() for k in r if k != "_src")
print(f"寫出 pillar3.json — {sum(len(v) for v in out.values())} 期 × 家,{tot} 個口徑格,{ok} 格全過對帳")
for bank, per in out.items():
    for k, r in sorted(per.items()):
        for basis in ("個體", "合併"):
            if basis in r and r[basis]["_fails"]:
                print(f"  ✗ {k} {bank} {basis}: {r[basis]['_fails']}")
for b in bad:
    print("  ✗", b)
