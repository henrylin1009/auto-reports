"""三分類(Trading/OCI/AC)債種明細提取 — 4 家彙總銀行。
兆豐另以變動明細表(座標)處理,不在此檔。
"""
import re, pdfplumber
from pathlib import Path
CACHE = Path("pdf_cache")

def full_text(code, roc=113, month="02"):
    p = CACHE / f"{1911+roc}{month}_{code}_AI3.pdf"
    return "\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)

def norm(s): return re.sub(r"\s+", "", s)
def to_num(s):
    s=s.replace(",","").strip()
    if s=="-": return 0
    neg=s.startswith("(") and s.endswith(")"); s=s.strip("()").strip()
    return (-int(s) if neg else int(s)) if s.isdigit() else None

# 品名同義字 -> 標準名
SYN = {
    "金融債":"金融債券", "資產基礎債券":"資產基礎證券", "可轉讓定存單":"可轉讓定期存單",
    "上市（櫃）股票":"股票", "股票投資":"股票", "基金受益憑證":"受益憑證",
    "政府債券":"政府公債",   # 舊年度(如2020)用「政府債券」舊稱
}
def canon(name):
    name = norm(name)
    return SYN.get(name, name)

# 每分類的錨點。itemized 表特徵:錨點後 <200 字內先出現「日期列」,再接債種明細。
import extract2 as _E2   # Trading 沿用已驗證的 summary 解析器
ANCHORS = {   # 債務工具投資 優先(富邦/玉山),金融資產 後備(中信),裸債務工具投資(國泰跨頁子表)
    "OCI":     [r"透過其他綜合損益按公允價值衡量之債務工具投資",
                r"透過其他綜合損益按公允價值衡量之金融資產",
                r"債務工具投資"],
    "AC":      [r"按攤銷後成本衡量之債務工具投資"],
}
# 日期列:支援「113年6月30日」與「114.6.30」兩種
DATEROW = re.compile(r"\d{2,3}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{3}\.\d{1,2}\.\d{1,2}")
STOP = re.compile(r"^(小計|合計|外匯|利率交換|遠期外匯|選擇權|換匯|衍生|持有供交易|指定|減：|上述|本行|本公司|透過(其他綜合)?損益|按攤銷後成本|附註|於|D\.|\(一\)|\(二\))")
EQUITY = ("股票","上市","未上市","REITs","權益","國內上市","國外股票","興櫃")
CONFIRM = ("政府公債","公司債","金融債","短期票券","商業本票","央行票據")

def _strip(name):
    name = re.sub(r"（[^）]*）", "", name)   # 去 (附註X)
    return name

DEBT_NAMES = ("政府公債","公司債","金融債券","資產基礎證券","國庫券","短期票券","可轉讓定期存單","央行票據")

def _parse_block(seg, want_subtotal=False):
    items={}; subtotal=None
    for ln in seg.splitlines():
        ln=ln.strip()
        if not ln: continue
        if STOP.match(norm(_strip(ln))) and items:
            sm=re.search(r"(小計|合計|小 計|合 計)\s*\$?\s*(\(?[\d,]{3,}\)?)", ln)
            if sm: subtotal=to_num(sm.group(2)); break
            if norm(_strip(ln)).startswith("減："):
                continue                       # 備抵損失行,續找後面的合計
            break
        nm=re.match(r"^([一-鿿（）()\s]+?)\s*\$?\s*(-|\(?[\d,]{3,}\)?)", ln)
        if nm:
            name=canon(_strip(nm.group(1))); val=to_num(nm.group(2))
            if not items and any(e in name for e in EQUITY):
                return ({}, None) if want_subtotal else {}
            if val is not None and name not in items and 2<=len(name)<=10:
                items[name]=val
    return (items, subtotal) if want_subtotal else items

NOTE = re.compile(r"[（(][一二三四五六七八九十]+[)）]\s*$|[一二三四五六七八九十]+、\s*$")

def _collect(text, cls):
    """OCI/AC:蒐集候選,回傳勝出者 (items, subtotal)。"""
    cands=[]
    for anchor in ANCHORS[cls]:
        for m in re.finditer(anchor, text):
            if cls=="OCI" and "攤銷後成本" in text[max(0,m.start()-15):m.start()]:
                continue
            head = text[m.end():m.end()+200]
            dm = DATEROW.search(head)
            # 日期列僅在「緊貼錨點(35字內)」時當表頭跳過;否則是分頁重複列,不可跳(會漏前半債種)
            base = m.end()+dm.end() if (dm and dm.start()<35) else m.end()
            if cls=="OCI" and "攤銷後成本" in text[m.end():max(base, m.end()+300)]:
                continue                       # 錨點後隨即出現 AC 標題 → 這段其實是 AC 表
            seg = text[base:base+2200]         # 加大:吸收跨頁(接次頁/承前頁)切斷的表
            if "面額" in seg[:300] or "取得成本" in seg[:300]:
                continue
            if sum(c in seg for c in CONFIRM) < 2:
                continue
            items, sub = _parse_block(seg, want_subtotal=True)
            ndebt=sum(1 for k in items if k in DEBT_NAMES)
            if ndebt>=2:
                is_note = bool(NOTE.search(text[max(0,m.start()-8):m.start()]))
                recon = sub is not None and abs(sum(items.values())-sub) <= max(100,0.005*sub)
                cands.append((recon, is_note, ndebt, sum(items.values()), items, sub))
    if not cands:
        return {}, None
    # 優先:能對上自己小計(reconcile)的候選 → 再看附註編號、債種數、總額
    best=max(cands, key=lambda c:(c[0], c[1], c[2], c[3]))
    return best[4], best[5]

