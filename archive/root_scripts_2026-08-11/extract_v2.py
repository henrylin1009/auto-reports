# -*- coding: utf-8 -*-
"""plan v2 抽取管線:章錨/LLM 找頁 → 視覺讀明細表(成本+公允)→ 三道對帳(含第2級逐桶)。
單一來源=明細表;主附註只當第2級逐桶證人;BS 只當外錨。缺欄→NA;對不過→fail-loud。
無外部 reader 依賴(vision_reader/schema 已退役)。

Gemini API 的呼叫層(多把 key 輪替 + 節流)已搬到 `core/llm.py`
(`docs/plan_schema_derive.md` D3)——`fill_auto.py` 只需要那一個函式,
不該為此 import 這整支 786 行的舊管線。`_gen` 留在這裡當別名,
是因為本檔自己也有獨立的呼叫點(不重複定義同一套邏輯)。
"""
import io, json, os, re
import pdfplumber
from config import (MODEL, MIN_GAP, MAX_EXPAND, TOL, TOL_REL, CLS_TITLE, CLS_NAME,
                    # 本檔用**凍結**的舊桶名(含「調整項」),不跟 v3 的 BUCKETS 走。
                    # v3 把「調整項」拆成 衍生 / 評價調整;若共用,LLM 會回傳本檔
                    # 認不得的桶名,而 L398/L588 靠 `!= "調整項"` 濾非桶列 →
                    # 調整項會被當成真桶加進去,線上網站數字直接壞掉。
                    # R5 刪本檔時,config 那兩個 LEGACY_* 一起刪。
                    LEGACY_BUCKETS as BUCKETS, LEGACY_BUCKET_RULES as BUCKET_RULES)
from core.llm import generate as _gen


def slice_pdf(path, pages):
    """pypdf 按頁碼(0-based)把選中頁抽成小 PDF bytes。純機械,不找、不失誤。"""
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

# MODEL / MIN_GAP / MAX_EXPAND / TOL / BUCKETS / BUCKET_RULES / CLS_* 皆來自 config.py(全站唯一設定源)

# BUCKETS / BUCKET_RULES / CLS_TITLE / CLS_NAME 皆來自 config.py


# ═══════════ 定位 ═══════════
def pages_text(path):
    with pdfplumber.open(path) as pdf:
        return [pg.extract_text() or "" for pg in pdf.pages]


def digest(pages, lo=0, hi=None):
    """形狀篩摘要:每頁抽『標題形狀的行』(短+含編號/關鍵詞;丟長數字行=濾湯)。"""
    hi = hi or len(pages)
    kw = ("明細表", "透過損益", "透過其他綜合", "攤銷後成本", "金融資產", "債務工具",
          "資產負債表", "資產總計", "資產合計", "重要會計項目")
    numbered = re.compile(r"^[（(]?[一二三四五六七八九十]+[)）、]|^表[一二三四五六七八九十]|^明細表[一二三四五六七八九十]")
    out = []
    for i in range(lo, hi):
        lines = [ln.strip() for ln in pages[i].splitlines()]
        # 先黏合連續短行,還原被拆行斷字的標題(「…衡量之」+「金融資產明細表」)
        merged = []
        for s in lines:
            if s and len(s) < 40 and not re.fullmatch(r"[\d,.\s\-()$%~〜]+", s):
                merged.append(s)
            else:
                merged.append("")  # 段落界:長行/數字行/空行都當分隔
        joined = []
        buf = ""
        for s in merged:
            if s:
                buf += s
            elif buf:
                joined.append(buf); buf = ""
        if buf:
            joined.append(buf)
        heads = []
        for s in lines + joined:  # 原短行 + 黏合後的長標題都當候選
            if not s or len(s) >= 60:
                continue
            if re.fullmatch(r"[\d,.\s\-()$%~〜]+", s):
                continue
            if numbered.match(s) or any(k in s for k in kw):
                heads.append(s[:60])
        if heads:
            # 去重保序
            seen = set(); uniq = [h for h in heads if not (h in seen or seen.add(h))]
            out.append((i, " | ".join(uniq[:5])))
    return out


_LOC_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "array", "items": {"type": "integer"}}
                   for k in ("Trading", "OCI", "AC")},
    "required": ["Trading", "OCI", "AC"],
}
_LOC_PROMPT = """以下是一份台灣銀行個體財報「明細表章」的精簡目錄(每行:頁碼 → 標題)。
請把三類『持有明細表』的**所有候選起頁**列出(可多頁),回 JSON。
- Trading:「透過損益按公允價值衡量之金融資產明細表」
- OCI:「透過其他綜合損益按公允價值衡量之金融資產明細表」
- AC:「按攤銷後成本衡量之債務工具投資明細表」
要逐檔/逐桶明細那張(列公債/公司債/金融債各多少),不要目錄頁、不要損益明細表、不要金融「負債」表。
【求全不求準】同一類若有多張(本行整體、證券部門、流動、非流動…),**全部都列出來**——由後端用合計對資產負債表挑/加總,你不用判哪張才對,漏列才是問題。
標題可能被拆行或缺字,用語意判。找不到給空陣列。目錄:
{digest}"""


