# -*- coding: utf-8 -*-
"""共用回歸:給定一個切表引擎,量「正確答案在不在候選解裡」。

天花板由本測決定 —— 候選裡沒有,再好的排序也選不出來。
用法: python3 recall.py geo | camelot
"""
import collections, glob, json, sys, time
import locate


def candidates(grid, ncols, anchor):
    """列舉所有「(某一欄, 某段連續列, 至多一列取負) 加起來 == 錨」的解。

    小計辨識、減項、破折號當 0 都在這裡,全是算術。**這是列舉不是選擇** ——
    選哪一個交給下游(排除法或 LLM 單選題)。
    """
    out = []
    for j in range(ncols):
        idx = [r for r, (_, c) in enumerate(grid) if j in c]
        vals = [grid[r][1][j] for r in idx]
        for a in range(len(vals)):
            s, used = 0, []
            for b in range(a, len(vals)):
                if s and vals[b] == s:      # 小計:等於目前累計和 → 跳過
                    continue
                s += vals[b]
                used.append(b)
                if len(used) < 2:
                    continue
                if s == anchor:
                    out.append([idx[u] for u in used])
                else:
                    for k in used:
                        if s - 2 * vals[k] == anchor:
                            out.append([idx[u] for u in used])
                            break
    return [collections.Counter(abs(grid[r][1][j]) for r in pick)
            for pick in out
            for j in [min(set.intersection(*(set(grid[r][1]) for r in pick)) or {None})]
            if j is not None]


def run(engine_name):
    if engine_name == 'camelot':
        import table_camelot as E
        grid_of = E.grid_of
    else:
        import pdfplumber, table
        _c = {}
        def grid_of(doc, i):
            if (doc, i) not in _c:
                with pdfplumber.open(f'pdf_cache/{doc}.pdf') as pf:
                    rs = table.rows(pf.pages[i]) if 0 <= i < len(pf.pages) else []
                cols = table.columns(rs)
                _c[(doc, i)] = (table.grid(rs, cols), len(cols))
            return _c[(doc, i)]

    res, detail, t0 = collections.Counter(), [], time.time()
    for p in sorted(glob.glob('facts/*.json')):
        for key, recs in json.load(open(p)).items():
            doc, cls = key.split('|')
            try:
                loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
            except Exception:
                continue
            if not anchor:
                continue
            cands = []
            for i in sorted(set(loc.pages[cls]) | {r['source_page'] for r in recs}):
                try:
                    g, nc = grid_of(doc, i)
                    cands += candidates(g, nc, anchor)
                except Exception:
                    pass
            for r in recs:
                want = collections.Counter(abs(row['cols'][r['total_col']])
                                           for row in r['rows'] if r['total_col'] in row['cols'])
                if not want:
                    continue
                sp = r['source_page']
                kind = '明細表' if sp > 100 else '附註'
                if not cands:
                    res[(kind, '① 零候選')] += 1
                elif any(c == want for c in cands):
                    res[(kind, '② ✅ 命中')] += 1; detail.append(len(cands))
                else:
                    res[(kind, '③ 有候選但沒中')] += 1
    return res, detail, time.time() - t0


if __name__ == '__main__':
    eng = sys.argv[1] if len(sys.argv) > 1 else 'geo'
    res, detail, secs = run(eng)
    tot = sum(res.values())
    print(f'══ engine={eng}   {tot} 份 record   {secs:.0f}s ══')
    for kind in ('附註', '明細表'):
        sub = {k[1]: v for k, v in res.items() if k[0] == kind}
        n = sum(sub.values())
        if not n: continue
        hit = sub.get('② ✅ 命中', 0)
        print(f'  {kind}({n} 份):  命中 {hit} ({hit/n:.0%})   ' +
              '  '.join(f'{k}={v}' for k, v in sorted(sub.items()) if not k.startswith('②')))
    hit = sum(v for k, v in res.items() if k[1].startswith('②'))
    print(f'  ──────  總命中 {hit}/{tot} ({hit/tot:.0%})' +
          (f'   命中時平均 {sum(detail)/len(detail):.1f} 個候選' if detail else ''))
