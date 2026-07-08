"""五家銀行債券投資自動化提取 (WIP)。
格式分三類:summary(中信/富邦/玉山)、cathay-detail(國泰)、mega-table(兆豐)。
本檔先實作 summary 解析器並對 email 目標值驗證。
"""
import re
import pdfplumber
from pathlib import Path

CACHE = Path("pdf_cache")

def full_text(code, roc=113, month="02"):
    p = CACHE / f"{1911+roc}{month}_{code}_AI3.pdf"
    return "\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)

def norm(s):                      # 去全形/半形空白
    return re.sub(r"\s+", "", s)

def to_num(s):
    s = s.replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    return (-int(s) if neg else int(s)) if s.isdigit() else None

# summary 格式:在「強制透過損益…」節內讀 商品名 + 第一個數字。
# 錨點取折行前的字首;必要條件:區塊內含「商業本票」(交易簿指標) 或 政府公債+公司債。
STOP = re.compile(r"^(小\s*計|合\s*計|外匯|利率交換|遠期外匯|選擇權|換匯|衍生|持有供交易|透過(其他綜合)?損益|指定)")
def parse_summary_trading(text):
    anchors = [r"強制透過損益按公允價值",
               r"透過損益按公允價值衡量之金融資產"]
    for anchor in anchors:
        for m in re.finditer(anchor, text):
            seg = text[m.end():m.end()+1400]
            if "面額" in seg[:400] or "到期日" in seg[:400]:   # 逐檔明細,跳過
                continue
            if "商業本票" not in seg and not ("政府公債" in seg and "公司債" in seg):
                continue
            items = {}
            for ln in seg.splitlines()[1:]:      # 跳過錨點殘尾那行
                ln = ln.strip()
                if not ln:
                    continue
                if STOP.match(norm(ln)) and items:
                    return items
                nm = re.match(r"^([一-鿿（）()\s]+?)\s*\$?\s*(-|[\d,]{3,})", ln)
                if nm:
                    name = norm(nm.group(1))
                    val = 0 if nm.group(2) == "-" else to_num(nm.group(2))
                    if val is not None and name not in items and 2 <= len(name) <= 9:
                        items[name] = val
            if items:
                return items
    return {}

# 目標桶
def buckets(items):
    cp = sum(items.get(k, 0) for k in ("商業本票", "可轉讓定期存單", "可轉讓定存單", "國庫券", "承兌匯票", "銀行承兌匯票"))
    gb = items.get("政府公債", 0) + items.get("政府債券", 0)
    return cp, gb

TARGET = {  # email 2024H1 目標 (億): (CP+NCD+BA, GB)
    "5841": ("中信", 2918, 14),
    "5836": ("富邦", 856, 36),
    "5847": ("玉山", 1288, None),
}

if __name__ == "__main__":
    for code, (name, tcp, tgb) in TARGET.items():
        t = full_text(code)
        items = parse_summary_trading(t)
        cp, gb = buckets(items)
        print(f"\n{name}({code})  抽到商品: {items}")
        mk = lambda got, tgt: "✅" if tgt is not None and round(got/1e5)==tgt else ("?" if tgt is None else "❌")
        print(f"   CP+NCD+BA = {cp/1e5:>6,.0f} 億 (目標 {tcp}) {mk(cp,tcp)}"
              f"   GB = {gb/1e5:>5,.0f} 億 (目標 {tgb}) {mk(gb,tgb)}")