def locate_by_digest(pages, lo, hi, prompt_tmpl):
    """統一定位原語:抽[lo,hi)頁段的文字大標做目錄 → LLM 回三類頁碼(陣列)。
       明細表(掃後段)、主附註(掃中段)共用;只差頁段與 prompt。純文字,不用影像。"""
    dg = digest(pages, lo, hi)
    dg_text = "\n".join(f"p{i}: {h}" for i, h in dg)
    from google.genai import types
    resp = _gen(
        model=MODEL, contents=[prompt_tmpl.format(digest=dg_text)],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=_LOC_SCHEMA))
    return json.loads(resp.text)


def locate_details(path, pages):
    """明細表定位:章錨框後段 → locate_by_digest 回三類明細表頁碼。"""
    n = len(pages)
    hits = [i for i in range(n) if "重要會計項目明細表" in pages[i]]
    ch = next((i for i in hits if i > n * 0.45), hits[-1] if hits else int(n * 0.6))
    lo = max(0, min(ch, int(n * 0.5)) - 2)          # 表可能在章標題頁之前,往前留 buffer
    return locate_by_digest(pages, lo, n, _LOC_PROMPT), ch


def rescan_detail_pages(pages, cls):
    """關鍵字重掃:找出標題精準命中某類明細表的頁(0-based)。
       LLM 盲挑標題漏頁(尤其被『證券部門』子報表誘餌帶走)時的兜底——用金額對 BS 前先把候選撈齊。
       排除『證券部門/部門』子報表;標題以去空白後子字串精準比(Trading『透過損益按…』≠ OCI『透過其他綜合損益按…』)。"""
    title = re.sub(r"\s", "", CLS_TITLE[cls])
    out = []
    for i in range(len(pages)):
        t = re.sub(r"\s", "", pages[i])
        if title in t and "證券部門" not in t and "部門明細" not in t:
            out.append(i)
    return out


_NOTE_LOC_PROMPT = """以下是一份台灣銀行個體財報「附註」段的精簡目錄(每行:頁碼 → 標題)。
請指出三類金融資產『主附註(文字敘述持有明細)』的起頁(可多頁),回 JSON。
- Trading:「透過損益按公允價值衡量之金融工具/資產」
- OCI:「透過其他綜合損益按公允價值衡量之金融資產」
- AC:「按攤銷後成本衡量之債務工具投資」
要附註區那段「編號+科目名」的文字明細(如「八、透過損益按公允價值衡量之金融工具」),
**不要**末端「重要會計項目明細表」那張大表、不要損益表、不要「負債」。
標題可能巢狀編號「(三)1.」或被拆行,用語意判。找不到給空陣列。目錄:
{digest}"""

_NOTES_CACHE = {}


def locate_notes_all(pages, path=None):
    """主附註定位(取代手刻 regex):掃中段 → locate_by_digest 回三類頁碼。一份只算一次(memo)。
       快取鍵用檔案路徑(不可用 id(pages):物件 GC 後位址會重用,批次會張冠李戴)。"""
    key = path or ("_anon", id(pages), len(pages))
    if key not in _NOTES_CACHE:
        n = len(pages)
        _NOTES_CACHE[key] = locate_by_digest(pages, int(n * 0.08), int(n * 0.75), _NOTE_LOC_PROMPT)
    return _NOTES_CACHE[key]




def locate_note(pages, cls, path=None):
    """某類主附註頁:取自統一定位 locate_notes_all(涵蓋起頁+下一頁)。"""
    ps = sorted(set(locate_notes_all(pages, path).get(cls) or []))
    if not ps:
        return []
    return sorted(set(ps + [ps[0] + 1]))


