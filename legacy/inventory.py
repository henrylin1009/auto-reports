# -*- coding: utf-8 -*-
"""盤點腳本(plan_v2 §5):不改抽取,只探測每份 PDF 的定位/欄位/粒度現況。
輸出每份:明細表章頁、三類明細表頁+連頁?、取得成本欄?、BS 頁/是否掃描圖、主附註逐桶粒度。
純文字探測;抓不到=可能湯/圖,正好標示哪些得走視覺。"""
import glob, os, re, sys
import pdfplumber

BANKS = {"5835": "國泰", "5836": "富邦", "5841": "中信", "5843": "兆豐", "5847": "玉山"}
CLS_TITLE = {
    "Trading": "透過損益按公允價值衡量之金融資產明細表",
    "OCI": "透過其他綜合損益按公允價值衡量之金融資產明細表",
    "AC": "按攤銷後成本衡量之債務工具投資明細表",
}
CLS_NOTE = {  # 主附註標題(不含「明細表」)
    "Trading": "透過損益按公允價值衡量之金融",
    "OCI": "透過其他綜合損益按公允價值衡量之金融",
    "AC": "按攤銷後成本衡量之債務工具投資",
}
BUCKET_WORDS = ["政府公債", "公司債", "金融債", "商業本票", "國庫券",
                "資產基礎", "證券化", "可轉讓定期存單", "受益憑證", "股票"]


def load_pages(path):
    with pdfplumber.open(path) as pdf:
        return [pg.extract_text() or "" for pg in pdf.pages]


def find_chapter(pages):
    """明細表章起頁:後半段(>45%)含『重要會計項目明細表』的最前一個。"""
    n = len(pages)
    hits = [i for i in range(n) if "重要會計項目明細表" in pages[i]]
    back = [i for i in hits if i > n * 0.45]
    return back[0] if back else (hits[-1] if hits else None)


def find_detail_pages(pages, ch):
    """三類明細表頁:章起之後找『真表頁』(含標題+單位,排除明細表目錄/索引頁)。
       抓不到→None(可能湯/圖)。"""
    n = len(pages)
    lo = int(n * 0.5)  # 掃整個後半段(明細表可能在章標題頁之前)
    out = {}
    for cls, tg in CLS_TITLE.items():
        page = None
        for i in range(lo, n):
            t = pages[i]
            if tg not in t:
                continue
            if "明細表目錄" in t or "索引" in t or "§" in t:  # 跳過目錄/索引頁
                continue
            if "單位" not in t and "仟元" not in t and "千元" not in t:  # 真表頁有單位
                continue
            page = i
            break
        out[cls] = page
    return out


def has_cost_col(pages, detail):
    """三類明細表頁(±1)是否見『取得成本』欄。"""
    out = {}
    for cls, p in detail.items():
        if p is None:
            out[cls] = None
            continue
        blob = re.sub(r"\s", "", " ".join(pages[j] for j in range(max(0, p), min(len(pages), p + 2))))
        out[cls] = ("取得成本" in blob) or ("攤銷成本" in blob) or ("攤銷後成本" in blob)
    return out


def bs_page(pages):
    """資產負債表:前段(<15)含『資產總計/資產合計』的文字頁;若前段零文字→標掃描圖。"""
    front_zero = [i for i in range(min(14, len(pages))) if len(pages[i].strip()) < 30]
    for i in range(min(15, len(pages))):
        t = re.sub(r"\s", "", pages[i])  # 去空白再比(財報常「資 產 總 計」)
        if ("資產總計" in t or "資產合計" in t) and "金融資產" in t:
            return i, False
    # 沒抓到文字 BS + 前段一坨零文字 → 掃描圖版
    if len(front_zero) >= 4:
        return front_zero[0], True
    return None, bool(front_zero)


def note_granularity(pages):
    """主附註逐桶粒度:三類主附註標題附近是否見多個桶名(細到桶)還是只有小計。
       回傳每類:'桶級'(見≥3桶名)/ '粗'(僅小計/少)/ None(未定位)。"""
    n = len(pages)
    out = {}
    for cls, tg in CLS_NOTE.items():
        # 主附註在中段(附註『六/八/九/十…』說明),取文件前 70% 第一個「編號+標題」行
        page = None
        for i in range(int(n * 0.1), int(n * 0.72)):
            for ln in pages[i].splitlines():
                s = ln.strip()
                # 標題行:開頭是「六、」或「(三)」或「（三）」等編號,含科目名,非明細表
                if re.match(r"^[（(]?[一二三四五六七八九十]+[)）、]", s) and tg in s and "明細表" not in s and len(s) < 40:
                    page = i
                    break
            if page:
                break
        if page is None:
            out[cls] = None
            continue
        blob = " ".join(pages[j] for j in range(page, min(n, page + 3)))
        cnt = sum(1 for w in BUCKET_WORDS if w in blob)
        out[cls] = "桶級" if cnt >= 3 else "粗"
    return out


def contiguous(detail):
    ps = [p for p in detail.values() if p is not None]
    if len(ps) < 2:
        return None
    return (max(ps) - min(ps)) <= 8


def run(path):
    pages = load_pages(path)
    ch = find_chapter(pages)
    detail = find_detail_pages(pages, ch)
    cost = has_cost_col(pages, detail)
    bs, scan = bs_page(pages)
    gran = note_granularity(pages)
    return {"章": ch, "明細": detail, "連頁": contiguous(detail),
            "成本欄": cost, "BS": bs, "掃描圖": scan, "主附註粒度": gran, "頁數": len(pages)}


def fmt(v):
    return "·" if v is None else ("✓" if v is True else ("✗" if v is False else str(v)))


if __name__ == "__main__":
    files = sorted(f for f in glob.glob("pdf_cache/*.pdf")
                   if re.match(r"pdf_cache/(2024|2025)\d\d_58\d\d_AI3\.pdf$", f))
    print(f"盤點 {len(files)} 份(最近兩年,個體 AI3)\n")
    hdr = f"{'檔':22} {'頁':4} {'章':4} {'T':4} {'O':4} {'A':4} {'連':3} | 成本 T/O/A | {'BS':4}{'掃':3}| 主附註粒度 T/O/A"
    print(hdr); print("-" * len(hdr))
    for f in files:
        name = os.path.basename(f).replace(".pdf", "")
        try:
            r = run(f)
        except Exception as e:
            print(f"{name:22} ERR {e}"); continue
        d = r["明細"]; c = r["成本欄"]; g = r["主附註粒度"]
        cost = "/".join(fmt(c[k]) for k in ("Trading", "OCI", "AC"))
        gran = "/".join(fmt(g[k]) for k in ("Trading", "OCI", "AC"))
        print(f"{name:22} {r['頁數']:4} {fmt(r['章']):>4} "
              f"{fmt(d['Trading']):>4} {fmt(d['OCI']):>4} {fmt(d['AC']):>4} "
              f"{fmt(r['連頁']):>3} | {cost:9} | {fmt(r['BS']):>4}{fmt(r['掃描圖']):>3}| {gran}")
