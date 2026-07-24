# -*- coding: utf-8 -*-
"""視覺 Reader — 用多模態模型『看財報頁面』讀值(預設 Gemini 免費 Flash)。

取代 llm_reader(DeepSeek 讀線性文字)。差別:把定位到的幾頁『切成小 PDF』直接送模型,
模型用文字+視覺一起看 → 折行/多欄/字元湯天然解掉。語義(讀值、歸桶)交模型;
數字/對桶交叉/對帳留給 schema + universal.check。

底層模型可換(介面固定):read_note(path, pages, cls, ...) -> dict。
key 放 .env 的 GEMINI_API_KEY。
"""
import os
import io
import json

MODEL = "gemini-3.6-flash"          # 最新免費 Flash;難格可另升付費


def _load_env(path=".env"):
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_CLIENT = None
def _client():
    """單例:重用同一個 client(每次新建會在重試時被關閉→『client has been closed』)。"""
    global _CLIENT
    if _CLIENT is None:
        _load_env()
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("找不到 GEMINI_API_KEY,請在 .env 貼上你的 key")
        from google import genai
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def slice_pdf(path, pages):
    """pypdf 按頁碼把選中頁(0-based)抽成小 PDF bytes。純機械,不找、不失誤。"""
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(path)
    w = PdfWriter()
    n = len(r.pages)
    for p in pages:
        if 0 <= p < n:
            w.add_page(r.pages[p])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# Gemini 結構化輸出 schema(攤平:rows + subtotals 兩平表)
_SCHEMA = {
    "type": "object",
    "properties": {
        "source_type": {"type": "string"},          # 主附註 / 明細表
        "header": {"type": "string"},                # 所讀表頁首標題原文
        "anchor": {"type": "integer"},               # 整則最後『合計』(仟元)
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},      # 品名原文
                    "section": {"type": "string"},    # 所屬小計段(債務工具/權益工具/調整…)
                    "bucket": {"type": "string"},     # 模型歸的桶(見下方 BUCKET_CHOICES)
                    "book": {"type": "integer", "nullable": True},   # 帳面/取得成本(仟元)
                    "fair": {"type": "integer", "nullable": True},   # 公允價值(仟元)
                },
                "required": ["name", "section", "bucket"],
            },
        },
        "subtotals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "amount": {"type": "integer"},
                },
                "required": ["section", "amount"],
            },
        },
    },
    "required": ["source_type", "header", "anchor", "rows"],
}

BUCKET_CHOICES = "公債 / 貨幣市場 / 公司債 / 金融債 / 資產基礎 / 可轉讓定存單 / 其他 / 股票 / 調整項"

_PROMPT = """你在看一份台灣銀行財報的幾頁(PDF,含表格影像)。請找出「{cls_name}」的持有明細表並逐列讀出。

來源(重要):固定讀「{source}」;不是損益表、不是公允價值分級表、不是敘述段落。
只取「當期」金額:看欄位標題的『日期』,取日期最新那欄(半年報常有本期底/去年底/去年同期三欄,取本期底)。

逐列輸出(rows),每列:
- name:品名原文
- section:它所屬的小計段落名(如「債務工具」「權益工具」「調整」;衍生/避險段落請標「衍生」)
- bucket:把這列歸到下列其一(用會計意義判斷,不是字面):{buckets}
    * 受益憑證/基金/上市櫃/存託憑證/特別股 → 股票
    * 受益證券(資產證券化ABS)/不動產抵押貸款證券 → 資產基礎
    * 商業本票/承兌匯票/國庫券/央行定期存單 → 貨幣市場
    * 評價調整/減損/備抵/衍生/避險/應計利息 等『非持有本金』的橋接列 → 調整項
- book:帳面金額/取得成本欄(仟元,整數;括號或負號→負數;該欄無/破折號→null)
- fair:公允價值欄(仟元;沒有這欄→null)

subtotals:表上『印出來的』各段小計(section 名 + 金額)。沒印小計就不用列。
anchor:整則最後的『合計/總計』金額(不是中途小計)。
source_type:你讀的是「主附註」還是「明細表」。
header:你所讀那張表最上方標題那一行原文。

金額單位照原文(仟元),去逗號與 $,數字逐位看準。只回 JSON。"""


_BS_SCHEMA = {
    "type": "object",
    "properties": {
        "asset_total": {"type": "integer", "nullable": True},   # 資產側總額(流動+非流動已相加,仟元)
        "found": {"type": "boolean"},                            # 有沒有讀到
        "detail": {"type": "string"},                            # 說明:讀了哪幾行、怎麼相加(供人核)
    },
    "required": ["found"],
}

_BS_PROMPT = """你在看一份台灣銀行財報的『資產負債表』頁(PDF,含表格影像)。
請找出【資產側】科目「{cls_name}」的『當期(日期最新那欄)』金額,單位仟元。

重要:
- 舊格式常把這科目拆成「流動」+「非流動」兩列(代碼如 113xxx 與 123xxx),資產側也可能叫
  「…債務工具投資」而非「…金融資產」——都算同一科目,請把流動+非流動【相加】成一個總額。
- 只取【資產側】。務必【排除】權益區的同名項(如「…未實現損益/評價調整」),那不是資產。
- 只取當期欄(日期最新),不要去年欄;數字後面的小整數(1/8/50…)是百分比不是金額,別取。

asset_total = 資產側總額(流動+非流動相加後,仟元整數);讀不到就 found=false。
detail = 簡述你把哪幾列相加、各多少(讓人核對)。只回 JSON。"""


