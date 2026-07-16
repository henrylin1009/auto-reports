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


# FVTPL 明細品名 → 債種桶(證券部分;衍生工具不計,與其他四家 Trading 一致)
_FVTPL_MAP = [
    ("政府", "公債"), ("公債", "公債"),
    ("公司債", "公司債"),
    ("金融債", "金融債"),
    ("資產基礎", "資產基礎"),
    ("國庫券", "國庫券"),
    ("可轉讓定期存單", "可轉讓定存單"), ("可轉讓定存單", "可轉讓定存單"),
    ("股票", "股票"),
    ("受益憑證", "其他"), ("不動產投資信託", "其他"), ("受益證券", "其他"),
]
def _fvtpl_bucket(label):
    for kw, b in _FVTPL_MAP:
        if kw in label:
            return b
    return None


def parse_megabank_fvtpl(pdf_path):
    """兆豐 FVTPL(六(三)):證券部門附錄無此表,改用「重要會計項目明細表」中
    『透過損益按公允價值衡量之金融資產明細表』(本行層級)。該表品名為 90° 旋轉字、
    數字為縮小正立字,故依 top 對齊品名(x<160)與公允價值(x≈560–660)。
    自「衍生工具」列起停止(只取證券,與其他四家 Trading 口徑一致)。
    回傳 {桶:億元, "股票":億元, "_合計":合計公允價值億元, "_ok":對帳} 或 None。"""
    from collections import defaultdict
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            title = "".join(c["text"] for c in page.chars if c["upright"])[:80]
            if "透過損益按公允價值衡量之金融資產明細表" not in title:
                continue
            if "證券部門" in title or "負債" in title:
                continue
            labs, vals = defaultdict(list), defaultdict(list)
            for c in page.chars:
                if not c["text"].strip():
                    continue
                # 品名欄 x<160。兆豐逐年在「旋轉字/正立字」間換版,故不用 upright 過濾。
                if c["x0"] < 160:
                    labs[round(c["top"])].append((c["x0"], c["text"]))
                elif 560 <= c["x0"] <= 665:            # 公允價值總額欄
                    vals[round(c["top"])].append((c["x0"], c["text"]))
            def label_of(top):
                for t in range(top - 2, top + 3):
                    if t in labs:
                        return "".join(x for _, x in sorted(labs[t]))
                return ""
            def value_of(top):
                cs = sorted(vals.get(top, []))
                s = "".join(x for _, x in cs)
                m = re.search(r"[\d,]{4,}", s)
                return _num(m.group()) if m else None

            rec = {k: 0.0 for k in BUCKET_KEYS}
            rec["股票"] = 0.0
            total = None
            derivative = False
            for top in sorted(set(list(labs) + list(vals))):
                lbl = label_of(top)
                if "合計" in lbl:
                    tv = value_of(top)
                    if tv is not None:
                        total = tv
                    continue
                if "衍生工具" in lbl:                  # 之後為衍生,證券口徑到此為止
                    derivative = True
                    continue
                if derivative:
                    continue
                b = _fvtpl_bucket(lbl)
                if not b:
                    continue
                v = value_of(top)
                if v:
                    rec[b] += v / 1e5                  # 仟元→億元
            if total is None:
                return None
            sec = sum(rec.values())                    # 證券小計(含股票)
            # 對帳:證券小計 + 衍生 ≈ 合計;證券本身應 < 合計且占多數
            ok = sec > 0 and sec <= total / 1e5 * 1.02
            rec["_合計"] = round(total / 1e5, 1)
            rec["_證券"] = round(sec, 1)
            rec["_ok"] = bool(ok)
            return rec
    return None


if __name__ == "__main__":
    import sys, json
    p = sys.argv[1] if len(sys.argv) > 1 else "pdf_cache/202504_5843_AI3.pdf"
    print("== parse_megabank_fvtpl ==")
    print(json.dumps(parse_megabank_fvtpl(p), ensure_ascii=False, indent=2))
