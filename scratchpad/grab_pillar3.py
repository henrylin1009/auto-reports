"""把第三支柱揭露檔抓下來(110H1~114H2 = 2021H1~2025H2)。一次性腳本,不是管線。

存到 pillar3_cache/{roc}{H1|H2}_{bank}.pdf,並驗內容(必須含「加權風險性資產」),
因為玉山站台會對亂猜的檔名回同一份 soft-404(HTTP 200 但內容一樣)。
"""
import re, ssl, sys, hashlib
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import pdfplumber

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}
OUT = Path("pillar3_cache"); OUT.mkdir(exist_ok=True)


class Lax(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        c = create_urllib3_context(); c.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = c; return super().init_poolmanager(*a, **kw)


S = requests.Session(); S.headers.update(UA); S.mount("https://", Lax())

# 實測確認的 URL 型態(富邦 110H2 檔名少一個底線 —— 所以清單是抄下來的,不是拼的)
URLS = {}
FB = "https://www.fubon.com/banking/document/public_info/TW/"
for roc, h1, h2 in [(110, "fubon_11006.pdf", "fubon11012.pdf"), (111, "fubon_11106.pdf", "fubon_11112.pdf"),
                    (112, "fubon_11206.pdf", "fubon_11212.pdf"), (113, "fubon_11306.pdf", "fubon_11312.pdf"),
                    (114, "fubon_11406.pdf", "fubon_11412.pdf")]:
    URLS[(roc, "H1", "富邦")] = FB + h1
    URLS[(roc, "H2", "富邦")] = FB + h2
CT = "https://www.ctbcbank.com/content/dam/twrbo/pdf/aboutctbc/"
for roc in range(110, 115):
    URLS[(roc, "H1", "中信")] = f"{CT}Analysis_Y{roc}_1st_half.pdf"
    URLS[(roc, "H2", "中信")] = f"{CT}Analysis_Y{roc}.pdf"


def verify(path):
    """回 (頁數, 是否含錨, sha1前8)。soft-404 會沒有錨。"""
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
            for pg in pdf.pages:
                if "加權風險性資產" in (pg.extract_text() or "").replace(" ", ""):
                    return n, True, hashlib.sha1(path.read_bytes()).hexdigest()[:8]
            return n, False, hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    except Exception as e:
        return 0, False, f"ERR {type(e).__name__}"


rows = []
for (roc, half, bank), url in sorted(URLS.items()):
    dest = OUT / f"{roc}{half}_{bank}.pdf"
    if not (dest.exists() and dest.stat().st_size > 100_000):
        got = None
        for a in range(3):
            try:
                r = S.get(url, timeout=90)
                if r.status_code == 200 and len(r.content) > 100_000:
                    got = r.content; break
            except Exception as e:
                print(f"  ! {bank} {roc}{half} {type(e).__name__}")
        if got is None:
            print(f"✗ {roc}{half} {bank}  抓不到  {url}"); continue
        dest.write_bytes(got)
    n, ok, h = verify(dest)
    rows.append((roc, half, bank, dest.stat().st_size, n, ok, h))
    print(f"{'✓' if ok else '✗錨'} {roc}{half} {bank:3} {dest.stat().st_size:>9,}B  {n:>3}頁  {h}")

print(f"\n共 {len(rows)} 份,有錨 {sum(1 for r in rows if r[5])} 份")
# soft-404 偵測:同一家出現重複 sha1
seen = {}
for roc, half, bank, sz, n, ok, h in rows:
    seen.setdefault((bank, h), []).append(f"{roc}{half}")
for (bank, h), v in seen.items():
    if len(v) > 1:
        print(f"⚠️ {bank} 這幾期檔案完全相同({h}): {v}  ← 疑似 soft-404")