# ═══════════ 視覺讀值 ═══════════
_DET_SCHEMA = {
    "type": "object",
    "properties": {
        "header": {"type": "string"},
        "saw_total_row": {"type": "boolean"},   # 有沒有看到收尾「合計/總計」列
        "table_continues": {"type": "boolean"}, # 表是否延續到所餵頁面之後
        "cost_total": {"type": "integer", "nullable": True},   # 印出的取得成本合計
        "value_total": {"type": "integer", "nullable": True},  # 印出的公允/帳面合計
        "rows": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "section": {"type": "string"}, "bucket": {"type": "string"},
            "cost": {"type": "integer", "nullable": True},     # 取得成本(仟元)
            "fair": {"type": "integer", "nullable": True},     # 公允價值/AC帳面(仟元)
        }, "required": ["name", "section", "bucket"]}},
    },
    "required": ["header", "rows"],
}
_DET_PROMPT = """你在看台灣銀行個體財報的「{cls_name}明細表」(PDF 含表格影像)。逐列讀出持有明細。
只取當期(日期最新那欄)。每列:
- name:品名原文
- section:所屬小計段(債務工具/權益工具/強制透過損益…;衍生段標「衍生」)
- bucket:{buckets}
{rules}
- cost:取得成本欄(仟元整數;括號/負號→負;無此欄或該格空→null)。AC 表通常無取得成本欄→cost 給 null。
- fair:公允價值欄;AC 表則取「帳面金額/帳面價值」欄(仟元)。
cost_total / value_total:表最後印出的『取得成本合計』與『公允/帳面合計』(沒有就 null)。
header:表最上方標題原文。
saw_total_row:所餵頁面裡有沒有看到這張表收尾的「合計/總計」列(有=表在此結束)。
table_continues:最後一列看起來是否還沒到底、表延續到下一頁(沒讀到合計列通常=true)。
數字逐位看準、去逗號。只回 JSON。"""


def read_detail(path, pages_idx, cls):
    from google.genai import types
    pdf = slice_pdf(path, pages_idx)
    prompt = _DET_PROMPT.format(cls_name=CLS_NAME[cls], buckets=" / ".join(BUCKETS), rules=BUCKET_RULES)
    resp = _gen(
        model=MODEL, contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=_DET_SCHEMA))
    d = json.loads(resp.text)
    d["_pages"] = list(pages_idx)
    return d


def read_detail_windowed(path, start, cls, n_pages=None):
    """從 start 起讀,靠 gemini 自報 saw_total_row 擴頁到看見收尾合計列為止(D)。
       先讀單頁:自足單頁表(合計就在本頁)乾淨讀,不被相鄰的『另一類』表汙染合計
       (曾把 Trading 本表與下一頁 OCI 表一起餵 → value_total=None,對不上 BS 而鎖錯表)。
       單頁沒讀到收尾合計列(表未結束)才往後擴。"""
    n_pages = n_pages or 10 ** 9
    window = [start] if start < n_pages else []
    det = read_detail(path, window, cls)
    for _ in range(MAX_EXPAND):
        if det.get("saw_total_row") and not det.get("table_continues"):
            break
        nxt = window[-1] + 1
        if nxt >= n_pages:
            break
        window.append(nxt)
        det = read_detail(path, window, cls)
    return det


def _combos(items, k):
    if k == 0:
        yield []
        return
    for i in range(len(items)):
        for rest in _combos(items[i + 1:], k - 1):
            yield [items[i]] + rest


def select_detail(path, candidates, cls, bs, n_pages=None):
    """BS 導向候選(E):逐候選讀到表尾,選 value_total==BS 的單張;否則湊子表相加==BS。
       感知(讀)交給 gemini,判斷(選/湊)交給規則對 BS。回 (det, mode)。"""
    reads = []
    for c in sorted(set(candidates)):
        try:
            reads.append(read_detail_windowed(path, c, cls, n_pages))
        except Exception as e:
            if _is_transient(e):
                raise                 # 交最外層 with_retry 重試,別誤判成「候選讀不出」
            continue                  # 只吞解析/資料類錯(這張確實讀不出)
    reads = [r for r in reads if r.get("rows")]
    if not reads:
        return None, "no_read"
    if bs is None:  # 無外錨:挑『自洽』那張(有印出合計、且全列相加≈印出合計),讓內錨自證有效
        def _selfok(r):
            s = sum((row.get("fair") or 0) for row in r.get("rows", []))
            vt = r.get("value_total")
            return vt is not None and _tie(s, vt)
        best = max(reads, key=lambda r: (_selfok(r), bool(r.get("saw_total_row")), len(r.get("rows", []))))
        best = dict(best); best["_needs_review"] = True
        return best, "no_bs"
    # ① 單張命中
    hits = [r for r in reads if _tie(r.get("value_total"), bs)]
    if hits:
        best = min(hits, key=lambda r: abs(r["value_total"] - bs))
        return best, "single"
    # ② 加總命中:2~3 張子表相加 == BS
    withtot = [r for r in reads if r.get("value_total") is not None]
    for k in (2, 3):
        for combo in _combos(withtot, k):
            if _tie(sum(r["value_total"] for r in combo), bs):
                return _merge_reads(combo), "sum%d" % k
    # ③ 都不中:回最接近的單張,標人工複核
    best = min(reads, key=lambda r: abs((r.get("value_total") or 0) - bs))
    best = dict(best); best["_needs_review"] = True
    return best, "best_effort"


