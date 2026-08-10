"""第三輪:兆豐子頁內容、中信/玉山上半年檔名、國泰期別標籤。"""
import re, ssl, html as H, urllib.parse as up
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}


class Lax(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        c = create_urllib3_context(); c.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = c; return super().init_poolmanager(*a, **kw)


S = requests.Session(); S.headers.update(UA); S.mount("https://", Lax())


def get(u):
    try:
        r = S.get(u, timeout=40); r.encoding = r.apparent_encoding or "utf-8"; return r
    except Exception as e:
        return None


def strip(s):
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", H.unescape(s)))


print("="*74, "\n【兆豐】子頁 114h2 內容")
r = get("https://www.megabank.com.tw/about/announcement/news/regulatory-disclosures/capital-adquacy/114h2")
if r:
    print(f"  HTTP {r.status_code}  {len(r.content):,}B")
    for p in ["加權風險性資產", "360,019,689", "槓桿比率", "普通股權益"]:
        print(f"    「{p}」×{r.text.count(p)}")
    i = r.text.find("加權風險性資產")
    if i > 0:
        print("  ---- 表身節錄 ----")
        print(strip(r.text[max(0, i-1500):i+1200])[:1400])

print("\n" + "="*74, "\n【中信】上半年檔名型態")
for roc in (114, 113):
    for suf in ["", "_1st_half", "_1H", "_first_half"]:
        u = f"https://www.ctbcbank.com/content/dam/twrbo/pdf/aboutctbc/Analysis_Y{roc}{suf}.pdf"
        r = get(u)
        print(f"  Analysis_Y{roc}{suf:12}.pdf  {'HTTP '+str(r.status_code)+'  '+format(len(r.content),',')+'B' if r and r.status_code==200 else '✗'}")

print("\n" + "="*74, "\n【玉山】上半年檔名型態")
for roc in (114, 113):
    for mmdd, suf in [("0630", ""), ("1231", ""), ("0630", "_V2"), ("1231", "_V2")]:
        u = f"https://www.esunbank.com/zh-tw/-/media/ESUNBANK/Files/about/Report/{roc}{mmdd}mensurable{suf}.pdf"
        r = get(u)
        ok = r and r.status_code == 200 and len(r.content) > 50000
        print(f"  {roc}{mmdd}mensurable{suf:4}.pdf  {'HTTP '+str(r.status_code)+'  '+format(len(r.content),',')+'B' if ok else '✗'}")

print("\n" + "="*74, "\n【國泰】期別標籤(看連結所在的區塊)")
r = get("https://www.cathaybk.com.tw/cathaybk/about/about/announcement/announce-risk/")
if r:
    for m in list(re.finditer(r'href="(/cathaybk/-/media/[0-9a-f]{32}\.pdf[^"]*)"', r.text))[:6]:
        ctx = strip(r.text[max(0, m.start()-700):m.start()+400])
        ctx = re.sub(r"\s{2,}", " | ", ctx).strip()
        print(f"\n  {m.group(1)[:70]}\n    …{ctx[-320:]}")
