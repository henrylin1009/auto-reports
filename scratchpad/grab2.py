"""抓兆豐/國泰/玉山 110H1~114H2。URL 是瀏覽器逐一挖出來的,不是拼的。

⚠️ 玉山檔名與標籤對不上(「113年度上半年」的檔叫 113H2mensurable.pdf),
所以期別一律**以 PDF 內容印的基準日為準**,檔名只當識別碼。
"""
import ssl, hashlib
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

CB = "https://www.cathaybk.com.tw/cathaybk/-/media/"
ES = "https://www.esunbank.com/zh-tw/-/media/ESUNBANK/Files/about/Report/"
MG = "https://www.megabank.com.tw/-/media/mega/files/bank/about/announcement/legal-disclosure/capital-adquacy/"

URLS = {}
for k, g in {"114H2": "9f0179e8d0684f7aa826fdd1cb89ff5e", "114H1": "0ee9aaec8f55477dab62bf7604f4f950",
             "113H2": "318e08b031dc45998c38410cb46fe09d", "113H1": "189d6ae8ffc14e44ade0ca21a940eb66",
             "112H2": "6841e50e3afd437788983a98b1b2b629", "112H1": "2cbdf15d52a24df796181ebf33130383",
             "111H2": "98b203cc18d249199f34eacfa0d48436", "111H1": "6184905311934163bbf6eec656bfe452",
             "110H2": "7f1c1bcceeba4915b8f1cdf23107c204", "110H1": "f1f192a0b1cc4f41988bb19a68d39656"}.items():
    URLS[(k, "國泰")] = f"{CB}{g}.pdf?sc_lang=en"

# 玉山:key 用頁面標籤(H1=上半年、H2=全年度),檔名混亂故照抄
for k, f in {"114H2": "114mensurable2.pdf", "114H1": "114mensurable.pdf",
             "113H2": "113mensurable.pdf", "113H1": "113H2mensurable.pdf",
             "112H2": "112H2mensurable.pdf", "112H1": "112mensurable.pdf",
             "111H2": "1111231mensurable0529.pdf", "111H1": "111mensurable.pdf",
             "110H2": "1101231mensurable_new.pdf", "110H1": "110mensurable_v3_new.pdf"}.items():
    URLS[(k, "玉山")] = ES + f

for roc in range(110, 115):                      # 兆豐:每張附表獨立 PDF,02 = 資本適足比率
    for h in (1, 2):
        URLS[(f"{roc}H{h}", "兆豐")] = f"{MG}{roc+1911}/h{h}/02.pdf"


def probe(path):
    """回 (頁數, 有錨, 印出的基準日字串)。"""
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages); dates = []; ok = False
            for pg in pdf.pages[:60]:
                t = (pg.extract_text() or "")
                if "加權風險性資產" in t.replace(" ", ""):
                    ok = True
                    import re
                    dates += re.findall(r"1[01][0-9]\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", t)
                    if dates: break
            return n, ok, (dates[0].replace(" ", "") if dates else "?")
    except Exception as e:
        return 0, False, f"ERR {type(e).__name__}"


rows = []
for (per, bank), url in sorted(URLS.items()):
    dest = OUT / f"{per}_{bank}.pdf"
    if not (dest.exists() and dest.stat().st_size > 20_000):
        got = None
        for a in range(3):
            try:
                r = S.get(url, timeout=90)
                if r.status_code == 200 and len(r.content) > 20_000:
                    got = r.content; break
            except Exception as e:
                pass
        if got is None:
            print(f"✗ {per} {bank}  抓不到  {url[:100]}"); continue
        dest.write_bytes(got)
    n, ok, d = probe(dest)
    h = hashlib.sha1(dest.read_bytes()).hexdigest()[:8]
    rows.append((per, bank, dest.stat().st_size, n, ok, d, h))
    print(f"{'✓' if ok else '✗錨'} {per} {bank:3} {dest.stat().st_size:>9,}B {n:>4}頁  基準日={d:14} {h}")

print(f"\n共 {len(rows)} 份,有錨 {sum(1 for r in rows if r[4])} 份")
seen = {}
for per, bank, sz, n, ok, d, h in rows:
    seen.setdefault((bank, h), []).append(per)
for (bank, h), v in seen.items():
    if len(v) > 1:
        print(f"⚠️ {bank} 檔案完全相同({h}): {v}  ← soft-404")
