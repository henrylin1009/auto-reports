# -*- coding: utf-8 -*-
"""量:用「章節」取代「候選頁+擴頁」,涵蓋率與成本各是多少。
真值 = facts/ 裡 155 格已通過驗收的 record 的 source_page(算術驗過的)。"""
import re, sys, glob, json, collections
sys.path.insert(0, ".")
import locate
from scratchpad.sect import HEAD

def heads(texts):
    out = []
    for p, t in enumerate(texts):
        for li, ln in enumerate(t.split("\n")):
            m = HEAD.match(ln)
            if m:
                out.append((p, li, ln.strip()))
    return out

def section_of(texts, hs, p, li):
    """(頁,行) 落在哪個章節 → (起頁, 迄頁, 標題) ;找不到前置標題回 None"""
    prev = None
    for h in hs:
        if (h[0], h[1]) <= (p, li):
            prev = h
        else:
            return (prev[0], h[0], prev[2]) if prev else None
    return (prev[0], len(texts) - 1, prev[2]) if prev else None

def anchor_hits(texts, anchor):
    s = f"{anchor:,}"
    out = []
    for p, t in enumerate(texts):
        for li, ln in enumerate(t.split("\n")):
            if s in ln:
                out.append((p, li))
    return out

def main():
    F = {}
    for fp in glob.glob("facts/*.json"):
        F.update(json.load(open(fp)))
    stats = collections.Counter()
    rows = []
    docs = sorted({k.split("|")[0] for k in F})
    for doc in docs:
        path = f"pdf_cache/{doc}.pdf"
        try:
            loc = locate.locate(path)
        except Exception as e:
            stats["locate_fail"] += 1; continue
        hs = heads(loc.texts)
        for cls in locate.CLASSES:
            key = f"{doc}|{cls}"
            if key not in F: continue
            recs = F[key]
            truth = sorted({r["source_page"] for r in recs})
            if cls not in loc.anchors:
                stats["no_anchor"] += 1; continue
            hits = anchor_hits(loc.texts, loc.anchors[cls])
            secs, pages = [], set()
            for (p, li) in hits:
                if p == loc.bs_page: continue
                s = section_of(loc.texts, hs, p, li)
                if s:
                    secs.append(s); pages |= set(range(s[0], s[1] + 1))
            l0 = set(loc.pages.get(cls) or [])
            cover_sec = set(truth) <= pages
            cover_l0 = set(truth) <= l0
            chars = sum(len(loc.texts[i]) for i in sorted(pages))
            charsl0 = sum(len(loc.texts[i]) for i in sorted(l0))
            stats["cells"] += 1
            stats["sec_cover" if cover_sec else "sec_miss"] += 1
            stats["l0_cover" if cover_l0 else "l0_miss"] += 1
            rows.append(dict(key=key, truth=truth, l0=sorted(l0), sec=sorted(pages),
                             cover_sec=cover_sec, cover_l0=cover_l0,
                             chars=chars, charsl0=charsl0,
                             titles=[s[2][:28] for s in secs]))
    json.dump(rows, open("scratchpad/measure.json", "w"), ensure_ascii=False, indent=1)
    print(stats)
    npg = [len(r["sec"]) for r in rows]
    print("章節頁數 中位/最大:", sorted(npg)[len(npg)//2], max(npg))
    print("字數 中位/最大:", sorted(r['chars'] for r in rows)[len(rows)//2],
          max(r['chars'] for r in rows), " (level0 中位:",
          sorted(r['charsl0'] for r in rows)[len(rows)//2], ")")
    print("\n--- 章節沒蓋到真值的格 ---")
    for r in rows:
        if not r["cover_sec"]:
            print(" ", r["key"], "真值", r["truth"], "l0", r["l0"], "章節", r["sec"], r["titles"])
    print("\n--- l0 沒蓋到但章節蓋到(= 省掉擴頁的格) ---")
    n=0
    for r in rows:
        if r["cover_sec"] and not r["cover_l0"]:
            n+=1; print(" ", r["key"], "真值", r["truth"], "l0", r["l0"], "章節", r["sec"])
    print("小計", n)

main()
