import sys, glob, json, collections
sys.path.insert(0, ".")
import locate
from scratchpad.sect3 import heads, section_of

F = {}
for fp in glob.glob("facts/*.json"): F.update(json.load(open(fp)))
st = collections.Counter(); spans = collections.Counter(); miss=[]; rows=[]
for doc in sorted({k.split("|")[0] for k in F}):
    loc = locate.locate(f"pdf_cache/{doc}.pdf"); hs = heads(loc.texts)
    for cls in locate.CLASSES:
        key = f"{doc}|{cls}"
        if key not in F or cls not in loc.anchors: continue
        truth = sorted({r["source_page"] for r in F[key]}); s=f"{loc.anchors[cls]:,}"
        pages=set(); titles=[]
        for p,t in enumerate(loc.texts):
            if p==loc.bs_page or s not in t: continue
            li=next(i for i,ln in enumerate(t.split("\n")) if s in ln)
            sec=section_of(loc.texts,hs,p,li)
            if sec:
                pages|=set(range(sec[0],sec[1]+1)); titles.append((sec[3],sec[2][:30]))
                spans[min(sec[1]-sec[0]+1,9)]+=1
        era="2023+" if int(doc[:4])>=2023 else "≤2022"
        ok=set(truth)<=pages; st[f"{era}/{'cover' if ok else 'MISS'}"]+=1
        if not ok: miss.append((key,truth,sorted(loc.pages.get(cls) or []),sorted(pages),titles))
        rows.append((key,era,len(pages),sum(len(loc.texts[i]) for i in pages)))
print(st); print("命中點跨頁分布(9=9以上):",dict(sorted(spans.items())))
for era in ("2023+","≤2022"):
    sub=[r for r in rows if r[1]==era]; pg=sorted(r[2] for r in sub); ch=sorted(r[3] for r in sub)
    print(era,"格數",len(sub),"總頁 中位/90%/最大",pg[len(pg)//2],pg[int(len(pg)*.9)],pg[-1],
          "| 字數 中位/90%/最大",ch[len(ch)//2],ch[int(len(ch)*.9)],ch[-1])
print("\n--- 沒蓋到 ---")
for m in miss: print("  ",m)
