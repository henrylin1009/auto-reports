# -*- coding: utf-8 -*-
"""A/B:同一個模型、同一套驗收(fill._attempt),只換「給它看哪些頁」。
   A = 現行 locate 候選頁   B = 錨所在的章節(sect3)"""
import sys, os, json, glob, time, argparse
sys.path.insert(0, ".")
import locate, fill, fill_auto, transcribe
from scratchpad.sect3 import heads, section_of

def section_pages(loc, cls):
    hs = heads(loc.texts); s = f"{loc.anchors[cls]:,}"; out = set(); secs = []
    for p, t in enumerate(loc.texts):
        if p == loc.bs_page or s not in t: continue
        li = next(i for i, ln in enumerate(t.rstrip().split("\n")) if s in ln)
        sec = section_of(loc.texts, hs, p, li)
        if sec: out |= set(range(sec[0], sec[1] + 1)); secs.append(sec)
    return sorted(out), secs

def ctx_section(loc, cls):
    pages, secs = section_pages(loc, cls)
    head = [f"# {loc.name}  類別={cls}  錨(BS 合計)={loc.anchors[cls]:,} 仟元",
            f"# 錨落在這些章節裡,整章給你(0-based 頁碼;BS 頁 p{loc.bs_page} 已排除):"]
    for s in secs: head.append(f"#   p{s[0]}–p{s[1]}  「{s[2][:40]}」")
    head.append("# 章節裡不只一張表,只抄與錨相符的那(幾)張;其餘無關的表不要抄。")
    for i in pages:
        head.append(f"\n===== page {i} =====\n{loc.texts[i]}")
    return "\n".join(head), pages

def build(loc, cls, mode):
    if mode == "B":
        ctx, pages = ctx_section(loc, cls)
    else:
        pages = list(loc.pages[cls]); ctx = transcribe.context_pages(loc, cls, pages)
    prompt = "\n".join([
        f"你在抄一份台灣銀行財報的有價證券明細表。錨(BS 合計)= {loc.anchors[cls]:,} 仟元。",
        "", fill.RULES, fill_auto.OUTPUT_CONTRACT, "",
        "## 自己先對一次",
        f"把每一欄各自加總,應該有一欄的和等於錨 {loc.anchors[cls]:,}"
        f"(哪一欄是合計欄不必你判斷,系統事後會自己挑)。", "",
        "## 來源頁", ctx])
    return prompt, pages

def run(cells, mode, reader, out):
    res = []
    for n, key in enumerate(cells, 1):
        doc, cls = key.split("|")
        print(f"[{n}/{len(cells)}] {mode} {key} ...", end=" ", flush=True)
        try:
            loc = locate.locate(f"pdf_cache/{doc}.pdf")
            if cls not in loc.anchors:
                print("NO_ANCHOR"); res.append({"key":key,"mode":mode,"outcome":"NO_ANCHOR"}); continue
            prompt, pages = build(loc, cls, mode)
            raw = fill_auto.READERS[reader](prompt)
            data = fill_auto._parse_json(raw)
            if not data or "records" not in data:
                print("PARSE_FAIL"); res.append({"key":key,"mode":mode,"outcome":"PARSE_FAIL","raw":raw[:800]}); continue
            recs = data["records"] or []
            for r in recs: r.setdefault("doc",doc); r.setdefault("class",cls)
            ok, reason, drecs, hard = fill._attempt(doc, cls, loc, recs)
            print("PASS" if ok else f"FAIL {str(reason)[:90]}")
            res.append({"key":key,"mode":mode,"outcome":"PASS" if ok else "FAIL",
                        "reason":reason,"pages":pages,"nchars":len(prompt),
                        "records":drecs if ok else recs})
        except Exception as e:
            print(f"ERROR {type(e).__name__}: {e}")
            res.append({"key":key,"mode":mode,"outcome":"ERROR","reason":str(e)[:300]})
        json.dump(res, open(out,"w"), ensure_ascii=False, indent=1)
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells"); ap.add_argument("--mode", default="B")
    ap.add_argument("--reader", default="gemini"); ap.add_argument("--out", default="scratchpad/ab.json")
    a = ap.parse_args()
    cells = a.cells.split(",")
    run(cells, a.mode, a.reader, a.out)