def read_bs_anchor(path, pages, cls_name, model=None):
    """切片資產負債表頁 → 模型視覺讀資產側總額(自動相加流動+非流動、排除權益側)。
       回傳 (asset_total 仟元 or None, detail 說明)。"""
    from google.genai import types
    pdf = slice_pdf(path, pages)
    prompt = _BS_PROMPT.format(cls_name=cls_name)
    resp = _client().models.generate_content(
        model=model or MODEL,
        contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt],
        config=types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", response_schema=_BS_SCHEMA),
    )
    d = json.loads(resp.text)
    return (d.get("asset_total") if d.get("found") else None), d.get("detail", "")


def page_types(path, thresh=50):
    """頁面分類(業界 detect-and-fallback):文字量 < 門檻 = 掃描圖頁(只有視覺看得到)。
       回傳 (image_pages[list], text_len{頁:字數})。一次分類、全管線共用。"""
    import pdfplumber
    image_pages, text_len = [], {}
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages):
            n = len((pg.extract_text() or "").strip())
            text_len[i] = n
            if n < thresh:
                image_pages.append(i)
    return image_pages, text_len


def outline(path, max_lines=2):
    """建精簡目錄(程式,便宜):逐頁抽標題(自帶正確 PDF 頁碼)。
       掃描圖頁(無文字)標記『(掃描圖頁)』,讓 navigate 知道它存在、指得到。"""
    import pdfplumber, re
    img, _ = page_types(path)
    imgset = set(img)
    out = []
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages):
            if i in imgset:
                out.append((i, "(掃描圖頁,可能是主報表/資產負債表)"))
                continue
            t = pg.extract_text() or ""
            heads = []
            for ln in t.splitlines():
                s = ln.strip()
                if not s or re.fullmatch(r"[\d,.\s\-()$%]+", s):   # 跳過純數字/符號行
                    continue
                heads.append(s[:40])
                if len(heads) >= max_lines:
                    break
            if heads:
                out.append((i, " ".join(heads)))
    return out


_NAV_SCHEMA = {
    "type": "object",
    "properties": {
        "Trading": {"type": "array", "items": {"type": "integer"}},
        "OCI": {"type": "array", "items": {"type": "integer"}},
        "AC": {"type": "array", "items": {"type": "integer"}},
        "BS": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["Trading", "OCI", "AC", "BS"],
}

_NAV_PROMPT = """以下是一份台灣銀行財報的『精簡目錄』(每行:頁碼 → 該頁標題)。
請幫我指出各項要讀的**頁碼**(可多頁),回 JSON。

要找的:
- Trading:「透過損益按公允價值衡量之金融資產(或金融工具)」的**持有明細表**
- OCI:「透過其他綜合損益按公允價值衡量之金融資產/債務工具投資」的**持有明細表**
- AC:「按攤銷後成本衡量之債務工具投資」的**持有明細表**
- BS:「資產負債表」頁

重要:
- 要「持有部位/餘額」那張(列公債/公司債/金融債…各多少),**優先財報正文的主附註**(附註編號如(十二)),
  **不要**損益表、不要『已實現損益明細表』、不要『公允價值分級表』、不要敘述段落。
- 若正文主附註與附錄明細表都有,兩個頁碼都給(讀取端會挑對帳得過的那張)。
- 找不到某項就給空陣列。頁碼用目錄上的數字。

目錄:
{outline}"""


def navigate(path, model=None):
    """Gemini 看目錄,一次回全部類別+資產負債表的頁碼(每份文件一次,不是每類)。"""
    from google.genai import types
    ol = outline(path)
    ol_text = "\n".join(f"p{i}: {h}" for i, h in ol)
    resp = _client().models.generate_content(
        model=model or MODEL,
        contents=[_NAV_PROMPT.format(outline=ol_text)],
        config=types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", response_schema=_NAV_SCHEMA),
    )
    return json.loads(resp.text)


def validate(note, bs_anchor):
    """對帳(算術,程式做)。note = read_note 結果;bs_anchor = 外錨(仟元)。
       回傳 dict:每桶 {帳面,公允}、類層總額、三道保險絲旗標、桶交叉檢查。"""
    import schema as S
    buckets = {}          # {桶: {"帳面":x, "公允":y}}
    book_total = fair_total = 0
    bucket_mismatch = []
    for r in note.get("rows", []):
        b = r.get("bucket") or ""
        name = r.get("name", "")
        bk, fr = r.get("book"), r.get("fair")
        if b == "調整項" or S.is_reconcile_only(name):
            continue                                   # 評價/減損/衍生 不入桶
        # 桶交叉檢查:模型歸的桶 vs schema 同義字(不一致→以模型為準,記下示警)
        s = S.bucket_of(name)
        if s and s != b and b != "股票":
            bucket_mismatch.append({"名": name, "模型": b, "schema": s})
        cell = buckets.setdefault(b, {"帳面": 0, "公允": 0})
        if bk: cell["帳面"] += bk; book_total += bk
        if fr: cell["公允"] += fr; fair_total += fr
    anchor = note.get("anchor")
    tol = S.RECON_ABS
    # 內部對帳:某一欄加總 == 印出的合計
    internal_ok = anchor is not None and min(
        abs(anchor - fair_total), abs(anchor - book_total)) <= tol
    # 外錨交叉:某一欄加總 == 資產負債表(OCI/Trading→公允欄;AC→帳面欄)
    cross_ok = bs_anchor is not None and min(
        abs(bs_anchor - fair_total), abs(bs_anchor - book_total)) <= tol
    # 分段小計自洽
    sub_fail = []
    for st in note.get("subtotals", []):
        seg, amt = st.get("section"), st.get("amount")
        if amt is None: continue
        s = sum((r.get("fair") or r.get("book") or 0)
                for r in note.get("rows", []) if r.get("section") == seg)
        if abs(s - amt) > tol:
            sub_fail.append({"段": seg, "讀出": s, "印出": amt})
    return {
        "buckets": buckets,
        "class": {"帳面總額": round(book_total / S.THOUSAND_TO_YI, 2),
                   "公允總額": round(fair_total / S.THOUSAND_TO_YI, 2),
                   "外錨": None if bs_anchor is None else round(bs_anchor / S.THOUSAND_TO_YI, 2)},
        "_pass": bool(internal_ok and cross_ok and not sub_fail),
        "_internal_ok": internal_ok, "_cross_ok": cross_ok,
        "_sub_fail": sub_fail, "_bucket_mismatch": bucket_mismatch,
        "_source_type": note.get("source_type"), "_header": note.get("header"),
    }


def read_note(path, pages, cls_name, source, model=None):
    """切片 PDF → 模型視覺讀 → 結構化 dict(rows 含桶與帳面/公允雙欄)。"""
    from google.genai import types
    pdf = slice_pdf(path, pages)
    prompt = _PROMPT.format(cls_name=cls_name, source=source, buckets=BUCKET_CHOICES)
    resp = _client().models.generate_content(
        model=model or MODEL,
        contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_SCHEMA,
        ),
    )
    return json.loads(resp.text)


