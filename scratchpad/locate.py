# -*- coding: utf-8 -*-
"""通用定位:把 BS 錨的值當字串 grep,找出「印著這個合計」的頁。
零版型知識——不認標題、不認小計、不認欄序。只回頁碼給 agent 讀。"""
import sys, os, json, collections
import pypdfium2 as pdf
import bs_anchor

def pages_with(path, anc):
    doc = pdf.PdfDocument(path)
    try:
        txt = [(doc[i].get_textpage().get_text_range() or "") for i in range(len(doc))]
    finally:
        doc.close()
    bs = bs_anchor.locate_cache if False else None
    out = {}
    for c, v in anc.items():
        s = f"{v:,}"
        out[c] = [i for i, t in enumerate(txt) if s in t]
    return out, len(txt)

if __name__ == "__main__":
    t = collections.Counter(); load = []
    miss = []
    for p in sys.argv[1:]:
        b = os.path.basename(p).replace(".pdf", "")
        anc, bspg = bs_anchor.read(p)
        if not anc: t["no_anchor_doc"] += 1; continue
        hits, n = pages_with(p, anc)
        for c in ("Trading", "OCI", "AC"):
            if c not in anc: t["no_anchor"] += 1; continue
            pgs = [i for i in hits[c] if i != bspg]
            if not pgs: t["0頁"] += 1; miss.append((b, c, anc[c]))
            else:
                t[f"{min(len(pgs),4)}頁" if len(pgs) < 4 else "4+頁"] += 1
                load.append(len(pgs))
    print(json.dumps(dict(t), ensure_ascii=False))
    if load:
        load.sort()
        print(f"候選頁數 中位數={load[len(load)//2]} 平均={sum(load)/len(load):.1f} 最多={load[-1]}")
    for m in miss[:20]: print("找不到:", m)