def _merge_reads(reads):
    """把若干子表合成一張:rows 串接、合計相加(用於流動+非流動)。"""
    out = {"header": " + ".join(str(r.get("header", ""))[:20] for r in reads),
           "rows": [row for r in reads for row in r.get("rows", [])],
           "saw_total_row": all(r.get("saw_total_row") for r in reads),
           "_pages": [p for r in reads for p in r.get("_pages", [])]}
    for k in ("cost_total", "value_total"):
        vals = [r.get(k) for r in reads if r.get(k) is not None]
        out[k] = sum(vals) if vals else None
    return out


# ── 檔名元資料:唯一知道「檔名長怎樣」的地方。擴到別家/別報表型只改這裡的資料。──
# 檔名 = YYYYMM_股票代碼_型別。第 5~6 碼是『期別碼』:02=半年報、04=年報(不是月份)。
PERIOD = {"01": True, "02": True, "03": True, "04": False}   # 期別碼 → is_halfyear(季報 01/03 走主附註,同半年報);不在表內 = 異常,報錯不靜默
_FNAME_RE = re.compile(r"(?P<year>\d{4})(?P<period>\d{2})_(?P<code>\d{4})_(?P<kind>[A-Za-z0-9]+)")


def doc_meta(path):
    """從檔名解出 {year, period, code, kind, is_halfyear}。
       檔名不符格式、或期別碼不是 02/04 → 直接 raise ValueError(不猜、不靜默走錯管線)。"""
    name = os.path.basename(path)
    m = _FNAME_RE.search(name)
    if not m:
        raise ValueError(f"檔名不符 YYYYMM_代碼_型別 格式,無法判斷期別:{name}")
    d = m.groupdict()
    if d["period"] not in PERIOD:
        raise ValueError(f"未知期別碼 {d['period']}(僅支援 02半年/04年報):{name}")
    d["is_halfyear"] = PERIOD[d["period"]]
    return d


def is_halfyear(path):
    """半年報?依檔名期別碼判;判不出直接 raise(見 doc_meta)。"""
    return doc_meta(path)["is_halfyear"]


def extract_from_note(cls, note_sub, bs):
    """半年報路由(F):主附註各桶小計 → 正規化成與明細表相同的對帳輸入 → 走同一條 reconcile。
       cost=NA(附註通常無取得成本欄)。逐列 vs 印出合計自證:sum(subtotals)==printed_total。"""
    if not note_sub or not note_sub.get("subtotals"):
        return {"_pass": False, "_error": "半年報主附註讀不到小計", "_source": "note"}
    nsub = {}
    for s in note_sub["subtotals"]:
        nsub[s["bucket"]] = nsub.get(s["bucket"], 0) + s["amount"]
    buckets = {b: {"成本": None, "值": v} for b, v in nsub.items() if b != "調整項"}
    printed = note_sub.get("printed_total")
    recon = printed if printed else sum(nsub.values())
    # 主附註無獨立逐列/合計兩來源自證(printed_total 本身就是唯一輸入)→ internal_ok=None(不擋);
    # 對帳全靠 BS 錨。note 的自證化是 P3 範圍(BASIS 統一 + 共用 reconcile 路徑),P1 不動。
    out = reconcile(recon_fair=recon, bs_anchor=bs,
                    internal_ok=None, buckets=buckets, bucket_cost=None,
                    deriv_fair=nsub.get("調整項", 0), cost_total=None, value_total=recon,
                    source="note")
    out["bucket_sum"] = sum(v for b, v in nsub.items() if b != "調整項")
    return out


_SUB_SCHEMA = {"type": "object", "properties": {
    "subtotals": {"type": "array", "items": {"type": "object", "properties": {
        "bucket": {"type": "string"}, "amount": {"type": "integer"}},
        "required": ["bucket", "amount"]}},
    "printed_total": {"type": "integer", "nullable": True},  # 該科目印出的總計(含衍生)
    "granularity": {"type": "string"}},  # 桶級 / 粗(僅債務/權益層)
    "required": ["subtotals"]}
_SUB_PROMPT = """你在看台灣銀行個體財報「主附註」裡「{cls_name}」的持有明細(段落式,非明細表)。
請讀出它按品類列的各桶金額(當期,日期最新那欄),把品類歸到:{buckets}
{rules}
subtotals:每桶一筆 {{bucket, amount 仟元}}(同桶多列請加總)。
printed_total:該科目**最末印出的整體合計**那個數字(通常是「{cls_name} $ xxx」那行,含衍生金融資產在內)。沒有就 null。
granularity:若只印到「債務工具/權益工具」層、未細分到桶,填「粗」,否則「桶級」。只回 JSON。"""


