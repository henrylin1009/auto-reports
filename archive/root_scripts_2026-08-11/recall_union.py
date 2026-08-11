# -*- coding: utf-8 -*-
"""兩個切表引擎的聯集召回 —— 決定「要不要兩個都跑」。

`arXiv 2410.09871`:沒有一個 PDF 表格工具是完美的,但常常一個失敗另一個成功。
本測回答的是:合起來的天花板有多高?以及兩者同意時可不可信?
"""
import collections, glob, json, time
import pdfplumber
import locate, table, table_camelot
from recall import candidates

_geo = {}
def geo_grid(doc, i):
    if (doc, i) not in _geo:
        with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
            rs = table.rows(pf.pages[i]) if 0 <= i < len(pf.pages) else []
        cols = table.columns(rs)
        _geo[(doc, i)] = (table.grid(rs, cols), len(cols))
    return _geo[(doc, i)]

res, t0 = collections.Counter(), time.time()
for p in sorted(glob.glob('facts/*.json')):
    for key, recs in json.load(open(p)).items():
        doc, cls = key.split('|')
        try:
            loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
        except Exception: continue
        if not anchor: continue
        pages = sorted(set(loc.pages[cls]) | {r['source_page'] for r in recs})
        cg, cc = [], []
        for i in pages:
            for fn, bag in ((geo_grid, cg), (table_camelot.grid_of, cc)):
                try:
                    g, nc = fn(doc, i); bag += candidates(g, nc, anchor)
                except Exception: pass
        for r in recs:
            want = collections.Counter(abs(row['cols'][r['total_col']])
                                       for row in r['rows'] if r['total_col'] in row['cols'])
            if not want: continue
            kind = '明細表' if r['source_page'] > 100 else '附註'
            g_ok = any(c == want for c in cg)
            c_ok = any(c == want for c in cc)
            tag = ('兩者皆中' if g_ok and c_ok else 'geo 獨中' if g_ok
                   else 'camelot 獨中' if c_ok else '兩者皆未中')
            res[(kind, tag)] += 1
tot = sum(res.values())
print(f'══ 聯集召回  {tot} 份 record  {time.time()-t0:.0f}s ══')
for kind in ('附註', '明細表'):
    sub = {k[1]: v for k, v in res.items() if k[0] == kind}
    n = sum(sub.values())
    if not n: continue
    u = n - sub.get('兩者皆未中', 0)
    print(f'\n  {kind}({n} 份)  聯集命中 {u} ({u/n:.0%})')
    for t in ('兩者皆中', 'geo 獨中', 'camelot 獨中', '兩者皆未中'):
        print(f'      {t:12s} {sub.get(t,0):4d}')
u = tot - sum(v for k, v in res.items() if k[1] == '兩者皆未中')
both = sum(v for k, v in res.items() if k[1] == '兩者皆中')
print(f'\n  ══ 總聯集 {u}/{tot} ({u/tot:.0%})   其中兩者皆中 {both} ({both/tot:.0%})')
