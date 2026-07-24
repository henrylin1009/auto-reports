"""
POC: 從公開資訊觀測站 (doc.twse.com.tw) 抓銀行合併財報 PDF,
抽出「債券投資」三種會計分類的商品別期末餘額。

  分類          附註      內容
  Trading(FVTPL)  六(三)  透過損益按公允價值衡量之金融資產
  OCI(FVOCI)      六(四)  透過其他綜合損益按公允價值衡量之金融資產
  AC(攤銷後成本)   六(五)  按攤銷後成本衡量之債務工具投資

用法:  python3 poc_extract.py            # 預設 5841 / 2025H1
"""
import re
import sys
import time
from pathlib import Path

import requests
import pdfplumber

DOC_BASE = "https://doc.twse.com.tw"
CACHE = Path(__file__).parent / "pdf_cache"
CACHE.mkdir(exist_ok=True)

# 期別 -> 檔名月份碼:  H1 = 02(半年報 6/30) ,  H2 = 04(年報 12/31)
PERIOD_MONTH = {"H1": "02", "H2": "04"}


def download(code: str, roc_year: int, period: str) -> Path:
    """下載合併個別報告 (AI1)。回傳本機 PDF 路徑,已存在則用快取。"""
    month = PERIOD_MONTH[period]
    # AI3 = 個體財報(銀行本體,不含子公司);AI1 = 合併。此分析用個體。
    filename = f"{1911 + roc_year}{month}_{code}_AI3.pdf"  # 檔名用西元年
    dest = CACHE / filename
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest

    s = requests.Session()
    # step 9: 送出後回一段 HTML,內含臨時 pdf 連結
    r = s.post(
        f"{DOC_BASE}/server-java/t57sb01",
        data={"step": "9", "kind": "A", "co_id": code,
              "filename": filename, "colorchg": "1"},
        timeout=30,
    )
    r.encoding = "big5"
    m = re.search(r"href='(/pdf/[^']+\.pdf)'", r.text)
    if not m:
        raise RuntimeError(f"找不到 PDF 連結: {code} {roc_year}{period}\n{r.text[:400]}")
    pdf = s.get(DOC_BASE + m.group(1), timeout=60)
    dest.write_bytes(pdf.content)
    return dest


# --- 目標三個附註的錨點與所屬分類 ---
NOTES = [
    ("Trading", r"透過損益按公允價值衡量之金融(?:工具|資產)"),
    ("OCI",     r"透過其他綜合損益按公允價值衡量之金融資產"),
    ("AC",      r"按攤銷後成本衡量之債務工具投資"),
]
# 明細表的驗證特徵:窗口內要出現這些債券商品,才是真的明細表(而非政策/彙總)
CONFIRM = ("政府公債", "公司債", "金融債券")
# 商品列:中文品名開頭,後面接數字
ITEM_LINE = re.compile(r"^([一-鿿（）()]+)\s*\$?\s*([\d,()]+)")
# 一條線結束:碰到下一個附註標題 (X) 或「小計/合計」
STOP = re.compile(r"^[(（][一二三四五六七八九十廿卅]+[)）]|小\s*計|合\s*計|減：")


def extract_full_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def to_num(s: str):
    s = s.replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not s.isdigit():
        return None
    return -int(s) if neg else int(s)


def parse_note(text: str, anchor: str) -> dict:
    """從錨點往下讀商品列,取每列第一個數字(本期期末 = 6/30 或 12/31)。

    一個標題字串會在報告裡出現多次(政策、彙總、明細…),
    只挑「窗口內出現政府公債/公司債/金融債券」的那個明細表。
    """
    start = None
    for m in re.finditer(anchor, text):
        window = text[m.end():m.end() + 800]
        if sum(w in window for w in CONFIRM) >= 2:
            start = m.end()
            break
    if start is None:
        return {}
    items = {}
    started = False
    for line in text[start:].splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳過表頭日期列 (114.6.30 113.12.31 ...)
        if re.match(r"^[\d.]+\s+[\d.]+", line):
            started = True
            continue
        if STOP.match(line):
            if started and items:  # 讀到小計就結束這張表
                break
            continue
        im = ITEM_LINE.match(line)
        if im and started:
            name = re.sub(r"[（）()]", "", im.group(1))
            val = to_num(im.group(2))
            if val is not None and name not in items:
                items[name] = val
    return items


def extract(code: str, roc_year: int, period: str) -> dict:
    pdf_path = download(code, roc_year, period)
    text = extract_full_text(pdf_path)
    out = {}
    for cls, anchor in NOTES:
        out[cls] = parse_note(text, anchor)
    return out


def report(code: str, roc_year: int, period: str):
    data = extract(code, roc_year, period)
    print(f"\n{'='*60}\n{code}  {1911+roc_year}{period}  (民國{roc_year}年)\n{'='*60}")
    for cls, items in data.items():
        print(f"\n[{cls}]  (單位:仟元)")
        for name, val in items.items():
            print(f"   {name:<12} {val:>18,}")
    # 核對你的兩個目標欄位 (Trading)
    # CP+NCD+BA 桶 = 商業本票 + 可轉讓定存單 + 國庫券(+承兌匯票);GB = 政府公債(不含國庫券)
    t = data["Trading"]
    cp = (t.get("商業本票", 0) + t.get("可轉讓定期存單", 0)
          + t.get("國庫券", 0) + t.get("承兌匯票", 0))
    gb = t.get("政府公債", 0)
    print(f"\n--- 對照目標欄位 (億元) ---")
    print(f"   Trading_CP+NCD+BA = {cp/1e5:,.0f} 億")
    print(f"   Trading_GB        = {gb/1e5:,.0f} 億")


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "5841"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 114
    period = sys.argv[3] if len(sys.argv) > 3 else "H1"
    report(code, year, period)
