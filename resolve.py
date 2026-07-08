"""穩健取檔:不寫死 AI3,改去 TWSE 清單找「個體」那個檔(代碼各家/各年不一,如 AI2/AI3)。
補回缺檔,並統一存成 {YYYYMM}_{code}_AI3.pdf 讓下游照吃。
"""
import re, time, requests, pdfplumber
from pathlib import Path
CACHE=Path("pdf_cache")
BASE="https://doc.twse.com.tw"

# 瀏覽器標頭(避免政府網站拒絕預設 python-requests UA)
HEADERS={
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language":"zh-TW,zh;q=0.9",
    "Referer":BASE+"/",
}
def _sess():
    s=requests.Session(); s.headers.update(HEADERS); return s

def list_year(code, roc):
    r=_sess().get(f"{BASE}/server-java/t57sb01",
        params={"step":"1","colorchg":"1","mtype":"A","co_id":code,"year":roc},timeout=30)
    r.encoding="big5"; return r.text

def indiv_filename(html, yyyymm):
    """從清單找該期(YYYYMM 前綴)標為『個體』的檔名。"""
    # 每個 readfile2 檔名 + 其所在列是否含「個體」
    for m in re.finditer(r'readfile2\("A","\d+","('+re.escape(yyyymm)+r'_\d+_[A-Z0-9]+\.pdf)"\)', html):
        fn=m.group(1)
        row=html[max(0,m.start()-600):m.start()]         # 該檔連結前的列描述
        if "個體" in row or "個別" in row:
            return fn
    return None

def download(code, roc, month, tries=4):
    """回傳個體 PDF 路徑(存成 AI3 統一名)。自動解析正確代碼。"""
    yyyymm=f"{1911+roc}{month}"
    dest=CACHE/f"{yyyymm}_{code}_AI3.pdf"
    if dest.exists() and dest.stat().st_size>100000: return dest
    for a in range(tries):
        try:
            html=list_year(code,roc)
            fn=indiv_filename(html,yyyymm)
            if not fn: return None                        # 該期無個體檔(真的沒有)
            s=_sess()
            r=s.post(f"{BASE}/server-java/t57sb01",
                data={"step":"9","kind":"A","co_id":code,"filename":fn,"colorchg":"1"},timeout=30)
            r.encoding="big5"; mm=re.search(r"href='(/pdf/[^']+\.pdf)'",r.text)
            if not mm: return None
            dest.write_bytes(s.get(BASE+mm.group(1),timeout=60).content)
            time.sleep(0.8); return dest
        except Exception:
            time.sleep(2*(a+1))
    return None

if __name__=="__main__":
    BANKS=[("5841","中信"),("5836","富邦"),("5847","玉山"),("5835","國泰")]
    miss=[]
    for roc in range(109,114):
        for month in ("02","04"):
            for code,name in BANKS:
                p=CACHE/f"{1911+roc}{month}_{code}_AI3.pdf"
                if p.exists() and p.stat().st_size>100000: continue
                got=download(code,roc,month)
                lbl=f"{1911+roc}{'H1' if month=='02' else 'H2'}"
                print(f"{lbl} {name}: {'補回 '+got.name if got else '★ 清單無個體檔(真缺)'}")
                if not got: miss.append(f"{lbl} {name}")
    print("\n仍缺(真無檔):", miss or "無 — 全補齊")
