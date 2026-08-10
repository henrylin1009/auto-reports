# -*- coding: utf-8 -*-
"""拿 facts/ 當標準答案,驗幾何抽出來的東西**對不對**,不只是「對不對得上錨」。

「對上錨」只證明算術自洽 —— 實測 202502_5836 OCI 對上了錨,抓到的卻是
彙總層 + 明細層混在一起還硬塞一個負號的垃圾解。所以覆蓋率必須配上正確率看。
"""
import collections, glob, json, time
import locate, table, sys
STRICT = '--strict' in sys.argv

truth = {}
for p in sorted(glob.glob('facts/*.json')):
    for key, recs in json.load(open(p)).items():
        vs = collections.Counter()
        for r in recs:
            for row in r['rows']:
                v = row['cols'].get(r['total_col'])
                if v is not None: vs[abs(v)] += 1
        truth.setdefault(key, vs)

res, wrong = collections.Counter(), []
t0 = time.time()
for key, want in truth.items():
    doc, cls = key.split('|')
    try:
        loc = locate.locate(f'pdf_cache/{doc}.pdf'); anchor = loc.anchors.get(cls)
    except Exception:
        res['錯誤']+=1; continue
    if not anchor: res['錨讀不到']+=1; continue
    got = None
    for i in loc.pages[cls]:
        try: r = table.extract(f'pdf_cache/{doc}.pdf', i, anchor, min_rows=3, allow_minus=False) if STRICT else table.extract(f'pdf_cache/{doc}.pdf', i, anchor)
        except Exception: r = None
        if r: got = collections.Counter(abs(v) for _, v in r[1]); break
    if got is None:
        res['① 對不上錨(誠實地說不知道)']+=1
    elif got == want:
        res['② 對上錨且與 facts 逐值相同']+=1
    elif set(got) <= set(want):
        res['③ 對上錨,是 facts 的子集(抄少了)']+=1; wrong.append((key,'子集',len(got),len(want)))
    else:
        res['④ 對上錨但值對不上 facts(垃圾解)']+=1
        wrong.append((key,'不符',len(got),len(want)))
tot=sum(res.values())
print(f'== 以 facts/ 為標準答案,{tot} 格,耗時 {time.time()-t0:.0f}s ==')
for k,n in sorted(res.items()): print(f'  {n:4d}/{tot} ({n/tot:5.0%})  {k}')
print(f'\n③④ 明細({len(wrong)} 格,幾何列數 vs facts 列數):')
for w in wrong[:40]: print('   ',w)
