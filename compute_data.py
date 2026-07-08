"""算出畫圖用資料:每(銀行,期間)的各分類/各債種 MV(億),存 data.json。"""
import json, pdfplumber
from pathlib import Path
import extract3 as E
CACHE=Path("pdf_cache")
BANKS=[("5841","中信"),("5843","兆豐"),("5835","國泰"),("5836","富邦"),("5847","玉山")]
PERIODS=[(roc,mth) for roc in range(109,114) for mth in ("02","04")]
def plabel(roc,mth): return f"{1911+roc}{'H1' if mth=='02' else 'H2'}"

out={"periods":[plabel(r,m) for r,m in PERIODS],"banks":[n for _,n in BANKS],"data":{}}
for roc,mth in PERIODS:
    lbl=plabel(roc,mth)
    for code,name in BANKS:
        p=CACHE/f"{1911+roc}{mth}_{code}_AI3.pdf"
        key=f"{lbl}|{name}"
        if name=="兆豐" or not p.exists() or p.stat().st_size<100000:
            out["data"][key]=None; continue
        t="\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
        rec={}
        for cls in ("Trading","OCI","AC"):
            b=E.bond_buckets(E.parse_class(t,cls))
            rec[cls]={
                "公債":b["公債"], "公司債":b["公司債"], "金融債":b["金融債"],
                "其他":b["資產基礎"]+b["其他"]+b["國庫券"]+b["可轉讓定存單"],
            }
        out["data"][key]=rec
json.dump(out, open("data.json","w"), ensure_ascii=False)
print("已存 data.json  期數",len(out["periods"]),"家數",len(out["banks"]))
