"""探測五家「資本適足性與風險管理專區」的連結結構(只讀不存)。

⚠️ Python 3.13+ 的 ssl.create_default_context 預設開 VERIFY_X509_STRICT,
多家台灣銀行的憑證鏈缺 Subject Key Identifier 會被擋。關掉「嚴格 RFC5280 一致性」
即可,**憑證鏈與主機名仍然照驗**(不是 verify=False)。
"""
import re, ssl, sys, urllib.parse as up
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}


class LaxSKIAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)


def sess():
    s = requests.Session()
    s.headers.update(UA)
    s.mount("https://", LaxSKIAdapter())
    return s


def get(s, url, tries=3):
    for a in range(tries):
        try:
            r = s.get(url, timeout=40)
            if len(r.content) > 800:
                return r
            print(f"    · 回應過短 {len(r.content)}B,重試")
        except Exception as e:
            print(f"    ! {type(e).__name__}: {str(e)[:90]}")
    return None


PAGES = {
    "富邦": "https://www.fubon.com/banking/public_info/public_info_bank_05.htm",
    "國泰": "https://www.cathaybk.com.tw/cathaybk/about/about/announcement/announce-risk/",
    "兆豐": "https://www.megabank.com.tw/about/announcement/news/regulatory-disclosures/capital-adquacy",
    "中信": "https://www.ctbcbank.com/twrbo/zh_tw/aboutctbc/ab_capital/ab_ca_disclosure.html",
    "玉山": "https://www.esunbank.com/zh-tw/about/investor-relations/financial-information/capital-adequacy",
}

if len(sys.argv) > 1:                      # 允許只跑指定銀行 / 指定 URL
    PAGES = {sys.argv[1]: sys.argv[2]} if len(sys.argv) > 2 else \
            {k: v for k, v in PAGES.items() if k in sys.argv[1:]}

s = sess()
for bank, url in PAGES.items():
    print(f"\n{'='*74}\n{bank}  {url}")
    r = get(s, url)
    if r is None:
        print("  ✗ 抓不到"); continue
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    print(f"  HTTP {r.status_code}  {len(r.content):,} B")
    pdfs = list(dict.fromkeys(re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)))
    print(f"  PDF 連結 {len(pdfs)} 個:")
    for p in pdfs[:16]:
        print("   ", up.urljoin(url, p)[:135])
    if len(pdfs) > 16:
        print(f"    ... 另 {len(pdfs)-16} 個")
    yrs = sorted(set(re.findall(r'(1[01][0-9])\s*年', html)), reverse=True)
    print(f"  民國年: {yrs[:12]}   「資本適足」×{html.count('資本適足')}"
          f"  「上半年」×{html.count('上半年')}  「附表」×{html.count('附表')}")
