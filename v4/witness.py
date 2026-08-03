# -*- coding: utf-8 -*-
"""L2 —— 六道 witness,全部是純函數,零 LLM。

每道都是「同一個數字的兩個獨立來源必須相等」(docs/plan_v4_dump.md §五)。
輸入是 `v4/reader.py` 存的 raw record(`v4/raw/{doc}.json`),輸出是覆寫過的
checks —— **一律不信模型自報的 status**,這裡重算,模型算對算錯都用程式再驗一次。

held-out 富邦半年報那次證明了為什麼不能信模型自報:BS 頁是空白掃描圖,模型 JSON 裡
`check_anchor` 照樣填 "OK"。所以 W2 這裡看到 BS 頁抽不到文字,一律強制覆寫成
"no_witness",不管 raw 裡寫什麼。
"""
import glob
import os
import re
import locate

from v4 import adapter, reader

CLASSES = ("Trading", "OCI", "AC")


# ─────────────────────────────── W1 ───────────────────────────────
def check_rowsum(book):
    """Σrows == 財報印出的小計。跟模型自己的 check_rowsum 無關,重算一次。

    ⚠️ 「row」要跟 `adapter.aggregate()` 是同一個定義,否則兩道 witness 會
    對同一格吵架:實測 `202302_5843_AI3|Trading` 這裡濾掉合計列前把
    小計/合計/淨額都當資料列加了進去(逐列加總 161,172,100 vs 印出小計
    55,717,136),而 `adapter.normalize_rows()` 早就把這幾個詞濾掉了、加總
    起來是對的。兩套「什麼算一列」不一致不是嚴謹,是各驗各的、誰先跑誰決定
    這格死活——所以在這裡直接借用 adapter 那份唯一的定義。"""
    if not book or book.get("rows") is None or book.get("printed_subtotal") is None:
        return {"status": "no_witness", "diff": None}
    rows, _dropped = adapter.normalize_rows(book["rows"])
    total = sum(r["amount"] for r in rows if r.get("amount") is not None)
    diff = total - book["printed_subtotal"]
    return {"status": "OK" if diff == 0 else "MISMATCH", "diff": diff}


# ─────────────────────────────── W2 ───────────────────────────────
def bs_page_readable(pages, bs_date=None):
    """資產負債表那一頁是否抽得到文字。純文字比對,跟 `locate.basis_of` 判封面
    是同一種機械檢查 —— 不問模型,問 PDF 文字層本身。"""
    for txt in pages:
        s = re.sub(r"\s+", "", txt)
        if "資產負債表" in s and "資產合計" in s and len(s) > 200:
            return True
    return False


def check_anchor(book, pages):
    """小計 == 資產負債表科目。**BS 頁抽不到文字時強制 no_witness,不管模型
    自己填了什麼** —— 這是這支檔案存在的理由,見檔頭。"""
    if not bs_page_readable(pages):
        return {"status": "no_witness", "diff": None}
    if not book or book.get("printed_subtotal") is None or book.get("bs_anchor") is None:
        return {"status": "no_witness", "diff": None}
    diff = book["printed_subtotal"] - book["bs_anchor"]
    return {"status": "OK" if diff == 0 else "MISMATCH", "diff": diff}


# ─────────────────────────────── W3 ───────────────────────────────
def check_page_ref(book, pages):
    """數字字串是否真的出現在模型引用的那一頁。機械 grep,抓「引錯頁」。
    掃描頁(抽不到文字)這道天生失效,一律 no_witness —— 不是失敗,是不適用。"""
    if not book or book.get("total") is None or book.get("page") is None:
        return {"status": "no_witness", "diff": None}
    p = book["page"] - 1  # 模型輸出是 1-based 頁碼
    if not (0 <= p < len(pages)):
        return {"status": "MISMATCH", "diff": None}  # 頁碼超出範圍,肯定是引錯
    page_text = pages[p]
    if len(page_text.strip()) < 50:
        return {"status": "no_witness", "diff": None}  # 該頁是掃描圖,grep 天生失效
    target = f"{book['total']:,}"
    found = target in page_text or str(book["total"]) in re.sub(r"[,\s]", "", page_text)
    return {"status": "OK" if found else "MISMATCH", "diff": None}


# ─────────────────────────────── W4 ───────────────────────────────
# 跨文件互證:本期的合計 == 前一期同份文件的合計(另一次 LLM 呼叫、另一份 PDF)。
# plan_v4_dump.md §五 W4:「本期的前期欄 == 前一份的當期欄 —— 另一份 PDF、另一次呼叫」。
#
# 實作策略:不改 prompt(不要重跑既有 2 份 raw),改用程式路徑:
#   doc 格式 `YYYYMM_CODE_KIND` → 按 YYYYMM 排序 → 找同 CODE+KIND 的前一份 doc,
#   確認其存在(no_witness 若無前一期)。
# 當 prompt 加入 prior_total 欄之後,這裡改為比對具體數值。
# 現階段:有前一期 → no_witness + note(避免誤判 GREEN);無前一期 → no_witness。
# 這樣能正確把「只有三道 witness、前期尚無資料」的格歸 GREY,不混進 GREEN。

