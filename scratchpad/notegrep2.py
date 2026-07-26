# -*- coding: utf-8 -*-
"""原型 v2:純文字層抓附註明細表(不呼叫模型)。
定位鍵 = BS 錨(bs_anchor,已驗 126/126);驗收 = 葉列相加 == 印出合計(精確)。
小計/合計是結構列不是資料列——把小計當資料列相加正是先前量到 20 格「多算」的成因。"""
import re, sys, json, os, collections
import pypdfium2 as pdf
import bs_anchor

SUB = re.compile(r"小\s*計|小\s*　*計")
TOT = re.compile(r"合\s*　*計|總\s*計")
# 期別表頭 = 新表開始。用來沖掉「上一張表沒有印合計」殘留的列
# (殘留會讓下一張表多算,實測中信 AC 多吃 259,241、OCI 多吃 404,258)。
_D = re.compile(r"\d{2,3}[.年]\d{1,2}")
CONT = re.compile(r"承\s*前\s*頁|接\s*次\s*頁|續")

def is_date_hdr(ln):
    tk = ln.split()
    return len(tk) >= 2 and all(_D.match(t) for t in tk)

def val(tok):
    t = tok.strip()
    if t in ("$", "＄"): return "SKIP"
    t = t.replace("$", "").replace("＄", "")
    if t in ("-", "－", "—", "–"): return 0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    # 不能用 str.isdigit():上標/下標數字(₄ ²)會通過但 int() 會炸
    if not re.fullmatch(r"[0-9]+", t): return None
    return -int(t) if neg else int(t)

def parse_line(ln):
    toks = ln.split()
    vals, first = [], None
    for i, tk in enumerate(toks):
        v = val(tk)
        if v == "SKIP": continue          # $ 會夾在各欄之間(國泰),不可當終止
        if v is None:
            if vals: return None
            continue
        if first is None: first = i
        vals.append(v)
    if not vals or first is None: return None
    if not any("," in t for t in toks[first:]): return None
    return "".join(toks[:first]).replace("$", "").replace("　", ""), vals

def scan(path):
    """整份文件連續掃(表會跨頁),回 [(page, leaves, printed_total)]。"""
    doc = pdf.PdfDocument(path)
    try:
        out, leaves, pg, cont = [], [], None, False
        for i in range(len(doc)):
            for ln in (doc[i].get_textpage().get_text_range() or "").splitlines():
                p = parse_line(ln)
                if p is None:
                    if CONT.search(ln): cont = True
                    elif is_date_hdr(ln):
                        if not cont: leaves, pg = [], None   # 沖殘留
                        cont = False
                    continue
                name, vals = p
                if SUB.fullmatch(name):            # 小計:結構列,不進和
                    continue
                if TOT.fullmatch(name) or name == "":   # 合計(國泰的合計列無標籤)
                    if leaves: out.append((pg, leaves, vals[0]))
                    leaves, pg = [], None
                    continue
                if pg is None: pg = i
                leaves.append((name, vals[0]))
        return out
    finally:
        doc.close()

def read(path):
    anc, _ = bs_anchor.read(path)
    bl = scan(path)
    res = {}
    for c, a in anc.items():
        cands = [b for b in bl if b[2] == a]
        res[c] = {"anchor": a, "n": len(cands),
                  "hit": None if not cands else
                  {"page": cands[0][0], "rows": cands[0][1],
                   "printed": a, "sum": sum(v for _, v in cands[0][1])}}
    return res, anc

if __name__ == "__main__":
    t, bad = collections.Counter(), []
    for p in sys.argv[1:]:
        b = os.path.basename(p).replace(".pdf", "")
        try: res, anc = read(p)
        except Exception as e: t["error"] += 3; bad.append((b, "ERR", str(e)[:70])); continue
        for c in ("Trading", "OCI", "AC"):
            if c not in anc: t["no_bs_anchor"] += 1; continue
            h = res[c]["hit"]
            if h is None: t["no_match"] += 1; bad.append((b, c, "no_match", anc[c]))
            elif h["sum"] == h["printed"]: t["OK"] += 1
            else:
                t["sum_mismatch"] += 1
                bad.append((b, c, "sumfail", h["sum"] - h["printed"], h["printed"]))
    print(json.dumps(dict(t), ensure_ascii=False))
    for x in bad[:100]: print(x)
