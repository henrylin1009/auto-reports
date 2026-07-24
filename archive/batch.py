"""批次抽取 4 家(中信/富邦/玉山/國泰)Trading 債券,2020H1~2024H2。
順便實測:同一套 summary 解析器能不能跨年度全通(回答『改版』疑慮)。
"""
import re, requests, pdfplumber
from pathlib import Path
import extract2 as E

CACHE = Path("pdf_cache"); CACHE.mkdir(exist_ok=True)
BANKS = [("5841","中信"), ("5836","富邦"), ("5847","玉山"), ("5835","國泰")]
# 期間: 2020H1..2024H2  => roc 109..113, month 02(H1)/04(H2)
PERIODS = [(roc, mth, f"{2020+(roc-109)}{'H1' if mth=='02' else 'H2'}")
           for roc in range(109,114) for mth in ("02","04")]

def dl(code, roc, month):
    fn=f"{1911+roc}{month}_{code}_AI3.pdf"; dest=CACHE/fn
    if dest.exists() and dest.stat().st_size>100000: return dest
    s=requests.Session()
    r=s.post("https://doc.twse.com.tw/server-java/t57sb01",
        data={"step":"9","kind":"A","co_id":code,"filename":fn,"colorchg":"1"},timeout=30)
    r.encoding="big5"; m=re.search(r"href='(/pdf/[^']+\.pdf)'",r.text)
    if not m: return None
    dest.write_bytes(s.get("https://doc.twse.com.tw"+m.group(1),timeout=60).content); return dest

def run():
    result={}   # (label) -> {name: (cp, gb)}
    for roc, mth, label in PERIODS:
        result[label]={}
        for code,name in BANKS:
            p=dl(code,roc,mth)
            if not p:
                result[label][name]=None; continue
            try:
                t="\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
                items=E.parse_summary_trading(t); cp,gb=E.buckets(items)
                result[label][name]=(cp/1e5, gb/1e5) if items else None
            except Exception as ex:
                result[label][name]=("ERR",str(ex)[:20])
    # 印表: CP+NCD+BA
    for metric,idx in [("CP+NCD+BA",0),("GB",1)]:
        print(f"\n{'='*66}\n{metric} (億元)\n{'='*66}")
        print(f"{'期間':<8}"+"".join(f"{n:>10}" for _,n in BANKS))
        for _,_,label in PERIODS:
            row=result[label]
            cells=[]
            for _,n in BANKS:
                v=row.get(n)
                cells.append(f"{v[idx]:>10,.0f}" if isinstance(v,tuple) and not isinstance(v[0],str) else f"{'—':>10}")
            print(f"{label:<8}"+"".join(cells))

if __name__=="__main__":
    run()
