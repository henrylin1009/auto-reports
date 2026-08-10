"""找四家的【附表五十一】銀行簿利率風險,看有沒有印數值(經濟價值/NII 佔比)。

富邦已查:只有定性,不印數值。這支查中信/國泰/兆豐/玉山。
"""
import io, re, ssl, sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import pdfplumber

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}


class Lax(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        c = create_urllib3_context(); c.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = c; return super().init_poolmanager(*a, **kw)


S = requests.Session(); S.headers.update(UA); S.mount("https://", Lax())

CAND = {
    "中信 114年報揭露": "https://www.ctbcbank.com/content/dam/twrbo/pdf/aboutctbc/Analysis_Y114.pdf",
    "國泰 114下半":     "https://www.cathaybk.com.tw/cathaybk/-/media/9f0179e8d0684f7aa826fdd1cb89ff5e.pdf",
    "國泰 114上半":     "https://www.cathaybk.com.tw/cathaybk/-/media/0ee9aaec8f55477dab62bf7604f4f950.pdf",
    "玉山 108(已知真檔)": "https://www.esunbank.com/zh-tw/-/media/ESUNBANK/Files/about/Report/1081231mensurable_V3.pdf",
}
# 兆豐:分章節 PDF, wwwfile.megabank.com.tw/upload/F330/{roc}Q{n}_{nn}_{章節}.pdf
for nn in ("04", "10", "11", "12", "13"):
    CAND[f"兆豐 114Q4_{nn}"] = f"https://wwwfile.megabank.com.tw/upload/F330/114Q4_{nn}_%E8%B3%87%E6%9C%AC%E9%81%A9%E8%B6%B3%E6%80%A7.pdf"

KEY = ["銀行簿利率風險", "經濟價值", "淨利息收入", "第一類資本之比率", "附表五十一"]
NUM = re.compile(r"\d+\.\d+\s*%|\d+\.\d+")

seen = {}
for name, url in CAND.items():
    try:
        r = S.get(url, timeout=90)
    except Exception as e:
        print(f"\n{name:22} ✗ {type(e).__name__}"); continue
    n = len(r.content)
    if r.status_code != 200 or n < 60000 or not r.content[:5].startswith(b"%PDF"):
        print(f"\n{name:22} ✗ HTTP {r.status_code} {n:,}B (非PDF或太小)"); continue
    if n in seen:
        print(f"\n{name:22} ⚠ 與『{seen[n]}』同大小 {n:,}B —— 疑似 soft-404"); continue
    seen[n] = name
    print(f"\n{name:22} ✓ {n:,}B")
    try:
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = [(i + 1, (p.extract_text() or "").replace(" ", "")) for i, p in enumerate(pdf.pages)]
            print(f"   {len(pages)} 頁,文字層空白 {sum(1 for _,t in pages if not t)} 頁")
            for k in KEY:
                hit = [i for i, t in pages if k in t]
                print(f"     「{k}」→ p{hit[:8]}{'...' if len(hit)>8 else ''} ({len(hit)})")
            tgt = [i for i, t in pages if "銀行簿利率風險" in t and ("經濟價值" in t or "第一類資本之比率" in t)]
            for pg in tgt[:2]:
                txt = pages[pg-1][1]
                print(f"   ===== p{pg} 節錄 =====")
                print("   " + txt[:900].replace("\n", "\n   "))
    except Exception as e:
        print(f"   ! 解析失敗 {type(e).__name__}: {str(e)[:80]}")
