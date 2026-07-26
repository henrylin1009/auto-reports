# -*- coding: utf-8 -*-
"""收集分桶表要涵蓋的名目詞彙:只看「錨值 grep 定位到的候選頁」上的列。"""
import sys, os, collections, json, re
import pypdfium2 as pdf, bs_anchor
sys.path.insert(0, os.path.dirname(__file__))
from notegrep2 import parse_line, SUB, TOT

freq, amt, where = collections.Counter(), collections.Counter(), collections.defaultdict(set)
for p in sys.argv[1:]:
    b = os.path.basename(p).replace(".pdf", "")
    anc, bspg = bs_anchor.read(p)
    if not anc: continue
    doc = pdf.PdfDocument(p)
    txt = [(doc[i].get_textpage().get_text_range() or "") for i in range(len(doc))]
    doc.close()
    pages = set()
    for v in anc.values():
        pages |= {i for i, t in enumerate(txt) if f"{v:,}" in t and i != bspg}
    for i in sorted(pages):
        for ln in txt[i].splitlines():
            r = parse_line(ln)
            if not r: continue
            name, vals = r
            name = re.sub(r"\s|　", "", name)
            if not name or SUB.fullmatch(name) or TOT.fullmatch(name): continue
            if len(name) > 24: continue
            freq[name] += 1; amt[name] += abs(vals[0]); where[name].add(b.split("_")[1])
print(f"相異名目 {len(freq)} 種,總出現 {sum(freq.values())} 次")
BK = {"5835":"國泰","5836":"富邦","5841":"中信","5843":"兆豐","5847":"玉山"}
for n, c in freq.most_common():
    bks = "".join(sorted(BK.get(x, x) for x in where[n]))
    print(f"{c:5d}  {n:<24s} {bks}")