_CLS_NAME = {"Trading": "透過損益按公允價值衡量之金融資產",
             "OCI": "透過其他綜合損益按公允價值衡量之金融資產",
             "AC": "按攤銷後成本衡量之債務工具投資"}
# 兩種來源提示;對帳不過就換另一種重試(不硬性指定,讓對帳裁決)。
_SRC_MAIN = "主附註(財報正文附註,段落式,附註編號如(十二));不是附錄明細表"
_SRC_DETAIL = "附錄明細表(逐標的清單,標題含『明細表』)"


def extract_cell(path, cls, nav=None):
    """端到端一格:定位→讀值→外錨→對帳;不過就換來源重試。回傳 validate 結果 + _meta。
       定位:navigate(Gemini 看目錄挑對表)為主;空則退回 universal.candidates/_bs_pages 保底。
       nav 可預先由 navigate(path) 算好傳入(每份一次,三類共用),省呼叫。"""
    import universal as U, schema as S
    if nav is None:
        try:
            nav = navigate(path)
        except Exception:
            nav = {}
    note_pages = nav.get(cls) or [i for i, _ in U.candidates(path, cls)]      # navigate 空→保底
    # BS 定位(detect-and-fallback):前段掃描圖頁=圖版主報表→優先餵視覺;
    # 否則用文字定位(navigate/_bs_pages)。解決『主資產負債表是掃描圖、文字定位看不到』。
    img_pages, _ = page_types(path)
    front_img = [i for i in img_pages if i < 15]        # 掃描主報表在報表前段
    # 要「一整塊」(≥4 頁)才判定為掃描圖版主報表→餵視覺;否則(文字家/零星空白)走文字定位。
    bs_pages = front_img if len(front_img) >= 4 else (nav.get("BS") or [i for i, _ in U._bs_pages(path)])
    bs, bs_detail = read_bs_anchor(path, bs_pages, cls_name=S.ANCHOR_BS[cls]) if bs_pages else (None, "")

    # 依 SOURCE 決定先讀哪種;不過再換另一種
    first = _SRC_DETAIL if "明細表" in S.SOURCE[cls] else _SRC_MAIN
    order = [first, _SRC_DETAIL if first == _SRC_MAIN else _SRC_MAIN]
    last = None
    for k, src in enumerate(order, 1):
        note = read_note(path, note_pages, cls_name=_CLS_NAME[cls], source=src)
        res = validate(note, bs)
        res["_meta"] = {"tries": k, "source_tried": src, "bs_detail": bs_detail,
                        "note_pages": note_pages, "bs_pages": bs_pages}
        last = res
        if res["_pass"]:
            return res
    return last            # 都不過 → 回最後一次(標記未過,待人工)
