# -*- coding: utf-8 -*-
"""關鍵問題:不同 k 過的是不是「不同的格」?
若聯集 ≈ 單一 k 最佳值 → agent 調參沒用;若遠大於 → 固定 k 才是問題。"""
import sys, os, glob, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.getcwd())
import pypdfium2 as pdf, bs_anchor
from notegrep2 import parse_line, SUB, TOT, CONT, is_date_hdr
from notegrep2b import chars, lines_k

KS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2)

def blocks_from(lines):
    blocks, leaves, cont = [], [], False
    for ln in lines:
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
    return blocks

def judge(blocks, anc, tag, passed):
    for c, a in anc.items():
        cand = [b for b in blocks if b[1] == a]
        if cand and sum(v for _, v in cand[0][0]) == a:
            passed.setdefault(tag, set()).add((os.path.basename(tag_p), c))

if __name__ == "__main__":
    files = sorted(f for f in glob.glob('pdf_cache/*.pdf') if os.path.basename(f) >= '202302')
    passed = collections.defaultdict(set); allcells = set()
    for p in files:
        tag_p = p
        try: anc, bspg = bs_anchor.read(p)
        except Exception: continue
        if not anc: continue
        b = os.path.basename(p)
        for c in anc: allcells.add((b, c))
        doc = pdf.PdfDocument(p)
        pages = [chars(doc[i]) for i in range(len(doc))]
        # 基準:pypdfium2 內建行組裝
        base = []
        for i in range(len(doc)):
            base += (doc[i].get_textpage().get_text_range() or '').split('\n')
        doc.close()
        for tag, lines in [('base', base)] + [
            (f'k={k}', [ln for cs in pages if cs for ln in lines_k(cs, k)]) for k in KS]:
            bl = blocks_from(lines)
            for c, a in anc.items():
                cand = [x for x in bl if x[1] == a]
                if cand and sum(v for _, v in cand[0][0]) == a:
                    passed[tag].add((b, c))
    print(f'總格數 {len(allcells)}')
    for tag in ['base'] + [f'k={k}' for k in KS]:
        print(f'  {tag:<8} 過 {len(passed[tag])}')
    uk = set().union(*[passed[f'k={k}'] for k in KS])
    print(f'\n座標版 任一 k 的聯集      : {len(uk)}')
    print(f'基準                      : {len(passed["base"])}')
    print(f'基準 ∪ 座標任一k          : {len(passed["base"] | uk)}')
    print(f'座標救到基準救不到的       : {len(uk - passed["base"])}')
    print(f'基準過但座標全 k 都不過    : {len(passed["base"] - uk)}')
