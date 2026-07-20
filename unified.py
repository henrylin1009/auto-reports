# -*- coding: utf-8 -*-
"""統一抽取流水線(取代 extract3 / extract2 / extract_megabank / parse_fubon_fvtpl / override)。

一條線,五家共用:
  1. page_rows   詞座標重組 → 每列 = [格...](乾淨文字與『字元湯』通吃)
  2. locate      用標題關鍵字找候選表區段
  3. parse_table 通用列規則(去破折號 / 最近列配對 / 交錯字子序列)
  4. reconcile   各類對帳(債+股+衍生+評價 ≈ 小計/合計);挑對得上的候選
  5. bucket      同義字 → 標準桶
  6. gate        對帳過→出值;不過→N/A

每家專屬的只有一張小設定(標題用詞 / 特例旗標),其餘全共用。
開發策略:與現行 data.json(已驗證)逐格對照,綠了才切換。
"""
import re
import pdfplumber

# ───────────────────────── Stage 1: 取列(詞座標重組) ─────────────────────────
def page_rows(page, ythresh=7.0, xgap=12.0):
    """回傳 [(y, [cell,...])]。依詞的『垂直中心』就近分列(非四捨五入,避免品名與
       數字因基線微差被切到不同列)、同列內依 x 間距切格。乾淨文字與被打散成單字
       的『字元湯』都能還原成 品名+各年數字 的格。"""
    ws = [((w["top"] + w["bottom"]) / 2.0, w["x0"], w["text"]) for w in page.extract_words()]
    ws.sort()                              # 依中心 y 排序
    lines, cur, ref = [], [], None
    for cy, x, t in ws:
        if ref is None or cy - ref <= ythresh:
            cur.append((cy, x, t)); ref = cur[0][0]
        else:
            lines.append(cur); cur = [(cy, x, t)]; ref = cy
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        pts = sorted((x, t) for _, x, t in ln)
        cells, grp = [], [pts[0]]
        for x, t in pts[1:]:
            if x - grp[-1][0] > xgap:
                cells.append("".join(t for _, t in grp)); grp = [(x, t)]
            else:
                grp.append((x, t))
        cells.append("".join(t for _, t in grp))
        out.append((ln[0][0], cells))
    return out


# ───────────────────────── 數值工具 ─────────────────────────
_DASH = "―—–-"
def cell_num(cell):
    """一格 → 數值(仟元)。去 $ , () 及破折號填充;括號→負。非數字回 None。"""
    raw = cell
    for ch in "$,()" + _DASH:
        raw = raw.replace(ch, "")
    if raw.isdigit() and len(raw) >= 3:
        return -int(raw) if "(" in cell else int(raw)
    return None

def first_num(cells):
    """列中『當期』數值 = 品名後第一個數值欄。該欄為單獨破折號(當期無/nil)→回 0,
       不可誤取下一欄(去年數)。純文字/表頭→None。"""
    for c in cells:
        s = c.strip()
        if s and all(ch in _DASH for ch in s):   # 單獨破折號欄 = 當期 nil
            return 0
        v = cell_num(c)
        if v is not None:
            return v
    return None

def name_of(cells):
    """列的品名 = 數值欄之前的所有文字格併起來(國泰把『公 司 債』拆成多格,要合回)。"""
    parts = []
    for c in cells:
        s = c.strip()
        if cell_num(c) is not None or (s and all(ch in _DASH for ch in s)):
            break                       # 進入數值欄(含當期 nil 破折號)→ 品名結束
        if re.search(r"[一-鿿]", c):
            parts.append(c)
    return "".join(parts).replace(" ", "")


# ───────────────────────── Stage 5: 同義字 → 桶 ─────────────────────────
# 順序即優先序(先命中先歸);交錯字用子序列比對時也照這順序。
SYN = [
    ("公債",     ("政府公債", "政府債券")),
    ("公司債",   ("可轉換公司債", "公司債券", "公司債")),
    ("金融債",   ("金融債券", "金融債")),
    ("資產基礎", ("資產基礎證券", "資產基礎債券", "資產證券化商品", "證券化商品", "受益證券")),
    ("國庫券",   ("央行定期存單", "央行可轉讓定期存單", "短期票券", "央行票據", "國庫券", "商業本票")),
    ("可轉讓定存單", ("可轉讓定期存單", "銀行定期存單", "定存單")),
    ("其他",     ("國外機構發行債券", "其他證券及債券", "其他債券", "其他")),
]
EQUITY = ("上市櫃", "興櫃", "未上市", "國外股票", "受益憑證", "股票", "REITs", "權益")
BUCKETS = ["公債", "國庫券", "公司債", "金融債", "資產基礎", "可轉讓定存單", "其他"]

def bucket_of(name):
    for b, kws in SYN:
        if any(kw in name for kw in kws):
            return b
    return None

def is_equity(name):
    return any(k in name for k in EQUITY)

