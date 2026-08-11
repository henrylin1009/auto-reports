# -*- coding: utf-8 -*-
"""對不上的格子,到底差在哪 —— 是切表壞了,還是對帳判準太嚴?"""
import sys, collections
import pdfplumber, locate, table

def diag(key):
    doc, cls = key.split('|')
    loc = locate.locate(f'pdf_cache/{doc}.pdf')
    anchor = loc.anchors[cls]
    best = None
    for i in loc.pages[cls]:
        with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
            if not 0 <= i < len(pf.pages): continue
            rs = table.rows(pf.pages[i])
        cols = table.columns(rs)
        if not cols: continue
        g = table.grid(rs, cols)
        for j in range(len(cols)):
            vals = [(n, c[j]) for n, c in g if j in c]
            if len(vals) < 2: continue
            tot = sum(v for _, v in vals)
            # 幾種常見結構的偏差
            for label, adj in (('全欄相加', tot),
                               ('全欄相加－最大列(可能是合計)', tot - max(v for _,v in vals)),
                               ('全欄相加－2×最大列', tot - 2*max(v for _,v in vals))):
                d = adj - anchor
                if best is None or abs(d) < abs(best[0]):
                    best = (d, i, j, label, len(vals), adj)
    if best is None: return f'{key}: 切不出任何欄'
    d,i,j,label,n,adj = best
    pct = abs(d)/anchor*100
    return (f'{key}\n    最接近: p{i} col{j} {label} = {adj:,} vs 錨 {anchor:,}'
            f'  差 {d:,} ({pct:.2f}%, {n} 列)')

for key in sys.argv[1:]:
    print(diag(key)); print()
