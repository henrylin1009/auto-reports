# -*- coding: utf-8 -*-
"""
兆豐(5843)專用解析器。

兆豐個體財報未以「附註六(三)(四)(五)清單」揭露債券明細,
而是在「證券部門」附錄用【變動明細表】揭露(排版為縮放/座標式,
一般文字抽取會打散),故獨立於 extract3 之外處理。

作法:找證券部門三類「變動明細表」,依 x 座標切欄,
取各類別「小計」列的【期末公允價值/帳面】(切欄後固定在第 8 欄)。
回傳與其他四家相同的結構(單位:億元)。
"""
import re
import pdfplumber

# 表格標題 → 分類
CLS_BY_TITLE = [
    ("透過其他綜合損益", "OCI"),   # 需在「透過損益」之前判斷(前者含後者字樣)
    ("攤銷後成本",       "AC"),
    ("透過損益",         "Trading"),
]

# 類別名(單獨成列的表頭)→ 債種桶
CAT_MAP = {
    "政府公債": "公債", "公債": "公債",
    "國庫券": "國庫券",
    "公司債": "公司債",
    "金融債券": "金融債", "金融債": "金融債",
    "可轉讓定期存單": "可轉讓定存單", "可轉讓定存單": "可轉讓定存單",
    "資產基礎證券": "資產基礎", "受益證券": "資產基礎",
}
CP_CATS = {"商業本票"}  # 併入 _cp(與其他家一致)

BUCKET_KEYS = ["公債", "國庫券", "公司債", "金融債", "資產基礎", "可轉讓定存單", "其他"]


def _num(s):
    """'1,234'→1234;'(  74)'→-74;'-'/''→0"""
    s = s.replace(",", "").replace("$", "").replace(" ", "").strip()
    if s in ("", "-", "－"):
        return 0
    neg = s.startswith("(") or s.endswith(")")
    s = s.strip("()")
    m = re.search(r"-?\d+", s)
    if not m:
        return 0
    v = int(m.group())
    return -v if neg else v


def _page_rows(page):
    """依 top 分列、x 間距切欄。回傳 [[cell,...], ...](保留座標式數字分隔)。"""
    chars = sorted(page.chars, key=lambda c: c["top"])
    lines, cur, last = [], [], None
    for c in chars:
        if last is None or abs(c["top"] - last) <= 3:
            cur.append(c)
        else:
            lines.append(cur)
            cur = [c]
        last = c["top"]
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        ln = sorted(ln, key=lambda c: c["x0"])
        cells, buf, px = [], ln[0]["text"], ln[0]["x1"]
        for c in ln[1:]:
            if c["x0"] - px > 4.5:
                cells.append(buf)
                buf = c["text"]
            else:
                buf += c["text"]
            px = c["x1"]
        cells.append(buf)
        cells = [x.strip() for x in cells if x.strip()]
        if cells:
            out.append(cells)
    return out


def _title(page):
    return "".join(c["text"] for c in page.chars if c["upright"])[:80]


def _cls_of(title):
    # 早期以「證券部門」附錄揭露、近期以本行層級揭露,標題不一;
    # 只認債券資產的變動明細表(排除金融負債/權益法/使用權/第三等級等)。
    if "變動明細表" not in title:
        return None
    if ("金融資產" not in title) and ("債務工具" not in title):
        return None
    if "金融負債" in title:
        return None
    for kw, cls in CLS_BY_TITLE:
        if kw in title:
            return cls
    return None


def parse_megabank(pdf_path):
    """回傳 {'Trading':buckets, 'OCI':buckets, 'AC':buckets, '_cp':億元} 或 None。"""
    rec = {c: {k: 0.0 for k in BUCKET_KEYS} for c in ("Trading", "OCI", "AC")}
    rec["_cp"] = 0.0
    found = False
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            cls = _cls_of(_title(page))
            if not cls:
                continue
            found = True
            cur_cat = None
            for cells in _page_rows(page):
                label = cells[0].replace(" ", "")
                # 單獨成列的類別表頭(續頁類別可能不重覆,故沿用上一類別)
                if len(cells) == 1:
                    if label in CAT_MAP:
                        cur_cat = CAT_MAP[label]
                    elif label in CP_CATS:
                        cur_cat = "_cp"
                    continue
                # 類別表頭與小計在同列的情況
                for name in list(CAT_MAP) + list(CP_CATS):
                    if label.startswith(name):
                        cur_cat = CAT_MAP.get(name, "_cp")
                        break
                if label.startswith("小計") and cur_cat and len(cells) >= 9:
                    val = _num(cells[8]) / 1e5  # 仟元→億元;cells[8]=期末公允價值/帳面
                    if cur_cat == "_cp":
                        rec["_cp"] += val
                    else:
                        rec[cls][cur_cat] += val
    return rec if found else None


def parse_megabank_aoci(pdf_path, roc, mth):
    """兆豐 ③ AOCI:其他權益項目表(座標式)當期『淨額』列的
    『透過其他綜合損益按公允價值衡量之金融資產損益』欄(第2個值欄)。
    兆豐 FVOCI 全為債券(無權益工具),故此=OCI 債券準備(稅後)。回傳仟元或 None。"""
    day = "6月30日" if mth == "02" else "12月31日"
    target = f"{roc}年{day}"
    def row_values(cells):
        # 各欄值以 $ 或 ( 起頭;移除欄內空白但保留 $/括號當分隔,避免相鄰欄數字相黏。
        blob = "".join(cells[1:]).replace(" ", "")
        vals = []
        for m in re.finditer(r"\(\$?([\d,]+)\)|\$([\d,]+)", blob):
            g = m.group(1) or m.group(2)
            vals.append((-1 if m.group(1) else 1) * int(g.replace(",", "")))
        return vals
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = "".join(c["text"] for c in page.chars if c["upright"])
            if "其他權益項目" not in txt:
                continue
            for cells in _page_rows(page):
                lbl = cells[0].replace(" ", "")
                if lbl.startswith(target) and "淨額" in lbl:
                    v = row_values(cells)
                    if len(v) < 2:
                        return None
                    fvoci = v[1]                            # 欄序:兌換|FVOCI金融資產|其他|總計
                    # 合理性守衛:兆豐 FVOCI 準備現實約 ±200億;超出=座標黏字亂碼→N/A不出誤導數
                    return fvoci if abs(fvoci) <= 20_000_000 else None
    return None


if __name__ == "__main__":
    import sys, json
    r = parse_megabank(sys.argv[1] if len(sys.argv) > 1
                        else "pdf_cache/202402_5843_AI3.pdf")
    print(json.dumps(r, ensure_ascii=False, indent=2))
