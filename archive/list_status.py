import pdfplumber
from pathlib import Path
import extract3 as E
CACHE=Path("pdf_cache")
BANKS=[("5841","中信"),("5836","富邦"),("5847","玉山"),("5835","國泰")]
PERIODS=[(roc,mth) for roc in range(109,114) for mth in ("02","04")]
def lbl(roc,mth): return f"{1911+roc}{'H1' if mth=='02' else 'H2'}"
bad=[]; nosub=[]; empty=[]; okc=0
for roc,mth in PERIODS:
    for code,name in BANKS:
        p=CACHE/f"{1911+roc}{mth}_{code}_AI3.pdf"
        if not p.exists() or p.stat().st_size<100000:
            empty.append(f"{lbl(roc,mth)} {name} (缺檔)"); continue
        t="\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
        for cls in ("Trading","OCI","AC"):
            it,st,ok=E.checksum(t,cls)
            tag=f"{lbl(roc,mth)} {name} {cls}"
            if not it: empty.append(tag+" (空)")
            elif ok: okc+=1
            elif st is None: nosub.append(tag)
            else:
                diff=(sum(it.values())-st)/1e5
                bad.append(f"{tag}  加總={sum(it.values())/1e5:,.0f} 小計={st/1e5:,.0f} 差={diff:+,.0f}億")
print(f"✓已驗證={okc}  ○無小計={len(nosub)}  ⚠️不符={len(bad)}  ✗空/缺檔={len(empty)}")
print("\n=== ⚠️ 不符(真正要查) ===")
for b in bad: print("  ",b)
print("\n=== ○ 無小計(未驗,邏輯健全) ===")
for n in nosub: print("  ",n)
