# -*- coding: utf-8 -*-
"""L2 —— witness,全部是純函數,零 LLM。

每道都是「同一個數字的兩個獨立來源必須相等」(docs/plan_v4_dump.md §五)。

**2026-08-03 收斂:五道 → 四道,其中只有兩道是硬閘門。**
判準是「人拿原始頁對得出來的,不必當閘門」——最終把關是人對著頁面影像複核,
機器的價值在補上人看不到的那一類(見 `v4/ledger.py:HARD_GATES`):

    提示   check_rowsum / check_anchor / check_page_ref
           抄錯數字、引錯頁、對不上 BS —— 人翻到那一頁就看得到,不判 RED
    硬閘門 check_bucket_complete  有列對不到桶 → 錢從七桶無聲消失
           check_basis            附註成本 vs 明細表取得成本逐桶互證
           兩者都是「每一列都跟紙上一樣、但產出是錯的」,人對圖看不出來

`check_cross_period`(W4)已整支移除,理由見下方 W4 段落。
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

import checks
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
    # **加總語意走 `checks.total_of()`** —— 跟 `transcribe.check_identity`
    # 共用同一份定義(2026-08-10 四份實作收一份,見 checks.py 檔頭)。
    total = checks.total_of([(r.get("name"), r.get("amount")) for r in rows])
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


# ─────────────────────────────── W4(已移除)─────────────────────────
# `check_cross_period` 於 2026-08-03 整支刪除。它原本要做跨期互證(本期的前期欄
# == 前一份的當期欄),但完整版需要 prompt 回報 `prior_total`,在那之前程式**每一條
# 路徑都只回 no_witness** —— 實測 42/42 全是 no_witness,一次都沒有生效過。
#
# 留著它有兩個實害:①每一格的 witness 清單多一行永遠不會亮的字;②它的 docstring
# 宣稱「這樣可以讓只有前三道 OK 的格落進 GREY」,但分流規則其實是 ok>=2 就 GREEN,
# 於是那句話變成一個沒人驗證過的錯誤描述(實測 0 格 GREY 就是反證)。
#
# 要做 W4 就重寫並附上會失敗的測試,不要留一個空殼佔位。
# 舊實作見 git history(commit 前一版的 _prior_doc / _load_parsed / check_cross_period)。


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


# ─────────────────────────────── W6 ───────────────────────────────
def check_basis(book, cost):
    """逐項是成本口徑時,附註的成本 == 明細表取得成本欄的成本(逐桶比對)。

    **這是真的兩個獨立來源**,符合檔頭那句「同一個數字的兩個獨立來源必須相等」:
      來源一 附註逐項(扣掉評價調整那一列)—— `book.rows`
      來源二 重要會計項目明細表的「取得成本」欄 —— `cost.rows`,另一頁、另一張表
    實測兆豐 202504 Trading 兩邊逐桶完全相同(明細表股票 11,743,395
    = 附註 4,727,053+1,104,928+5,911,414),那份對得上才敢說口徑判對了。

    ⚠️ **只在 basis=="成本" 且明細表有成本欄時才有話講**,其餘一律 no_witness ——
    不要為了讓每一格都有一行字而硬湊出恆真的 OK(W4 就是那樣死的)。
    """
    if not book or book.get("rows") is None:
        return {"status": "no_witness", "diff": None}
    agg = adapter.aggregate(book["rows"], book.get("printed_subtotal"))
    if not agg.ok:
        # 桶本身不合格,`check_bucket_complete` 會報,這裡不重複判紅
        return {"status": "no_witness", "diff": None,
                "note": "七桶未通過,口徑無從判定(見 check_bucket_complete)"}
    if agg.basis != "成本":
        return {"status": "no_witness", "diff": None, "note": "逐項即帳面,無成本可互證"}
    if not (isinstance(cost, dict) and cost.get("rows") is not None):
        return {"status": "no_witness", "diff": None,
                "note": "文件未揭露取得成本欄(半年報常態),無第二來源可比"}
    agg_c = adapter.aggregate(cost["rows"], cost.get("total"))
    if not agg_c.ok:
        return {"status": "no_witness", "diff": None,
                "note": f"明細表成本欄自身不合格:{agg_c.reason}"}
    diff = {b: agg.book[b] - agg_c.book[b]
            for b in agg.book if agg.book[b] != agg_c.book.get(b)}
    if diff:
        return {"status": "MISMATCH", "diff": None,
                "note": "附註成本 vs 明細表取得成本逐桶不符:"
                        + "、".join(f"{b} 差 {d:,}" for b, d in diff.items())}
    return {"status": "OK", "diff": 0, "note": "附註成本 == 明細表取得成本(逐桶)"}


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
        cls_data = parsed.get(cls) or {}
        book = cls_data.get("book")
        out[cls] = {
            # 提示(人對原始頁自己看得到,不判 RED —— 見 ledger.HARD_GATES)
            "check_rowsum": check_rowsum(book),
            "check_anchor": check_anchor(book, pages),
            "check_page_ref": check_page_ref(book, pages),
            # 硬閘門(人對原始頁看不出來的那一類)
            "check_bucket_complete": check_bucket_complete(book),
            "check_basis": check_basis(book, cls_data.get("cost")),
        }
    return out


if __name__ == "__main__":
    import json
    import sys

    doc = sys.argv[1]
    result = run_witness(doc)
    print(json.dumps(result, ensure_ascii=False, indent=1))