def read_note_subtotals(path, pages_idx, cls):
    from google.genai import types
    pdf = slice_pdf(path, pages_idx)
    prompt = _SUB_PROMPT.format(cls_name=CLS_NAME[cls], buckets=" / ".join(BUCKETS), rules=BUCKET_RULES)
    resp = _gen(
        model=MODEL, contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=_SUB_SCHEMA))
    return json.loads(resp.text)


# ── 資產負債表:讀【整欄】而非三個孤立數字,讓自己能自證(v3-P1)──
# 一個孤立錨(舊版三數字)讀錯跟讀對長得一模一樣,沒有算術能查。整欄有:
# sum(rows) == 資產總計,精確相等才收;抓錯表/抓錯期/抓到合併報表,加總幾乎必不會平。
_BS_ROWS_SCHEMA = {"type": "object", "properties": {
    "rows": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "amount": {"type": "integer"}},
        "required": ["name", "amount"]}},
    "total_assets": {"type": "integer", "nullable": True},
    "detail": {"type": "string"}}, "required": ["rows"]}
_BS_ROWS_PROMPT = """以下是台灣銀行個體財報的一頁(可能是資產負債表,也可能不是——先判斷)。
若這頁是『資產負債表』:逐列讀出【資產側】每一個科目列(每列一筆 name+amount),只取當期(日期最新那欄),
單位仟元。不要挑,**整個資產側全部列都要**(現金、拆存、金融資產各科目、放款、不動產…全部),
這樣才能用『全列相加 == 資產總計』自我檢查。
最後讀出『資產總計』填 total_assets。
若同一科目被拆成流動(11xxxx)+非流動(12xxxx)兩列,兩列都各自列出(不要先加好)。
只取個體(不取合併)資產負債表那頁;若這頁不是資產負債表,rows 給空陣列、total_assets 給 null。
數字後小整數是百分比不是金額,不要誤讀進 amount。只回 JSON。"""


def read_bs_all(path, pages_idx):
    from google.genai import types
    pdf = slice_pdf(path, pages_idx)
    resp = _gen(
        model=MODEL, contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), _BS_ROWS_PROMPT],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=_BS_ROWS_SCHEMA))
    return json.loads(resp.text)


def _verify_bs_rows(raw):
    """自證條件:資產側全列相加 == 印出的資產總計(精確)。"""
    rows = raw.get("rows") or []
    ta = raw.get("total_assets")
    if not rows or ta is None:
        return False
    return sum(r.get("amount") or 0 for r in rows) == ta


def _classify_bs_row(name):
    """依科目名把一列歸到 Trading/OCI/AC 其一(互斥、不重疊);判不到回 None。"""
    n = re.sub(r"\s", "", name or "")
    if "透過其他綜合損益" in n:
        return "OCI"
    if "透過損益" in n:
        return "Trading"
    if "攤銷後成本" in n:
        return "AC"
    return None


def read_bs_verified(path, pages):
    """定位+讀值+自證合一(取代舊版 locate_bs + check_bs_anchors)。
       grep 命中頁優先試一次讀值自證;沒命中或沒自證 → 逐頁(前 15 頁)個別餵圖直到某頁自證。
       只有『自證過』的頁才拿三類錨,否則三類一律 None(無錨,不是猜的錨)。"""
    n = len(pages)
    order = []
    for i in range(min(40, n)):
        t = re.sub(r"\s", "", pages[i])
        if ("資產總計" in t or "資產合計" in t) and "金融資產" in t:
            order.append(i)
            break
    order += [i for i in range(min(15, n)) if i not in order]
    for i in order:
        try:
            raw = read_bs_all(path, [i])
        except Exception:
            continue
        if _verify_bs_rows(raw):
            out = {"Trading": None, "OCI": None, "AC": None}
            for r in raw.get("rows", []):
                cls = _classify_bs_row(r.get("name"))
                if cls:
                    out[cls] = (out[cls] or 0) + (r.get("amount") or 0)
            out["total_assets"] = raw.get("total_assets")
            return out, [i]
    return {"Trading": None, "OCI": None, "AC": None, "total_assets": None}, []


# ── 合併讀:主附註連頁整塊一次回三類逐桶小計 ──
_SUBALL_SCHEMA = {"type": "object", "properties": {
    cls: {"type": "object", "properties": {
        "subtotals": {"type": "array", "items": {"type": "object", "properties": {
            "bucket": {"type": "string"}, "amount": {"type": "integer"}}, "required": ["bucket", "amount"]}},
        "printed_total": {"type": "integer", "nullable": True},
        "granularity": {"type": "string"}}, "required": ["subtotals"]}
    for cls in ("Trading", "OCI", "AC")}, "required": ["Trading", "OCI", "AC"]}
