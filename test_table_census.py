# -*- coding: utf-8 -*-
"""普查:純幾何 + 「選那一欄使和==錨」,能覆蓋多少格?

**這是量測不是閘門** —— 判準先寫死再跑,跑完不准回頭調參數。
對照組:攤平字串 + regex 的同一判準 = 57%(2026-07-29 實測)。
"""
import collections
import glob
import json
import sys
import time

import locate
import table

def census(page_mode):
    """page_mode: 'candidates' = locate 的候選頁(生產情境)
                  'candidates+1' = 候選頁及其鄰頁"""
    seen, res, wins, fails = set(), collections.Counter(), [], []
    keys = []
    for p in sorted(glob.glob('facts/*.json')):
        keys += list(json.load(open(p)))
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        doc, cls = key.split('|')
        try:
            loc = locate.locate(f'pdf_cache/{doc}.pdf')
        except Exception as e:
            res['ERR ' + type(e).__name__] += 1
            continue
        anchor = loc.anchors.get(cls)
        if not anchor:
            res['錨讀不到'] += 1
            continue
        pages = list(loc.pages[cls])
        if page_mode.endswith('+1'):
            pages = sorted({i for p0 in pages for i in (p0 - 1, p0, p0 + 1)})
        hit = None
        for i in pages:
            try:
                r = table.extract(f'pdf_cache/{doc}.pdf', i, anchor)
            except Exception:
                r = None
            if r:
                hit = (i, r); break
        if hit:
            i, (j, rowsv) = hit
            named = sum(1 for n, _ in rowsv if n)
            res['✅ 幾何對上錨'] += 1
            wins.append((key, i, len(rowsv), named))
        else:
            res['✗ 對不上'] += 1
            fails.append(key)
    return res, wins, fails


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'candidates'
    t0 = time.time()
    res, wins, fails = census(mode)
    tot = sum(res.values())
    print(f'== page_mode={mode}  共 {tot} 格  耗時 {time.time()-t0:.0f}s ==')
    for k, n in res.most_common():
        print(f'  {n:4d}/{tot}  ({n/tot:5.0%})  {k}')
    if wins:
        nm = sum(w[3] for w in wins); rw = sum(w[2] for w in wins)
        print(f'\n對上的 {len(wins)} 格共 {rw} 列,其中 {nm} 列抓到名字 ({nm/rw:.0%});'
              f'{rw-nm} 列名字空白(基線飄移 → 要 LLM 配對)')
    print(f'\n對不上的 {len(fails)} 格:')
    for f in fails: print('   ', f)
