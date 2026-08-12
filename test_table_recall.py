# -*- coding: utf-8 -*-
"""決定性量測:正確答案在不在「候選解」裡?

架構假設:程式列舉候選(實測中位數 2 個、最多 6 個)→ 選一個。
**天花板由本測的命中率決定,不由排序好壞決定。**

⚠️ 比對必須**逐 record**,不能逐格。一格常有兩份 record(附註 + 明細表),
把兩份的列混成一個集合去比,幾何只抽到其中一頁就會被誤判成沒中
(實測 202204_中信_個體|AC:truth 14 列其實是 8+6 兩份)。
"""
import collections, glob, json, sys, time
import pdfplumber
import locate, table

_pg = {}
def grid_of(doc, i):
    k = (doc, i)
    if k not in _pg:
        with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
            rs = table.rows(pf.pages[i]) if 0 <= i < len(pf.pages) else []
        cols = table.columns(rs)
        _pg[k] = (table.grid(rs, cols), len(cols))
    return _pg[k]

def candidates(doc, i, anchor):
    g, nc = grid_of(doc, i)
    out = []
    for j in range(nc):
        idx = [r for r, (_, c) in enumerate(g) if j in c]
        vals = [g[r][1][j] for r in idx]
        for a in range(len(vals)):
            s, used = 0, []
            for b in range(a, len(vals)):
                if s and vals[b] == s: continue
                s += vals[b]; used.append(b)
                if len(used) < 2: continue
                if s == anchor:
                    out.append([idx[u] for u in used])
                else:
                    for k in used:
                        if s - 2*vals[k] == anchor:
                            out.append([idx[u] for u in used]); break
    return [(collections.Counter(abs(g[r][1][j2]) for r in pick), pick)
            for j2 in range(nc) for pick in out
            if all(j2 in g[r][1] for r in pick)] or \
           [(collections.Counter(), [])] if False else \
           [(collections.Counter(abs(v) for v in _col(g, pick)), pick) for pick in out]

def _col(g, pick):
    # pick 的列共通的欄:取第一列有的欄裡,全部列都有的那個
    common = set(g[pick[0]][1])
    for r in pick[1:]: common &= set(g[r][1])
    j = min(common) if common else None
    return [g[r][1][j] for r in pick] if j is not None else []

res, detail, t0 = collections.Counter(), [], time.time()
for p in sorted(glob.glob('facts/*.json')):
    for key, recs in json.load(open(p)).items():
        doc, cls = key.split('|')
        try:
            loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
        except Exception: continue
        if not anchor: continue
        pages = sorted(set(loc.pages[cls]) | {r['source_page'] for r in recs})
        cands = []
        for i in pages:
            try: cands += candidates(doc, i, anchor)
            except Exception: pass
        for r in recs:
            want = collections.Counter(abs(row['cols'][r['total_col']])
                                       for row in r['rows'] if r['total_col'] in row['cols'])
            if not want: continue
            if not cands: res['① 零候選']+=1
            elif any(c == want for c, _ in cands): res['② ✅ 命中']+=1; detail.append((key,'HIT',len(cands)))
            elif any(set(want) <= set(c) for c, _ in cands): res['③ 候選是超集(多抓)']+=1; detail.append((key,'SUP',len(cands)))
            else: res['④ 有候選但沒一個對']+=1; detail.append((key,'MISS',len(cands)))
tot=sum(res.values())
print(f'== 逐 record 比對,共 {tot} 份,耗時 {time.time()-t0:.0f}s ==')
for k,n in sorted(res.items()): print(f'  {n:4d}/{tot} ({n/tot:5.0%})  {k}')
h=[c for _,t,c in detail if t=='HIT']
if h: print(f'\n命中時平均 {sum(h)/len(h):.1f} 個候選 → 「{sum(h)/len(h):.0f} 選 1」')
print('\n沒中的:')
for k,t,c in detail:
    if t=='MISS': print(f'   {k} ({c} 候選)')
