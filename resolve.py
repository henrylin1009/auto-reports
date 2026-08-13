"""穩健取檔:不寫死 AI3,改去 TWSE 清單找該口徑那個檔(代碼各家/各年不一,如 AI2/AI3)。
補回缺檔,並統一存成 `{YYYYMM}_{銀行名}_{口徑}.pdf` 讓下游照吃。

**兩個口徑都抓得到**(2026-08-12)。原本只抓個體 —— 但 TWSE 清單上本來就
同時標著「個體」與「合併」,`report_filename()` 的最近標籤演算法一直都算出了
兩者,只是把合併那個丟掉。丟掉的代價是合併變成一個死結:沒檔就沒欄、
沒欄就沒格可按,唯一進料口只剩拖放上傳,而且順序是反的(要先有檔,
那一欄才會長出來)。

⚠️ **這是一個取得器外掛,不是唯一入口**(2026-08-11,`docs/plan_v6_一台機器.md` R2-3)。
還有一條路:網頁「資料」頁的拖放上傳(`/api/upload`,見 `server.py`)——
使用者自己有 PDF(不管從哪裡拿到的)就能直接餵給機器,不需要 TWSE、
不需要台灣網路。這支的存在理由沒變(TWSE 擋雲端 IP,取得層仍然要在
台灣機器上跑),只是**不再是拿到 PDF 的唯一辦法**。
"""
import re, time, requests, pdfplumber
from pathlib import Path

import config
import docid

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

#: 清單上的口徑標籤 → `docid` 的口徑值。**2014 以前叫「母公司財報」,不叫「個體」**
#: —— 只認「個體」的話,2014 以前的每一期都會回 None,`acquire.fetch_one()` 就把它
#: 記成 absent(「TWSE 清單上沒有這期的個體檔」),而檔案其實一直都在。
#: 舊時代四季都申報母公司財報,比現在的個體(只有半年報/年報)還密。
#: 合併只有一個寫法,但它涵蓋「母子公司合併報表」等變體。
_TAGS = {
    docid.SOLO: ("個體", "個別", "母公司財報"),
    docid.CONSOLIDATED: ("合併",),
}

def report_filename(html, yyyymm, basis=docid.SOLO):
    """從清單找該期(YYYYMM 前綴)標為 `basis` 的檔名。

    **口徑是參數,不是寫死的**:同一套「最近標籤」判斷同時認得個體與合併,
    兩者共用一個實作 —— 分成兩支各自 rfind 是這個 repo 一再出事的形狀
    (一道規則兩個實作,改了一邊忘了另一邊)。
    """
    if basis not in _TAGS:
        raise ValueError(f"口徑 {basis!r} 不認得 —— 只有 {tuple(_TAGS)}")
    for m in re.finditer(r'readfile2\("A","\d+","('+re.escape(yyyymm)+r'_\d+_[A-Z0-9]+\.pdf)"\)', html):
        fn=m.group(1)
        win=html[max(0,m.start()-600):m.start()]          # 該檔連結前的列描述
        # **取最近的那個標籤,不是「窗口裡有沒有」** —— 600 字窗口會跨到上一列:
        # 實測 201202_5843_A02(合併)的窗口裡,距離 514 字處就有上一列的
        # 「母公司財報」,而它自己的「合併」在 63 字處。用 `in` 判斷會把合併
        # 報表當成個體收下來,是靜默抓錯口徑的檔。
        best, kind = None, None
        for b, tags in _TAGS.items():
            for t in tags:
                i = win.rfind(t)
                if i >= 0 and (best is None or i > best):
                    best, kind = i, b
        if kind == basis:
            return fn
    return None

def download(code, roc, month, tries=4, basis=docid.SOLO):
    """回傳該口徑的 PDF 路徑。自動解析 TWSE 的原始檔名代碼。

    存檔名走 `docid.make(..., basis)`,而 `basis` 也就是 `report_filename()`
    去清單上比對的那個標籤 —— 檔名上的口徑因此**是問出來的,不是猜的**:
    抓下來的一定是清單標著那個口徑的那一列。(封面仍是最終權威,見 `docid.py`;
    這裡保證的是「沒有抓錯列」,不是「封面一定同意」。)
    """
    yyyymm=f"{1911+roc}{month}"
    bank=config.BANKS.get(code)
    if not bank:
        raise ValueError(f"代碼 {code} 不在 config.BANKS —— 要抓新銀行請先加進設定")
    dest=CACHE/f"{docid.make(yyyymm, bank, basis)}.pdf"
    if dest.exists() and dest.stat().st_size>100000: return dest
    for a in range(tries):
        try:
            html=list_year(code,roc)
            fn=report_filename(html,yyyymm,basis)
            if not fn: return None                        # 該期無此口徑的檔(真的沒有)
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
    # 銀行清單只有一份(`config.BANKS`)—— 這裡原本自己列了四家(還漏了兆豐)。
    miss=[]
    for roc in range(109,114):
        for month in ("02","04"):
            for code,name in sorted(config.BANKS.items()):
                p=CACHE/f"{docid.make(f'{1911+roc}{month}', name, docid.SOLO)}.pdf"
                if p.exists() and p.stat().st_size>100000: continue
                got=download(code,roc,month)
                lbl=f"{1911+roc}{'H1' if month=='02' else 'H2'}"
                print(f"{lbl} {name}: {'補回 '+got.name if got else '★ 清單無個體檔(真缺)'}")
                if not got: miss.append(f"{lbl} {name}")
    print("\n仍缺(真無檔):", miss or "無 — 全補齊")