_SUBALL_PROMPT = """你在看台灣銀行個體財報『主附註』中連續幾頁,含三個科目的持有明細(段落式,非明細表):
- Trading:透過損益按公允價值衡量之金融(工具/資產)
- OCI:透過其他綜合損益按公允價值衡量之金融資產
- AC:按攤銷後成本衡量之債務工具投資
各科目請讀出按品類列的各桶金額(當期,日期最新那欄),把品類歸到:{buckets}
{rules}
每科目:subtotals=每桶一筆{{bucket, amount 仟元}}(同桶多列加總);
printed_total=該科目最末印出的整體合計數字(含衍生金融資產在內,通常是「科目名 $ xxx」那行,沒有給 null);
granularity=只印到債務/權益層填「粗」否則「桶級」。
某科目在這幾頁找不到就給空 subtotals。只回 JSON。"""


def read_subtotals_all(path, pages_idx):
    from google.genai import types
    pdf = slice_pdf(path, pages_idx)
    prompt = _SUBALL_PROMPT.format(buckets=" / ".join(BUCKETS), rules=BUCKET_RULES)
    resp = _gen(
        model=MODEL, contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), prompt],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=_SUBALL_SCHEMA))
    return json.loads(resp.text)


def locate_note_block(pages, path=None):
    """三類主附註連號連頁 → 回涵蓋三者的頁碼區塊(給 read_subtotals_all 一次切)。"""
    loc = locate_notes_all(pages, path)
    hits = [p for cls in ("Trading", "OCI", "AC") for p in (loc.get(cls) or [])]
    if not hits:
        return []
    lo, hi = min(hits), max(hits)
    hi = min(hi + 1, lo + 8)                 # 最多 8 頁,防過切
    return list(range(lo, hi + 1))


def _is_transient(e):
    """速率/逾時/斷線類錯 → 應往上拋交 with_retry 重試,不可被當成『讀不出』吞掉。"""
    m = str(e).lower()
    return any(s in m for s in ("429", "resource_exhausted", "quota", "timed out",
                                "closed", "disconnect", "unreachable", "503", "unavailable"))


# ═══════════ 對帳 ═══════════ (TOL / TOL_REL 來自 config.py)


def _tol(x):
    """統一容差:相對 TOL_REL,下限 TOL。總額動輒千億,絕對值太死;相對容忍 OCR 逐位小誤差。"""
    return max(TOL, int(TOL_REL * abs(x or 0)))


def _tie(a, b):
    """兩數是否對得上(用相對容差,以較大者為基)。"""
    return a is not None and b is not None and abs(a - b) <= _tol(max(abs(a), abs(b)))


# 衍生商品:靠「商品名」認,不靠 section 字面(模型不一定標 section=衍生 → 曾漏計)
_DERIV_WORDS = ("交換", "選擇權", "遠期", "期貨", "換匯", "保證金", "無本金", "NDF", "衍生")
_ADJ_WORDS = ("備抵", "減損", "評價調整", "未攤銷", "應計利息", "溢價", "折價")


def _is_deriv(name, section):
    return "衍生" in (section or "") or any(w in name for w in _DERIV_WORDS)


def _is_adj(bucket, name):
    # 真調整項(要丟掉的):備抵/減損/評價/應計利息/溢價折價/未攤銷;或桶被判為「調整項」且非衍生
    return any(w in name for w in _ADJ_WORDS) or bucket == "調整項"


def reconcile(*, recon_fair, bs_anchor, internal_ok=None,
              buckets=None, bucket_cost=None, deriv_fair=0,
              cost_total=None, value_total=None, cost_internal_ok=None, source="detail"):
    """單一對帳規則(detail / note 共用,v3-P1)。
       訊號:internal(逐列==印出合計)、cross(recon==BS)。
       BS 錨若存在,一定是已自證過的(見 read_bs_verified);沒有『不可靠錨』這回事了——
       錨不是 None 就是已驗證過的數字,對不上就是真的對不上,不再猜誰錯。"""
    buckets = buckets or {}
    if bs_anchor is None:
        cross_ok = None
        weak = True
        # 無外錨:detail 靠 internal 自證;note 無 internal 又無 BS → 零獨立訊號,不收(fail-loud)
        passed = bool(internal_ok) if internal_ok is not None else False
    else:
        cross_ok = _tie(recon_fair, bs_anchor)
        weak = False
        passed = bool(cross_ok) if internal_ok is None else bool(internal_ok and cross_ok)
    return {
        "buckets": buckets,
        "recon_fair": recon_fair, "bucket_cost": bucket_cost, "deriv_fair": deriv_fair,
        "bs_anchor": bs_anchor, "cost_total": cost_total, "value_total": value_total,
        "_internal_ok": internal_ok, "_cost_internal_ok": cost_internal_ok,
        "_cross_ok": cross_ok, "_weak_anchor": weak, "_needs_review": weak,
        "_source": source, "_pass": passed,
    }


