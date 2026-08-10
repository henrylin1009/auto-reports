"""第二輪探測:國泰連結文字對期別、兆豐表在哪、中信/玉山正確入口。"""
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
        print(f"  ! {type(e).__name__}: {str(e)[:80]}"); return None


def strip(s):
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", H.unescape(s)))


print("="*74, "\n【國泰】連結文字 → URL")
r = get("https://www.cathaybk.com.tw/cathaybk/about/about/announcement/announce-risk/")
if r:
    n = 0
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        t = strip(m.group(2))
        if any(k in t for k in ("資本適足", "揭露", "風險管理")):
            print(f"  {t[:44]:46} {up.urljoin(r.url, m.group(1))[:95]}")
            n += 1
    print(f"  → 命中 {n} 個")
    if n == 0:                                  # 退路:看連結周邊文字
        for m in list(re.finditer(r'\.pdf', r.text))[:3]:
            print("  周邊:", strip(r.text[max(0, m.start()-260):m.start()+60])[:220])

print("\n" + "="*74, "\n【兆豐】表在網頁裡嗎")
r = get("https://www.megabank.com.tw/about/announcement/news/regulatory-disclosures/capital-adquacy")
if r:
    for probe in ["360,019,689", "加權風險性資產", "普通股權益", "槓桿比率"]:
        print(f"  「{probe}」出現 {r.text.count(probe)} 次")
    i = r.text.find("加權風險性資產")
    if i > 0:
        print("  ---- 命中處前後 ----")
        print("  " + strip(r.text[max(0, i-900):i+700])[:900])
    else:
        for m in re.finditer(r'(?:data-|href=|src=)["\']([^"\']*(?:api|json|ajax|list|query)[^"\']*)["\']', r.text, re.I):
            print("  候選端點:", m.group(1)[:120])

print("\n" + "="*74, "\n【中信】找入口")
for u in ["https://www.ctbcbank.com/twrbo/zh_tw/index.html",
          "https://www.ctbcbank.com/content/dam/twrbo/pdf/aboutctbc/Analysis_Y114.pdf",
          "https://www.ctbcbank.com/content/dam/twrbo/pdf/aboutctbc/Analysis_Y113.pdf"]:
    r = get(u)
    print(f"  {u[-58:]:60} {'HTTP '+str(r.status_code)+' '+format(len(r.content),',')+'B' if r else '✗'}")

print("\n" + "="*74, "\n【玉山】找入口")
for u in ["https://www.esunbank.com/zh-tw/about/information-disclosure/capital-adequacy",
          "https://www.esunbank.com/zh-tw/-/media/ESUNBANK/Files/about/Report/1131231mensurable.pdf",
          "https://www.esunbank.com/zh-tw/-/media/ESUNBANK/Files/about/Report/1081231mensurable_V3.pdf"]:
    r = get(u)
    print(f"  {u[-58:]:60} {'HTTP '+str(r.status_code)+' '+format(len(r.content),',')+'B' if r else '✗'}")
