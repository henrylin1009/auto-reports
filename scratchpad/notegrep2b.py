# -*- coding: utf-8 -*-
"""座標重建版:y 容差 = k × 該頁中位字高(自適應),用恆等式當裁判掃 k。"""
import sys, os, glob, collections, statistics, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pypdfium2 as pdf, bs_anchor
from notegrep2 import parse_line, SUB, TOT, CONT, is_date_hdr

def chars(page):
    tp = page.get_textpage(); out = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if not ch.strip(): continue
        l, b, r, t = tp.get_charbox(i); out.append((l, b, r, t, ch))
    return out

def lines_k(cs, k):
    hs = [t - b for _, b, _, t, _ in cs]
    h = statistics.median(hs) if hs else 8.0
    if h <= 0: h = 8.0
    tol = k * h
    buf = collections.defaultdict(list)
    for l, b, r, t, ch in cs: buf[round((b + t) / 2, 2)].append((l, r, ch))
    out = []
    for y in sorted(buf, reverse=True):
        if out and abs(out[-1][0] - y) <= tol: out[-1][1].extend(buf[y])
        else: out.append([y, list(buf[y])])
    res = []
    for y, cl in out:
        # 用前一字的【右緣】算真實空白,不是左緣——用左緣的話 delta 等於字寬,
        # 中文 ~8pt、數字 ~4pt,任何固定門檻都只是卡在兩者之間的魔術數字。
        cl.sort(); s = ''; pr = None
        for l, r, c in cl:
            if pr is not None and l - pr > 0.3 * h: s += '  '
            s += c; pr = r
        res.append(s)
    return res

def cells(k, files):
    ok = fail = nomatch = 0
    for p in files:
        try: anc, bspg = bs_anchor.read(p)
        except Exception: continue
        if not anc: continue
        doc = pdf.PdfDocument(p)
        blocks, leaves, cont = [], [], False
        for i in range(len(doc)):
            cs = chars(doc[i])
            if not cs: continue
            for ln in lines_k(cs, k):
                r = parse_line(ln)
                if r is None:
                    if CONT.search(ln): cont = True
                    elif is_date_hdr(ln):
                        if not cont: leaves = []
                        cont = False
                    continue
                nm, vs = r; nm = re.sub(r"\s|　", "", nm)
                if SUB.fullmatch(nm): continue
                if TOT.fullmatch(nm) or nm == "":
                    if leaves: blocks.append((leaves, vs[0]))
                    leaves = []; continue
                leaves.append((nm, vs[0]))
        doc.close()
        for c, a in anc.items():
            cand = [b for b in blocks if b[1] == a]
            if not cand: nomatch += 1
            elif sum(v for _, v in cand[0][0]) == a: ok += 1
            else: fail += 1
    return ok, fail, nomatch

if __name__ == "__main__":
    files = sorted(f for f in glob.glob('pdf_cache/*.pdf') if os.path.basename(f) >= '202302')
    print(f'{len(files)} 份,共 123 格。k → (恆等式過, 加不起來, 找不到)')
    for k in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2):
        print(f'  k={k:<4} {cells(k, files)}', flush=True)
