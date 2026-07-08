"""跨年度覆蓋測試 — 驗證三分類解析器能否規格化延展到不同年份。
對每 (家,期,分類) 抽取,並用 checksum(各項加總 vs 財報自印小計)驗證。
掉格或 checksum 不符 = 該年版面沒接住,需補規則(而非默默給錯)。
"""
import re, time, requests, pdfplumber
from pathlib import Path
import extract3 as E

CACHE=Path("pdf_cache"); CACHE.mkdir(exist_ok=True)
BANKS=[("5841","中信"),("5836","富邦"),("5847","玉山"),("5835","國泰")]

def dl(code, roc, month, tries=4):
    fn=f"{1911+roc}{month}_{code}_AI3.pdf"; dest=CACHE/fn
    if dest.exists() and dest.stat().st_size>100000: return dest
    for a in range(tries):
        try:
            s=requests.Session()
            r=s.post("https://doc.twse.com.tw/server-java/t57sb01",
                data={"step":"9","kind":"A","co_id":code,"filename":fn,"colorchg":"1"},timeout=30)
            r.encoding="big5"; m=re.search(r"href='(/pdf/[^']+\.pdf)'",r.text)
            if not m: return None
            data=s.get("https://doc.twse.com.tw"+m.group(1),timeout=60).content
            dest.write_bytes(data); time.sleep(0.8)   # 節流,避免被擋
            return dest
        except Exception:
            time.sleep(2*(a+1))                        # 退避重試
    return None

def cov(items):   # 三大債種有幾種抓到(公債/公司債/金融債)
    return sum(1 for k in ("政府公債","公司債","金融債券") if items.get(k,0)>0)

def run(rocs):
    periods=[(roc,mth,f"{1911+roc}{'H1' if mth=='02' else 'H2'}") for roc in rocs for mth in ("02","04")]
    for code,name in BANKS:
        print(f"\n{'='*70}\n{name}({code})  覆蓋度 (每格 = Trading/OCI/AC 抓到的主要債種數 0-3)\n{'='*70}")
        print(f"{'期間':<9}{'Trading':>9}{'OCI':>7}{'AC':>7}")
        for roc,mth,label in periods:
            p=dl(code,roc,mth)
            if not p:
                print(f"{label:<9}{'(無檔)':>9}"); continue
            try:
                t="\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
                cells=[]
                for cls in ("Trading","OCI","AC"):
                    it=E.parse_class(t,cls); cells.append(cov(it))
                flag="" if all(c>=1 for c in cells) else "  ⚠️掉格"
                print(f"{label:<9}{cells[0]:>9}{cells[1]:>7}{cells[2]:>7}{flag}")
            except Exception as ex:
                print(f"{label:<9}  ERR {str(ex)[:30]}")

if __name__=="__main__":
    import sys
    rocs=range(107,114) if len(sys.argv)<2 else [int(x) for x in sys.argv[1:]]
    run(rocs)