def _trading_subtotal(text):
    """Trading checksum 基準:
    (1) 有純證券『小計』→ 直接用(富邦/國泰)。
    (2) 否則用『合計 − 衍生金融資產 − 金融資產評價調整』(中信型)。
    """
    for m in re.finditer(r"強制透過損益按公允價值", text):
        seg=text[m.end():m.end()+1400]
        if "商業本票" not in seg[:600]:
            continue
        sm=re.search(r"(小計|小 計)\s*\$?\s*(\(?[\d,]{3,}\)?)", seg)
        if sm:
            return to_num(sm.group(2))
        def num(pat):
            r=re.search(pat+r"\s*\$?\s*([\d,]{3,})", seg); return to_num(r.group(1)) if r else None
        tot=num(r"合\s*計"); dv=num("衍生金融資產"); adj=num("金融資產評價調整")
        if tot is not None:
            return tot-(dv or 0)-(adj or 0)
    return None

def parse_class(text, cls):
    if cls == "Trading":
        return {canon(k): v for k, v in _E2.parse_summary_trading(text).items()}
    return _collect(text, cls)[0]

def _fulltable_ok(seg):
    """通用整表對帳:整張表所有明細(含衍生)加總 == 報表印的總額(無標籤的 $ 行或小/合計)。
    整表對得起來 → 代表每個數字都讀對 → 債券子集可信。回傳 (ok, total)。"""
    leaves=0; total=None
    for ln in seg.splitlines():
        s=ln.strip()
        if not s: continue
        if re.match(r"^\$\s*[\d,(]", s):                      # 無品名、以 $ 起頭 = 總額行
            total=to_num(re.match(r"^\$\s*(\(?[\d,]+\)?)", s).group(1)); break
        if norm(_strip(s)).startswith(("小計","合計")):
            mm=re.search(r"([\d,]{3,})", s); total=to_num(mm.group(1)) if mm else None; break
        nm=re.match(r"^([一-鿿（）()\s]+?)\s*\$?\s*(-|\(?[\d,]{3,}\)?)", s)
        if nm:
            v=to_num(nm.group(2))
            if v is not None: leaves+=v
    if total is None: return False, None
    return abs(leaves-total) <= max(100, 0.005*total), total

def checksum(text, cls):
    """回傳 (items, subtotal, ok)。三層驗算:純證券小計 → 中信式(合計−衍生−評價) → 通用整表對帳。"""
    if cls == "Trading":
        it = parse_class(text, cls); st = _trading_subtotal(text)
        anchor_pat=r"強制透過損益按公允價值"
    else:
        it, st = _collect(text, cls)
        anchor_pat=ANCHORS[cls][0]
    tol = max(100, 0.005*st) if st else 0
    ok = bool(it) and st is not None and abs(sum(it.values())-st) <= tol
    if it and not ok:                                        # 前兩招沒過 → 整表對帳
        for m in re.finditer(anchor_pat, text):
            seg=text[m.end():m.end()+1600]
            if sum(c in seg for c in CONFIRM) >= 2 and "面額" not in seg[:300]:
                fok, ft = _fulltable_ok(seg)
                if fok: return it, ft, True
    return it, st, ok

# 債種桶(億元)
def bond_buckets(items):
    g=lambda *k: sum(items.get(x,0) for x in k)/1e5
    return {
        "公債":   g("政府公債"),
        # 貨幣市場/短:國庫券 + 兆豐的央行定期存單/短期票券 + 央行票據
        "國庫券": g("國庫券","央行定期存單","短期票券","央行票據","央行可轉讓定期存單"),
        "公司債": g("公司債","公司債券"),          # 兆豐用「公司債券」
        "金融債": g("金融債券","金融債"),
        "資產基礎": g("資產基礎證券"),
        "可轉讓定存單": g("可轉讓定期存單","定存單"),
        "其他":   g("其他","其他證券及債券","其他債券","國外機構發行債券"),
    }

BANKS=[("5841","中信"),("5836","富邦"),("5847","玉山"),("5835","國泰")]
if __name__=="__main__":
    for cls in ["Trading","OCI","AC"]:
        print(f"\n{'='*78}\n【{cls}】各家債種 (億元) — 2024H1\n{'='*78}")
        print(f"{'銀行':<6}{'公債':>8}{'公司債':>8}{'金融債':>8}{'資產基礎':>9}{'國庫券':>8}{'定存單':>8}{'其他':>8}")
        for code,name in BANKS:
            it=parse_class(full_text(code),cls)
            b=bond_buckets(it)
            print(f"{name:<6}{b['公債']:>8,.0f}{b['公司債']:>8,.0f}{b['金融債']:>8,.0f}"
                  f"{b['資產基礎']:>9,.0f}{b['國庫券']:>8,.0f}{b['可轉讓定存單']:>8,.0f}{b['其他']:>8,.0f}")
