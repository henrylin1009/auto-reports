"""獲利面(粗估 NIM / 資金成本)抽取器 — 5 家個體損益表 + 資產負債表。
一期原型:FY2025(民國114/12/31,全年,免年化)。單位:千元 → 輸出億元。
所有指標標「粗估」:以資產總計近似生息資產,計息負債=存款+同業+應付債券。
"""
import re, json, pdfplumber
from pathlib import Path

CACHE = Path("pdf_cache")
BANKS = [("5841","中信"),("5843","兆豐"),("5835","國泰"),("5836","富邦"),("5847","玉山")]

def full_text(code, period="202504"):
    p = CACHE / f"{period}_{code}_AI3.pdf"
    return "\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)

def _first_num(t, kw, minlen=6):
    """關鍵字後同一行第一個大數(略過附註編號)。"""
    for m in re.finditer(kw, t):
        line = t[m.start()+len(kw): t.find("\n", m.start())]
        nums = re.findall(r"[\d,]{%d,}" % minlen, line)
        if nums:
            return int(nums[0].replace(",", ""))
    return None

def _max_num(t, kws, lo=None, hi=None):
    """多個錨點取符合區間的最大值(避開前段小entity報表)。"""
    best = None
    for kw in kws:
        for m in re.finditer(kw, t):
            line = t[m.start(): t.find("\n", m.start())]
            for n in re.findall(r"[\d,]{9,}", line):
                v = int(n.replace(",", ""))
                if (lo is None or v >= lo) and (hi is None or v <= hi):
                    best = v if best is None else max(best, v)
    return best

def extract_one(code, name):
    t = full_text(code)
    ii = _first_num(t, "利息收入")
    ie = _first_num(t, "利息費用")
    ni = _first_num(t, "利息淨收益")
    # 資產總計:五家標籤不一(總計/合計/負債及權益總計),取兆級最大值
    ta = _max_num(t, [r"資\s*產\s*總\s*計", r"資\s*產\s*合\s*計", r"負\s*債\s*及\s*權\s*益\s*總\s*計"],
                  lo=int(3e9))
    dep  = _first_num(t, "存款及匯款", 9)
    intb = _max_num(t, ["央行及銀行同業存款"], lo=int(1e7))
    return dict(bank=name, code=code,
                利息收入=ii, 利息費用=ie, 利息淨收益=ni,
                資產總計=ta, 存款及匯款=dep, 同業存款=intb)

def compute(r):
    K = 1e5  # 千元 -> 億元
    to = lambda v: round(v/K, 1) if v else None
    ni, ii, ie, ta = r["利息淨收益"], r["利息收入"], r["利息費用"], r["資產總計"]
    liab = (r["存款及匯款"] or 0) + (r["同業存款"] or 0)
    nim  = round(100*ni/ta, 2) if (ni and ta) else None       # 粗估淨利差 %(÷總資產)
    ayld = round(100*ii/ta, 2) if (ii and ta) else None       # 資產收益率 %(÷總資產)
    exta = round(100*ie/ta, 2) if (ie and ta) else None       # 利息費用占資產 %(可加:ayld=exta+nim)
    cost = round(100*ie/liab, 2) if (ie and liab) else None   # 資金成本率 %(÷計息負債,慣用口徑)
    recon = (ni and ii and ie and abs(ni-(ii-ie)) <= 0.01*ii)
    return dict(bank=r["bank"], 利息收入億=to(ii), 利息費用億=to(ie), 利息淨收益億=to(ni),
                資產總計億=to(ta), 計息負債億=to(liab),
                粗估NIM=nim, 資產收益率=ayld, 費用占資產=exta, 資金成本率=cost, 對帳ok=bool(recon))

def main():
    rows = [compute(extract_one(c, n)) for c, n in BANKS]
    print(f"{'銀行':<6}{'NIM%':>7}{'資產收益%':>9}{'資金成本%':>9}{'淨收益億':>9}{'資產兆':>8}  對帳")
    for r in rows:
        ta = (r['資產總計億']/1e4) if r['資產總計億'] else 0
        print(f"{r['bank']:<6}{str(r['粗估NIM']):>7}{str(r['資產收益率']):>9}"
              f"{str(r['資金成本率']):>9}{str(r['利息淨收益億']):>9}{ta:>8.2f}  {'✓' if r['對帳ok'] else '✗'}")
    Path("pnl.json").write_text(json.dumps({"period":"FY2025","rows":rows},
                                ensure_ascii=False, indent=2))
    print("\n-> pnl.json")

if __name__ == "__main__":
    main()