def _all_docs_sorted():
    """v4/raw/ 裡所有已讀過的 doc,依 YYYYMM 昇序。"""
    paths = sorted(glob.glob(f"{reader.OUT_DIR}/*.json"))
    return [os.path.basename(p)[:-5] for p in paths]


def _prior_doc(doc):
    """同 CODE_KIND 前一期的 doc 名。找不到回 None。
    doc 格式:YYYYMM_CODE_KIND(如 202504_5843_AI3)。
    以 _ 切,取 [0]=期別、[1]=銀行代碼、[2..]=報表類型 組成 identity key。
    """
    parts = doc.split("_")
    if len(parts) < 3:
        return None
    code, kind = parts[1], "_".join(parts[2:])
    identity = f"{code}_{kind}"
    all_docs = _all_docs_sorted()
    prior = None
    for d in all_docs:
        if d == doc:
            break
        dp = d.split("_")
        if len(dp) >= 3 and f"{dp[1]}_{'_'.join(dp[2:])}" == identity:
            prior = d
    return prior


def _load_parsed(doc):
    """讀 v4/raw/{doc}.json 的 parsed 欄位。找不到回 None。"""
    import json
    import os
    path = os.path.join(reader.OUT_DIR, f"{doc}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("parsed")


def check_cross_period(doc, cls):
    """W4:確認前一期文件存在於 v4/raw/。
    ─── 現階段為「孤證偵測」版 ───────────────────────────────────────────
    完整 W4 需要 prompt 回報 prior_total(本期財報印出的前期欄)才能做數值比對。
    在 prompt 升版之前,這道 witness 只確認「是否有前一期可比」:
      - 有前一期已讀入 → no_witness + note(知道存在,但尚未取到前期欄數值)
      - 無前一期(最早一份或尚未讀入) → no_witness(孤證)
    這樣做使「只有前三道 OK、W4 還沒啟用」的格不會誤跑進 GREEN 區,
    而是落進 GREY(孤證)—— 符合 plan_v4_dump.md §六的語義。
    """
    prior = _prior_doc(doc)
    if prior is None:
        return {"status": "no_witness", "diff": None,
                "note": "最早的一份,或前一期尚未讀入 v4/raw/"}
    prior_parsed = _load_parsed(prior)
    if prior_parsed is None:
        return {"status": "no_witness", "diff": None,
                "note": f"前一期 {prior} parsed 讀取失敗"}
    prior_total = (prior_parsed.get(cls) or {}).get("book", {}).get("total")
    note = (f"前一期 {prior} 存在(total={prior_total:,})" if prior_total is not None
            else f"前一期 {prior} 存在但 total 為 None")
    return {"status": "no_witness", "diff": None, "note": note}


# ─────────────────────────────── W5 ───────────────────────────────
# docs/plan_v5_統一.md P1-2:「有列對不到桶 / Σ七桶≠小計」一定要是硬閘門,
# 不能只活在 `v4/adapter.py` 裡沒人問。這道跟 W1~W4 用同一套 status 詞彙
# (OK/MISMATCH/no_witness),所以直接併進既有的 GREEN/RED 計數 ——
# `MISMATCH` 會讓 `ledger.classify_cell()` 判 RED,不需要另開一條分流規則。
def check_bucket_complete(book):
    """七桶(+衍生/評價調整)是否吃得下這份 book 的每一列、且加總對得上小計。
    跟 `check_rowsum` 的差別:`check_rowsum` 只驗總數,這道驗**每一列都認得**——
    總數對、但其中一列被分桶表吃成 unknown、另一列剛好多出一樣的差額,
    `check_rowsum` 抓不到,這道才抓得到。"""
    if not book or book.get("rows") is None:
        return {"status": "no_witness", "diff": None}
    agg = adapter.aggregate(book["rows"], book.get("printed_subtotal"))
    if agg.ok:
        return {"status": "OK", "diff": 0}
    return {"status": "MISMATCH", "diff": None, "note": agg.reason}


# ─────────────────────────────── 彙整 ───────────────────────────────
# 這是唯一給 L3(分流)用的結果 —— L3 不准再看 raw record 裡模型自己填的 checks。

def run_witness(doc):
    """對一份文件重算全部 witness。回傳 {cls: {check_name: {status, diff, ?note}}}。"""
    import json
    import os

    path = os.path.join(reader.OUT_DIR, f"{doc}.json")
    with open(path, encoding="utf-8") as f:
        doc_json = json.load(f)
    parsed = doc_json.get("parsed")
    if not parsed:
        return None

    pdf_path = os.path.join(reader.PDF_DIR, f"{doc}.pdf")
    with locate.PDFIUM_LOCK:
        pages = reader.pages_text(pdf_path)

    out = {}
    for cls in CLASSES:
        book = (parsed.get(cls) or {}).get("book")
        out[cls] = {
            "check_rowsum": check_rowsum(book),
            "check_anchor": check_anchor(book, pages),
            "check_page_ref": check_page_ref(book, pages),
            "check_cross_period": check_cross_period(doc, cls),
            "check_bucket_complete": check_bucket_complete(book),
        }
    return out


if __name__ == "__main__":
    import json
    import sys

    doc = sys.argv[1]
    result = run_witness(doc)
    print(json.dumps(result, ensure_ascii=False, indent=1))
