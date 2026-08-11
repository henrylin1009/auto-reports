# -*- coding: utf-8 -*-
"""天花板:網格裡到底有沒有正確答案?—— 決定瓶頸在「切表」還是在「選擇」。

分三級,對應下游要多聰明:
  L1 值都在網格裡(任一欄)  → 資訊沒丟。選對就成,LLM 有機會
  L2 值都在**同一欄**       → LLM 只要選列
  L3 值都在同一欄且**連續**  → 最簡單:選一個區間

L1 低 = 切表把資訊弄丟了,換模型沒用。
L1 高但 L3 低 = 資訊都在,只是不好選 → **這正是 LLM 該做的事**。
"""
import collections, glob, json, time
import pdfplumber
import locate, table, table_camelot

_geo = {}
def geo_grid(doc, i):
    if (doc, i) not in _geo:
        with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
            rs = table.rows(pf.pages[i]) if 0 <= i < len(pf.pages) else []
        cols = table.columns(rs)
        _geo[(doc, i)] = (table.grid(rs, cols), len(cols))
    return _geo[(doc, i)]

def levels(grids, want):
    """want = Counter(絕對值)。回傳 (L1, L2, L3)。"""
    l1 = l2 = l3 = False
    for g, nc in grids:
        allv = collections.Counter(abs(v) for _, c in g for v in c.values())
        if not (want - allv): l1 = True
        for j in range(nc):
            idx = [r for r, (_, c) in enumerate(g) if j in c]
            colv = collections.Counter(abs(g[r][1][j]) for r in idx)
            if not (want - colv):
                l2 = True
                # 連續性:want 的元素是否落在一段連續的 idx 裡
                pos = [k for k, r in enumerate(idx) if abs(g[r][1][j]) in want]
                if pos and pos[-1] - pos[0] + 1 <= len(want) + 2: l3 = True
    return l1, l2, l3

res, t0 = collections.Counter(), time.time()
for p in sorted(glob.glob('facts/*.json')):
    for key, recs in json.load(open(p)).items():
        doc, cls = key.split('|')
        try: loc = locate.locate(f'pdf_cache/{doc}.pdf')
        except Exception: continue
        if cls not in loc.anchors: continue
        for r in recs:
            want = collections.Counter(abs(row['cols'][r['total_col']])
                                       for row in r['rows'] if r['total_col'] in row['cols'])
            if not want: continue
            sp = r['source_page']
            pages = [sp - 1, sp, sp + 1]   # 跨頁表:附註常印「(接次頁)」
            gs = []
            for i in pages:
                for fn in (geo_grid, table_camelot.grid_of):
                    try: gs.append(fn(doc, i))
                    except Exception: pass
            l1, l2, l3 = levels(gs, want)
            kind = '明細表' if r['source_page'] > 100 else '附註'
            res[(kind, 'L3 同欄且連續')] += l3
            res[(kind, 'L2 同欄')] += l2
            res[(kind, 'L1 值都在')] += l1
            res[(kind, 'N')] += 1
print(f'══ 天花板({time.time()-t0:.0f}s)══   分母=facts 的 record')
for kind in ('附註', '明細表'):
    n = res[(kind, 'N')]
    if not n: continue
    print(f'\n  {kind}  {n} 份')
    for lv in ('L1 值都在', 'L2 同欄', 'L3 同欄且連續'):
        print(f'      {lv:14s} {res[(kind,lv)]:4d}  ({res[(kind,lv)]/n:.0%})')
N = res[('附註','N')] + res[('明細表','N')]
for lv in ('L1 值都在', 'L2 同欄', 'L3 同欄且連續'):
    v = res[('附註',lv)] + res[('明細表',lv)]
    print(f'  總計 {lv:14s} {v}/{N} ({v/N:.0%})')