def empty_buckets():
    return {b: 0.0 for b in BUCKETS} | {"股票": 0.0}


# ───────────────────────── Stage 2-4: 定位 + 解析 + 對帳 ─────────────────────────
TITLES = {
    "Trading": ("透過損益按公允價值衡量之金融資產",),
    "OCI":     ("透過其他綜合損益按公允價值衡量之債務工具投資",
                "透過其他綜合損益按公允價值衡量之金融資產", "債務工具投資"),
    "AC":      ("按攤銷後成本衡量之債務工具投資",),
}
_STOP = ("小計", "淨額", "合計")

def _norm(cells):
    return "".join(cells).replace(" ", "")

# 各類的「別類招牌」——解析中撞到=已跨進另一則附註,該表結束
_BOUNDARY = {
    "OCI":     ("攤銷後成本衡量之", "透過損益按公允價值衡量之金融資產"),
    "AC":      ("透過其他綜合損益按公允價值衡量之", "透過損益按公允價值衡量之金融資產"),
    "Trading": ("其他綜合損益按公允價值衡量之", "攤銷後成本衡量之"),
}

def _parse_block(rows, cls):
    """一段列 → (items 桶→仟元, adj 評價調整, subtotal, stock)。取『債券小計』止。
       equity-first(國泰:權益工具在前)時第一個小計是股票小計→不收尾,續讀債券。
       撞到別類附註標題(section 邊界)→ 立即結束,避免 seg 溢流到隔壁表。"""
    items = {}; adj = 0; sub = None; stock = 0
    for _, cells in rows:
        j = _norm(cells)
        if any(b in j for b in _BOUNDARY[cls]):   # 跨到別類附註 → 收尾
            break
        if "評價調整" in j or "評價損益" in j:
            v = first_num(cells)
            if v is not None: adj += v
            continue
        if any(s in j for s in _STOP):
            if items:                 # 已收到債券 → 這是債券小計,收尾
                sub = first_num(cells); break
            stock = 0; adj = 0        # 尚無債券(權益工具區的小計)→ 重置,續讀債券區
            continue
        v = first_num(cells)
        if v is None:            # 敘述行 / 表頭(無數字)→ 跳過
            continue
        nm = name_of(cells)
        # 裸小計:無品名、只有金額,且已收到債券(玉山/富邦早年不寫「小計」二字)
        if not nm and items:
            sub = v; break
        b = bucket_of(nm)
        if b:
            items[b] = items.get(b, 0) + v
        elif is_equity(nm):
            stock += v
    return items, adj, sub, stock

def extract(path, cls, cfg=None):
    """統一入口:回傳 {桶:億元, 股票:億元} 或 None(對帳不過/無資料)。"""
    titles = TITLES[cls]
    with pdfplumber.open(path) as pdf:
        allrows = []
        for pg in pdf.pages:
            raw = pg.extract_text() or ""
            if "明細表" in raw or "證券部門" in raw:
                continue
            hay = raw
            if cls == "Trading":
                hay = raw.replace("透過其他綜合損益按公允價值衡量之金融資產", "")
            if not any(t in hay for t in titles):
                continue
            allrows.append(page_rows(pg))
    if not allrows:
        return None
    # 候選:每個「命中標題的列」之後到第一個小計,當一段
    flat = [r for pr in allrows for r in pr]
    cands = []
    for i, (_, cells) in enumerate(flat):
        j = _norm(cells)
        mt = next((t for t in titles if t in j), None)
        if not mt:
            continue
        # 排除「內文提到標題字樣」的敘述句(只認真正的表頭列)
        if any(w in j for w in ("上述", "已附", "除列", "減損", "持有", "質押", "整體",
                                 "認列", "係指", "選擇", "評估", "並不")):
            continue
        if cls != "AC" and "攤銷後成本" in j:      # OCI/Trading 別誤抓 AC 表
            continue
        if cls == "Trading" and "其他綜合" in j:     # Trading 別誤抓 OCI 表
            continue
        seg = flat[i + 1:i + 60]
        items, adj, sub, stock = _parse_block(seg, cls)
        ndebt = sum(1 for b in items if b in BUCKETS)
        if ndebt >= 2 and sub:
            recon = abs(sum(items.values()) + adj - sub) <= max(100, 0.006 * abs(sub))
            # 標題專屬度:此類的招牌字在標題內(避免 OCI 誤選 AC 之類跨類污染)
            sig = {"OCI": "其他綜合", "AC": "攤銷後成本", "Trading": "透過損益"}[cls]
            spec = 1 if sig in mt else 0
            cands.append((recon, spec, ndebt, items, stock))
    if not cands:
        return None
    best = max(cands, key=lambda c: (c[0], c[1], c[2]))
    if not best[0]:          # 對帳不過 → N/A
        return None
    out = {b: best[3].get(b, 0) / 1e5 for b in BUCKETS}
    out["股票"] = best[4] / 1e5
    return out
