# -*- coding: utf-8 -*-
"""候選解的「選擇判準」比較 —— 決定這個案型要不要進 LLM / 人工佇列。

只在「正解確實在候選裡」的案子上算命中率:那才是判準的準度,
不會被切表能力(天花板 50%)污染。

判準:
  D1 對得到桶的列數最多       ← 本次要驗的
  D2 對得到桶的比例最高
  D3 列數最多                ← 實測過會爆(202502_5836 AC 抓到小計層),當對照組
  D4 D1 為主、平手時列數多者優先
"""
import collections, glob, json, time
import pdfplumber
import buckets, locate, table, table_camelot

_geo = {}
def geo_grid(doc, i):
    if (doc, i) not in _geo:
        with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
            rs = table.rows(pf.pages[i]) if 0 <= i < len(pf.pages) else []
        cols = table.columns(rs)
        _geo[(doc, i)] = (table.grid(rs, cols), len(cols))
    return _geo[(doc, i)]


def cands_with_names(grid, ncols, anchor):
    """回傳 [(Counter(絕對值), [名字...])] —— 比 recall.candidates 多帶名字。"""
    out = []
    for j in range(ncols):
        idx = [r for r, (_, c) in enumerate(grid) if j in c]
        vals = [grid[r][1][j] for r in idx]
        for a in range(len(vals)):
            s, used = 0, []
            for b in range(a, len(vals)):
                if s and vals[b] == s:
                    continue
                s += vals[b]; used.append(b)
                if len(used) < 2:
                    continue
                hit = (s == anchor) or any(s - 2 * vals[k] == anchor for k in used)
                if hit:
                    rows = [idx[u] for u in used]
                    out.append((collections.Counter(abs(grid[r][1][j]) for r in rows),
                                [grid[r][0] for r in rows]))
    return out


def score(names):
    n = sum(1 for x in names if buckets.bucket({'name': x}) is not None)
    return n, (n / len(names) if names else 0), len(names)


res, t0 = collections.Counter(), time.time()
bad = []
for p in sorted(glob.glob('facts/*.json')):
    for key, recs in json.load(open(p)).items():
        doc, cls = key.split('|')
        try:
            loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
        except Exception: continue
        if not anchor: continue
        cands = []
        for i in sorted(set(loc.pages[cls]) | {r['source_page'] for r in recs}):
            for fn in (geo_grid, table_camelot.grid_of):
                try:
                    g, nc = fn(doc, i); cands += cands_with_names(g, nc, anchor)
                except Exception: pass
        if not cands: continue
        for r in recs:
            want = collections.Counter(abs(row['cols'][r['total_col']])
                                       for row in r['rows'] if r['total_col'] in row['cols'])
            if not want or not any(c == want for c, _ in cands):
                continue                       # 正解不在候選裡 → 不是判準的問題
            res['分母(正解在候選裡)'] += 1
            res['候選數合計'] += len(cands)
            sc = [score(nm) for _, nm in cands]
            picks = {
                'D1 對桶列數最多':  max(range(len(cands)), key=lambda i2: sc[i2][0]),
                'D2 對桶比例最高':  max(range(len(cands)), key=lambda i2: sc[i2][1]),
                'D3 列數最多':      max(range(len(cands)), key=lambda i2: sc[i2][2]),
                'D4 對桶列數+列數': max(range(len(cands)), key=lambda i2: (sc[i2][0], sc[i2][2])),
            }
            for k, i2 in picks.items():
                if cands[i2][0] == want:
                    res[k] += 1
                elif k == 'D4 對桶列數+列數':
                    bad.append((key, r['source_page'], len(cands),
                                sc[i2][:1], cands[i2][1][:5]))
n = res['分母(正解在候選裡)']
print(f'══ 判準比較({time.time()-t0:.0f}s)══  分母 {n} 份(正解確實在候選裡)')
print(f'   平均每份 {res["候選數合計"]/n:.1f} 個候選\n')
for k in ('D1 對桶列數最多', 'D2 對桶比例最高', 'D3 列數最多', 'D4 對桶列數+列數'):
    print(f'   {k:18s} 選對 {res[k]:3d}/{n}  ({res[k]/n:.0%})')
print(f'\n   D4 選錯的 {len(bad)} 份,前 10:')
for b in bad[:10]:
    print(f'      {b[0]} p{b[1]}  {b[2]}候選  對桶{b[3][0]}列  {b[4]}')