def validate(cls, det, bs_anchor):
    """明細表對帳:從 rows 算出全選合計/分桶 → 交給 reconcile。"""
    rows = det.get("rows", [])
    # 對帳「全選」:所有列相加(不挑不排除)= 印出合計 = BS。衍生/調整自然含在內。
    # 分桶只為輸出呈現:衍生、真調整不進「證券種類桶」,但不影響對帳。
    buckets = {}
    bucket_cost = deriv_fair = 0
    sum_all_fair = sum_all_cost = 0
    for r in rows:
        b, name = r.get("bucket") or "", r.get("name", "")
        cost, fair = r.get("cost"), r.get("fair")
        sum_all_fair += fair or 0
        sum_all_cost += cost or 0
        if _is_deriv(name, r.get("section")):
            deriv_fair += fair or 0
            continue
        if _is_adj(b, name):
            continue
        cell = buckets.setdefault(b, {"成本": 0, "值": 0})
        if cost: cell["成本"] += cost; bucket_cost += cost
        if fair: cell["值"] += fair
    ct, vt = det.get("cost_total"), det.get("value_total")
    recon_fair = vt if vt is not None else sum_all_fair
    return reconcile(
        recon_fair=recon_fair, bs_anchor=bs_anchor,
        internal_ok=_tie(sum_all_fair, vt),
        buckets={b: {"成本": c["成本"], "值": c["值"]} for b, c in buckets.items()},
        bucket_cost=bucket_cost, deriv_fair=deriv_fair,
        cost_total=ct, value_total=vt,
        cost_internal_ok=(ct is None or _tie(sum_all_cost, ct)),
        source="detail",
    )


# ═══════════ 逐桶成本證人(plan_v2 第2級:分桶獨立防線)═══════════
# 對帳(總額)對分桶免疫——歸錯桶總額照樣對 BS。唯一獨立的逐桶檢查=拿「同一份文件的另一張表」對:
#   明細表各桶(成本/帳面) ==? 主附註各桶(成本/帳面)   ← 兩張表獨立讀,同基礎
# 只對「兩表定義一致」的硬債桶;排除 其他(衍生歸併不一)、股票(受益憑證邊界)、調整項。
_WITNESS_BUCKETS = ("公債", "公司債", "金融債", "資產基礎", "可轉讓定存單", "貨幣市場")


def bucket_cost_witness(cls, det_buckets, note_sub):
    """明細桶 vs 主附註桶,逐桶對(同基礎)。回 {_mode, checked, mismatch};無主附註→None。
       Trading/OCI:主附註金額=成本,對明細「成本」欄;AC:兩邊皆帳面,對明細「值」欄。"""
    if not note_sub or not note_sub.get("subtotals"):
        return None
    col = "值" if cls == "AC" else "成本"
    nsub = {}
    for s in note_sub["subtotals"]:
        nsub[s["bucket"]] = nsub.get(s["bucket"], 0) + (s.get("amount") or 0)
    checked, mismatch = [], []
    for b in _WITNESS_BUCKETS:
        dc = (det_buckets.get(b) or {}).get(col)
        nc = nsub.get(b)
        if not dc or not nc:            # 有一邊沒值(桶不存在/該欄 NA)→ 無從對,略過
            continue
        checked.append(b)
        if not _tie(dc, nc):
            mismatch.append({"桶": b, "明細表": dc, "主附註": nc})
    return {"_mode": "逐桶成本證人", "checked": checked, "mismatch": mismatch}


# ═══════════ 端到端 ═══════════
def _note_cls(path, pages, cls, bs, note_sub):
    """從主附註抽某類。note_sub=None(年報 fallback)時自行定位讀。
       不再做『同頁重讀』:temperature=0 下無新資訊,只燒配額。"""
    if note_sub is None:
        np0 = locate_note(pages, cls, path)
        note_sub = read_note_subtotals(path, np0, cls) if np0 else None
    return extract_from_note(cls, note_sub, bs)


