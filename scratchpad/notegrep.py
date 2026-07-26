# -*- coding: utf-8 -*-
"""原型:純文字層抓附註明細表。不呼叫任何模型。
驗收=兩道獨立檢查同時過:(a)列相加==印出合計 (b)印出合計==bs_anchor。"""
import re, sys, json, os
import pypdfium2 as pdf
import bs_anchor

CLSKEY = [("Trading", "透過損益按公允價值衡量"),
          ("OCI",     "透過其他綜合損益按公允價值衡量"),
          ("AC",      "按攤銷後成本衡量")]
TOTAL = re.compile(r"合\s*計|總\s*計")

def val(tok):
    t = tok.strip()
    if t in ("$", "＄"): return "SKIP"          # 錢字號單獨成 token,不是數值
    t = t.replace("$", "").replace("＄", "")
    if t in ("-", "－", "—", "–"): return 0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    if not re.fullmatch(r"\d+", t): return None
    return -int(t) if neg else int(t)

def parse_line(ln):
    """回 (名目, [數值...]) ;不是數字列回 None。要求至少一個含逗號的數字。"""
    toks = ln.split()
    vals, first_num = [], None
    for i, tk in enumerate(toks):
        v = val(tk)
        if v == "SKIP":
            if not vals and first_num is None: continue
            if vals: return None
            continue
        if v is None:
            if vals: return None          # 數字中間插字 → 不是乾淨的數字列
            continue
        if first_num is None: first_num = i
        vals.append(v)
    if not vals or first_num is None: return None
    if not any("," in t for t in toks[first_num:]): return None
    name = "".join(toks[:first_num]).replace("$", "").strip()
    return name, vals

def blocks(lines):
    """把連續數字列切成表格塊,以合計列收尾。回 [(起始行, [(名目,值)...], 合計)]"""
    out, cur, start, pend = [], [], None, []
    for i, ln in enumerate(lines):
        p = parse_line(ln)
        if p is None:
            s = ln.strip()
            if s and len(s) < 40: pend.append((i, s))
            if len(pend) > 6: pend = pend[-6:]
            continue
        name, vals = p
        if not name and pend: name = pend[-1][1]
        if start is None: start = i
        if TOTAL.search(name.replace(" ", "").replace("　", "")):
            out.append((start, cur[:], vals[0])); cur, start, pend = [], None, []
        else:
            cur.append((name, vals[0]))
        pend = []
    return out

def classify(lines, at):
    for j in range(at, max(-1, at - 16), -1):
        s = lines[j]
        if "金融負債" in s or "金融工具" in s and "資產" not in s: 
            if "金融負債" in s: return None
        for c, kw in CLSKEY:
            if kw in s:
                if "負債" in s: return None
                if c == "Trading" and "其他綜合損益" in s: return "OCI"
                return c
    return None

def all_blocks(path):
    """回 [(page, start, rows, printed)] —— 全文所有以合計收尾的表格塊。"""
    doc = pdf.PdfDocument(path)
    try:
        out = []
        for i in range(len(doc)):
            lines = (doc[i].get_textpage().get_text_range() or "").splitlines()
            if len(lines) < 3: continue
            for st, rows, tot in blocks(lines):
                if len(rows) >= 2:
                    out.append((i, st, rows, tot))
        return out
    finally:
        doc.close()


def read(path):
    """用 BS 錨定位明細表:找印出合計==錨的塊。驗收仍靠列相加==印出合計。"""
    anc, _ = bs_anchor.read(path)
    bl = all_blocks(path)
    res = {}
    for c, a in anc.items():
        cands = [b for b in bl if b[3] == a]
        res[c] = {"anchor": a, "n_cand": len(cands),
                  "hit": None if not cands else
                        {"page": cands[0][0], "rows": cands[0][2],
                         "printed": cands[0][3],
                         "sum": sum(v for _, v in cands[0][2])}}
    return res, anc, len(bl)


if __name__ == "__main__":
    import collections
    tally = collections.Counter()
    bad = []
    for p in sys.argv[1:]:
        try:
            res, anc, nb = read(p)
        except Exception as e:
            tally["error"] += 3; bad.append((p, "ERR", str(e)[:60])); continue
        for c in ("Trading", "OCI", "AC"):
            if c not in anc:
                tally["no_bs_anchor"] += 1; continue
            r = res[c]
            if r["hit"] is None:
                tally["no_table_match"] += 1; bad.append((os.path.basename(p), c, "no_match", r["anchor"]))
            elif r["hit"]["sum"] == r["hit"]["printed"]:
                tally["OK"] += 1
            else:
                tally["sum_mismatch"] += 1
                bad.append((os.path.basename(p), c, "sumfail", r["hit"]["sum"], r["hit"]["printed"]))
    print(json.dumps(dict(tally), ensure_ascii=False))
    for b in bad[:80]: print(b)
