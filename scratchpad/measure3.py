import sys, glob, json, collections
sys.path.insert(0, ".")
import locate
from scratchpad.sect2 import heads, section_of

F = {}
for fp in glob.glob("facts/*.json"): F.update(json.load(open(fp)))
st = collections.Counter(); big = []
for doc in sorted({k.split("|")[0] for k in F}):
    loc = locate.locate(f"pdf_cache/{doc}.pdf"); hs = heads(loc.texts)
    for cls in locate.CLASSES:
        key = f"{doc}|{cls}"
        if key not in F or cls not in loc.anchors: continue
        s = f"{loc.anchors[cls]:,}"
        for p, t in enumerate(loc.texts):
            if p == loc.bs_page or s not in t: continue
            li = next(i for i, ln in enumerate(t.split("\n")) if s in ln)
            sec = section_of(loc.texts, hs, p, li)
            n = sec[1]-sec[0]+1 if sec else -1
            st[f"span{min(n,9) if n>0 else 'none'}"] += 1
            ch = sum(len(loc.texts[i]) for i in range(sec[0], sec[1]+1)) if sec else 0
            if n > 4: big.append((key, p, n, sec[3], sec[2][:34], ch))
print("每個錨命中點的章節跨頁分布:", dict(sorted(st.items())))
print("命中點總數", sum(st.values()), " >4頁的:", len(big))
for b in sorted(big, key=lambda x:-x[2])[:20]: print("  ", b)