def extract_all(path, pages=None, loc=None):
    """一份文件三類端到端。路由照檔名期別碼(is_halfyear):半年報→主附註、年報→明細表。
       年報某類明細表定位/讀不到 → 該格 fail(不繞主附註)。
       共用讀:BS一次(3類錨)+(半年報)主附註整塊一次。回 ({cls: 結果}, loc)。"""
    pages = pages or pages_text(path)
    n = len(pages)
    half = is_halfyear(path)
    # 例外:中信「合併」(AI1)年報沒有「重要會計項目明細表」章節,結構同半年報主附註彙總表,
    # 不分半年報/年報一律走主附註路徑。AI3(個體)不受影響,既有分流邏輯不動。
    if doc_meta(path)["kind"] == "AI1":
        half = True
    # 共用讀(各一次):BS 整欄讀值+自證(v3-P1)。沒有頁自證得過 → 該文件所有類均無錨。
    bs_all, bs_pages = read_bs_verified(path, pages)
    # 主附註只在半年報當正源才整塊預讀;年報只有 fallback 到某類時才個別讀
    if half:
        note_pages = locate_note_block(pages, path)
        sub_all = read_subtotals_all(path, note_pages) if note_pages else {}
    else:
        # 年報:主附註不是來源,但整塊預讀一次當「逐桶成本證人」(獨立第二張表驗分桶)。
        note_pages = locate_note_block(pages, path)
        try:
            sub_all = read_subtotals_all(path, note_pages) if note_pages else {}
        except Exception:
            sub_all = {}                # 證人讀失敗絕不擋主流程(分桶對帳仍走明細表)
        if loc is None:
            loc, _ = locate_details(path, pages)
    loc = loc or {}
    out = {}
    for cls in ("Trading", "OCI", "AC"):
        bs = bs_all.get(cls)
        # 半年報路由(F):無本行整體明細表 → 主附註當輸出來源,cost=NA
        if half:
            res = _note_cls(path, pages, cls, bs, sub_all.get(cls))
            res["_meta"] = {"det_pages": None, "bs_pages": bs_pages, "note_pages": note_pages,
                            "total_assets": bs_all.get("total_assets")}
            out[cls] = res
            continue
        # 年報:BS 導向候選(D+E)——列候選、逐個讀到表尾、對 BS 選/湊
        candidates = loc.get(cls) or []
        if not candidates:
            out[cls] = {"_pass": False, "_error": "定位不到明細表頁"}
            continue
        det, mode = select_detail(path, candidates, cls, bs, n_pages=n)
        if det is None:
            out[cls] = {"_pass": False, "_error": "候選都讀不出明細"}
            continue
        res = validate(cls, det, bs)
        # 同頁重讀(temperature=0)無新資訊 → 不做。有新資訊的唯一 fallback=關鍵字重掃擴候選。
        if not res.get("_pass") and bs is not None:
            extra = [p for p in rescan_detail_pages(pages, cls) if p not in candidates]
            if extra:
                det3, mode3 = select_detail(path, sorted(set(candidates) | set(extra)), cls, bs, n_pages=n)
                if det3 is not None:
                    r3 = validate(cls, det3, bs)
                    if r3.get("_pass"):        # 只在重掃後真的對上 BS 才採用,否則保留原判(仍 fail 標人工)
                        det, res, mode = det3, r3, mode3 + "+rescan"
        res["_source"] = "detail"; res["_select_mode"] = mode
        # 保留 validate 判定的弱錨待複核(錨可疑),別被 select_detail 的 needs_review 覆蓋掉 → 取聯集
        res["_needs_review"] = res.get("_needs_review", False) or det.get("_needs_review", False)
        # 逐桶成本證人:明細桶 vs 主附註桶(獨立第二張表)。對不上→示警待複核,不靜默。
        wit = bucket_cost_witness(cls, res.get("buckets", {}), sub_all.get(cls))
        if wit:
            res["_bucket_check"] = wit
            res["_bucket_warn"] = bool(wit["mismatch"])
            if wit["mismatch"]:
                res["_needs_review"] = True
        res["_meta"] = {"det_pages": det.get("_pages"), "bs_pages": bs_pages,
                        "note_pages": note_pages, "header": det.get("header"),
                        "total_assets": bs_all.get("total_assets")}
        out[cls] = res
    return out, loc


if __name__ == "__main__":
    import sys
    fn = sys.argv[1] if len(sys.argv) > 1 else "pdf_cache/202504_5835_AI3.pdf"
    pages = pages_text(fn)
    half = is_halfyear(fn)
    out, loc = extract_all(fn, pages)
    print(f"檔:{fn}  {'半年報' if half else '年報'}  LLM定位:{loc}")
    for cls in ("Trading", "OCI", "AC"):
        r = out.get(cls, {})
        p = "✅PASS" if r.get("_pass") else "❌"
        if r.get("_weak_anchor"):
            p = "~弱錨(待複核)"
        print(f"\n[{cls}] {p}  頁{r.get('_meta',{}).get('det_pages')}")
        if "_error" in r:
            print("   ", r["_error"]); continue
        print(f"   對帳值={r.get('recon_fair')} 成本={r.get('bucket_cost')} BS錨={r.get('bs_anchor')} "
              f"合計={r.get('value_total')} | internal={r.get('_internal_ok')} cross={r.get('_cross_ok')} "
              f"cost_int={r.get('_cost_internal_ok')}")
        print(f"   桶:{ {b: c['值'] for b,c in r.get('buckets',{}).items()} }")
