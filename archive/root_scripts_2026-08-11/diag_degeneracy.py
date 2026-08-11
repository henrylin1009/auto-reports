# -*- coding: utf-8 -*-
"""量「解的多重性」—— 排除法夠不夠用,取決於這個數字。

一頁上有 N 個數字、M 欄。問:有多少組 (欄, 連續列區間) 加起來等於錨?
若通常 1–2 組 → 排除小計/彙總層就能收斂。
若動輒數十組 → 排除法是在無底洞裡撈,得換別的判準。
"""
import collections, glob, json, statistics, time
import locate, table, pdfplumber

def solutions(pdf_path, page_no, anchor):
    with pdfplumber.open(pdf_path) as pf:
        if not 0 <= page_no < len(pf.pages): return []
        rs = table.rows(pf.pages[page_no])
    cols = table.columns(rs)
    if not cols: return []
    g = table.grid(rs, cols)
    out = []
    for j in range(len(cols)):
        idx = [i for i, (_, c) in enumerate(g) if j in c]
        vals = [g[i][1][j] for i in idx]
        for a in range(len(vals)):
            s, used = 0, []
            for b in range(a, len(vals)):
                if s and vals[b] == s: continue
                s += vals[b]; used.append(b)
                if len(used) < 2: continue
                if s == anchor: out.append((j, tuple(idx[u] for u in used), None))
                else:
                    for k in used:
                        if s - 2*vals[k] == anchor:
                            out.append((j, tuple(idx[u] for u in used), idx[k])); break
    return out

keys=[]
for p in sorted(glob.glob('facts/*.json')): keys += list(json.load(open(p)))
counts, t0 = [], time.time()
for key in keys:
    doc, cls = key.split('|')
    try:
        loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
    except Exception: continue
    if not anchor: continue
    n = 0
    for i in loc.pages[cls]:
        try: n += len(solutions(f'pdf_cache/{doc}.pdf', i, anchor))
        except Exception: pass
    counts.append((key, n))
have=[n for _,n in counts if n]
print(f'{len(counts)} 格,耗時 {time.time()-t0:.0f}s')
print(f'  完全沒有解     {sum(1 for _,n in counts if n==0)}')
print(f'  有解的 {len(have)} 格,每格解數:  中位數 {statistics.median(have):.0f}   平均 {statistics.mean(have):.1f}   最多 {max(have)}')
d=collections.Counter('1 組' if n==1 else '2-3 組' if n<=3 else '4-10 組' if n<=10 else '>10 組' for n in have)
for k in ('1 組','2-3 組','4-10 組','>10 組'): print(f'    {k:8s} {d[k]:4d} 格 ({d[k]/len(have):4.0%})')
print('\n解最多的 10 格:')
for k,n in sorted(counts,key=lambda x:-x[1])[:10]: print(f'   {n:5d}  {k}')
