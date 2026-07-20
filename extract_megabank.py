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


# =====================================================================
# 主附註六(三)(四)(五)彙總解析器(通用「詞座標重組」,讀毛額)
# ---------------------------------------------------------------------
# 兆豐主附註跟其他四家一樣有債種彙總表,只是排版讓 extract_text 打散成
# 「字元湯」。這裡按詞的 y 座標重新分列、同列內按 x 切格,即可還原;
# 各債種列取「當期(民國當年,年報中排最左)」的第一個數字 = 毛額(取得成本)。
# 已驗:六期 AC 幾乎逐格對得上手工 override;OCI 為毛額(公債/資產基礎
# 因長天期跌價,毛額 > override 淨額,屬口徑差非錯)。
#
# 口徑定案:主資料一律用毛額;評價調整(市價含損)另抓供估值視角。
# 回傳 items 用「其他四家 bond_buckets 認得的正規名」,可直接餵 E.bond_buckets。
# =====================================================================

# 兆豐各表原始品名 → bond_buckets 正規名(仟元累加)
_MAIN_NAME_MAP = [
    ("政府債券", "政府公債"), ("政府公債", "政府公債"),
    ("公司債券", "公司債券"), ("公司債", "公司債券"),
    ("金融債券", "金融債券"), ("金融債", "金融債券"),
    ("資產基礎", "證券化商品"), ("證券化商品", "證券化商品"), ("受益證券", "證券化商品"),
    ("央行定期存單", "央行定期存單"), ("央行定存單", "央行定期存單"),
    ("短期票券", "短期票券"), ("央行票據", "央行票據"), ("國庫券", "國庫券"),
    ("銀行定期存單", "定存單"), ("定期存單-可轉讓", "可轉讓定期存單"),
    ("可轉讓定期存單", "可轉讓定期存單"), ("定存單", "定存單"),
]
# 權益(股票桶):不進 bond_buckets,另計
_MAIN_STOCK_KW = ("上市櫃公司股票", "興櫃公司股票", "非上市", "上市櫃股票",
                  "未上市", "國外股票", "受益憑證")
_MAIN_SKIP = ("小計", "合計", "淨額", "評價調整", "減：", "減:", "衍生")


def _mega_cells(words, gap=12):
    """一列的詞依 x 間距切成『格』(品名 / 各年數字各成一格)。"""
    words = sorted(words)
    out, cur = [], [words[0]]
    for x, t in words[1:]:
        if x - cur[-1][0] > gap:
            out.append(cur); cur = [(x, t)]
        else:
            cur.append((x, t))
    out.append(cur)
    return ["".join(t for _, t in c) for c in out]


def _mega_rows(pg):
    """回傳 [(top, [(x,text)...])],依 y 分列。"""
    rows = {}
    for w in pg.extract_words():
        rows.setdefault(round(w["top"] / 3.0), []).append((w["x0"], w["text"]))
    return [(k, sorted(r)) for k, r in sorted(rows.items())]


def _mega_first_num(row):
    """取這列切格後第一個數字格 = 當期(毛額)。括號→負。
       去除 $ , () 及長短劃填充(如『5,860,463-』尾隨破折號),避免漏數。"""
    for cell in _mega_cells(row):
        raw = cell
        for ch in "$,()―—–-":
            raw = raw.replace(ch, "")
        if raw.isdigit() and len(raw) >= 5:
            return -int(raw) if "(" in cell else int(raw)
    return None


def _mega_name(txt):
    for raw, canon in _MAIN_NAME_MAP:
        if raw in txt:
            return canon
    return None


def _is_subseq(pat, s):
    """pat 的字元是否依序出現在 s 中(容忍交錯字,如『公司債券』∈『公國司庫債券券』)。"""
    it = iter(s)
    return all(ch in it for ch in pat)


# 缺口反推只補這幾類核心債種(貨幣市場類金額大、風險高,不推)
_INFER_CORE = ["政府公債", "公司債券", "金融債券", "證券化商品"]


def _mega_infer(items, subtotal, valued_noname, named_novalue):
    """通用缺口反推,治『錯行/交錯字』。就地改 items。全程由外層對帳閘門保護。
       規則①(交錯字):有數字但品名交錯→用『字元子序列』對到唯一未填核心債種。
       規則②(錯行):有品名但無數字→若加總距小計恰差一個未填品名,把缺口給它。"""
    # 規則①:valued_noname(有值、名交錯)→ 子序列唯一對到「尚未填的核心債種」
    for val, raw in valued_noname:
        cands = [c for c in _INFER_CORE if c not in items and _is_subseq(c, raw)]
        if len(cands) == 1:
            items[cands[0]] = items.get(cands[0], 0) + val
    # 規則②:named_novalue(有名、無值)→ 缺口反推
    gap = subtotal - sum(items.values())
    nov = [n for n in named_novalue if n not in items]
    if gap > 0 and len(nov) == 1:
        items[nov[0]] = gap


