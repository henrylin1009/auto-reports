import sys, glob, json, collections
sys.path.insert(0, ".")
import locate
from scratchpad.sect2 import heads, section_of

def anchor_hits(texts, anchor):
    s = f"{anchor:,}"
    return [(p, li) for p, t in enumerate(texts)
            for li, ln in enumerate(t.split("\n")) if s in ln]

F = {}
for fp in glob.glob("facts/*.json"):
    F.update(json.load(open(fp)))
st = collections.Counter(); rows = []
for doc in sorted({k.split("|")[0] for k in F}):
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    hs = heads(loc.texts)
    era = "2023+" if int(doc[:4]) >= 2023 else "≤2022"
    for cls in locate.CLASSES:
        key = f"{doc}|{cls}"
        if key not in F or cls not in loc.anchors: continue
        truth = sorted({r["source_page"] for r in F[key]})
        pages, titles = set(), []
        for (p, li) in anchor_hits(loc.texts, loc.anchors[cls]):
            if p == loc.bs_page: continue
            s = section_of(loc.texts, hs, p, li)
            if s: pages |= set(range(s[0], s[1]+1)); titles.append((s[3], s[2][:30]))
        l0 = set(loc.pages.get(cls) or [])
        ok = set(truth) <= pages
        st[f"{era}/cells"] += 1
        st[f"{era}/{'cover' if ok else 'MISS'}"] += 1
        st[f"{era}/l0_{'cover' if set(truth)<=l0 else 'miss'}"] += 1
        rows.append(dict(key=key, era=era, truth=truth, l0=sorted(l0), sec=sorted(pages),
                         ok=ok, chars=sum(len(loc.texts[i]) for i in pages), titles=titles))
json.dump(rows, open("scratchpad/measure2.json","w"), ensure_ascii=False, indent=1)
print(st)
for era in ("2023+", "≤2022"):
    sub=[r for r in rows if r["era"]==era]
    npg=sorted(len(r["sec"]) for r in sub); ch=sorted(r["chars"] for r in sub)
    if sub: print(era, "格數",len(sub), "頁數 中位/90%/最大", npg[len(npg)//2], npg[int(len(npg)*.9)], npg[-1],
                  "| 字數 中位/最大", ch[len(ch)//2], ch[-1])
print("\n--- 沒蓋到的 ---")
for r in rows:
    if not r["ok"]: print(" ", r["era"], r["key"], "真值",r["truth"], "l0",r["l0"], "章節",r["sec"], r["titles"])
print("\n--- 章節超過 6 頁的(2023+) ---")
for r in rows:
    if r["era"]=="2023+" and len(r["sec"])>6: print(" ", r["key"], len(r["sec"]),"頁", r["sec"][:3],"…", r["titles"])