def parse_megabank_main(path):
    """讀兆豐主附註六(三)(四)(五)彙總(毛額)。
       回傳 {"Trading":items, "OCI":items, "AC":items,
             "股票":{cls:仟元}, "adj":{cls:評價調整仟元}, "ok":{cls:bool}}
       items 為正規名→仟元,可直接餵 extract3.bond_buckets。抓不到的類回 {}、ok=False。"""
    TITLES = [
        ("Trading", "透過損益按公允價值衡量之金融資產"),
        ("OCI",     "透過其他綜合損益按公允價值衡量之金融資產"),
        ("AC",      "按攤銷後成本衡量之債務工具投資"),
    ]
    out = {"Trading": {}, "OCI": {}, "AC": {},
           "股票": {"Trading": 0, "OCI": 0, "AC": 0},
           "adj": {"Trading": 0, "OCI": 0, "AC": 0},
           "ok": {"Trading": False, "OCI": False, "AC": False}}
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        for cls, title in TITLES:
            # 1) 逐頁重組;依「小計」把列切成一張張表(block)。
            #    逐頁處理(頁尾未收尾的殘列丟棄),避免現金流量表等雜訊頁跨頁污染真表。
            blocks = []            # [{"items":{}, "subtotal":int, "end":idx}]
            adjs, netvals = [], []  # [(idx, value)]
            idx = 0
            for pg in pages:
                raw = pg.extract_text() or ""
                # Trading 標題是 OCI 標題的子字串→先剔除 OCI 標題再判,避免抓到 OCI 表
                hay = raw.replace("透過其他綜合損益按公允價值衡量之金融資產", "") \
                    if cls == "Trading" else raw
                if title not in hay:
                    continue
                if "明細表" in raw or "證券部門" in raw:   # 排除附錄逐檔表,只要主附註
                    continue
                cur = {"items": {}, "subtotal": None}   # 每頁重置,不跨頁累積
                for _, r in _mega_rows(pg):
                    idx += 1
                    txt = "".join(t for _, t in r)
                    if "評價調整" in txt:
                        v = _mega_first_num(r)
                        if v is not None:
                            adjs.append((idx, v))
                        continue
                    if "淨額" in txt:
                        v = _mega_first_num(r)
                        if v is not None:
                            netvals.append((idx, v))
                        continue
                    if "小計" in txt:
                        cur["subtotal"] = _mega_first_num(r); cur["end"] = idx
                        if cur["items"]:
                            blocks.append(cur)
                        cur = {"items": {}, "subtotal": None}
                        continue
                    if any(k in txt for k in ("合計", "減：", "減:", "衍生", "應付", "償還", "發行")):
                        continue                          # 排除現金流量表的「應付/發行金融債券」等雜訊
                    nm = _mega_name(txt)
                    v = _mega_first_num(r)
                    if nm and v is not None:
                        cur["items"][nm] = cur["items"].get(nm, 0) + v
                    elif nm and v is None:                 # 有品名、無數字(錯行)→ 記待補
                        cur.setdefault("named_novalue", []).append(nm)
                    elif nm is None and v is not None and any(k in txt for k in ("債", "券", "單", "票")):
                        cur.setdefault("valued_noname", []).append((v, txt))  # 有數字、品名交錯→待推名
            # 3) 選債務工具表 = 小計最大的那張(FVOCI 債務 >> FVTPL/權益)
            debt = max((b for b in blocks if b["subtotal"]),
                       key=lambda b: abs(b["subtotal"]), default=None)
            if not debt:
                continue
            # 3.5) 缺口反推(通用,治「錯行/交錯字」):只在簡單比對對不上小計時啟動,
            #      全程受對帳閘門保護——推錯→整組作廢→退回 override,只會更好不會更糟。
            items = dict(debt["items"]); sub = debt["subtotal"]
            if sub and abs(sum(items.values()) - sub) > 0.005 * abs(sub):
                _mega_infer(items, sub, debt.get("valued_noname", []),
                            debt.get("named_novalue", []))
            debt["items"] = items
            out[cls] = items
            # 股票只有 FVOCI 有權益工具:取債務表後的權益工具淨額(含評價調整,與他行一致)。
            # Trading/AC 無股票(AC 依定義只債券;Trading 股票另由 fvtpl 解析器處理)。
            if cls == "OCI":
                eq = [v for i, v in netvals if i > debt["end"]]  # 債務表之後的淨額 = 權益淨額
                out["股票"][cls] = eq[-1] if eq else 0
            # 債務評價調整 = 該債務表小計之後第一個評價調整
            after = [v for i, v in adjs if i > debt["end"]]
            out["adj"][cls] = after[0] if after else 0
            s = sum(debt["items"].values())
            # 對帳門檻 0.5%:乾淨表餘裕 <0.1%;交錯字致某債種漏配者(如2022 AC公司債)
            # 會落在 ~1% 被擋下→退回 override(手工對帳值),不靜默漏一類。
            out["ok"][cls] = bool(debt["subtotal"] and s and
                                  abs(s - debt["subtotal"]) <= 0.005 * abs(debt["subtotal"]))
    return out


if __name__ == "__main__":
    import sys, json
    p = sys.argv[1] if len(sys.argv) > 1 else "pdf_cache/202504_5843_AI3.pdf"
    print("== parse_megabank_main ==")
    print(json.dumps(parse_megabank_main(p), ensure_ascii=False, indent=2))
