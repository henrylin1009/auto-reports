# -*- coding: utf-8 -*-
"""L3 分流 + L4 帳本(docs/plan_v4_dump.md §六)。

分流用 witness **計數**,不用信心分數——分數會引來閾值,閾值會引來調參,
調參正是 v3 那 14 個靜默 bug 的溫床。

    GREEN  ≥2 道獨立 witness 通過,0 道失敗   → 直通,人不用看
    RED    ≥1 道失敗                         → 進複核台,附打架的來源與差額
    GREY   0 道失敗,但 witness < 2(孤證)     → 抽樣看,不是全看

帳本是 append-only:`ratify()` 把一格凍結,之後 `classify()` 一律回報該格的
凍結值,不再重算——**這是快取機制,不是另一套邏輯**,凍結值就是 ratify 當下
的 book,沒有獨立公式。
"""
import glob
import json
import os

import buckets
import config
import docid
from core.webdata import EditError

from v4 import reader, witness

LEDGER_DIR = "v4/ledger"
CLASSES = witness.CLASSES


def _bank_and_kind(doc):
    """`202504_兆豐_個體` → ("兆豐", "202504")。純字串解析,不猜。

    解析走 `docid.parse()`(唯一入口);認不得的名字回 ("?", "?") 而不是
    硬湊 —— 這個回傳值只拿來顯示,顯示「?」比顯示一個像模像樣的錯名字好。
    """
    try:
        period, bank, _ = docid.parse(doc)
    except docid.BadDocId:
        return "?", "?"
    return bank, period


def _basis_of_book(book):
    """這份 book 的逐桶口徑。判準與 `adapter.aggregate()` 完全同一條
    (有評價調整列 ⇒ 逐項是成本),只是這裡不需要真的攤成七桶。
    回傳 "成本" / "公允",book 形狀不對時回 None(不猜)。"""
    if not isinstance(book, dict) or not isinstance(book.get("rows"), list):
        return None
    from v4 import adapter
    return "成本" if any(
        adapter.is_adjustment_row({"name": r.get("name") or "",
                                    "group": r.get("group") or ""})
        for r in book["rows"] if isinstance(r, dict)) else "公允"


#: **硬閘門 —— 只有這些不過才判 RED。**(2026-08-03 裁示,五道收成三道)
#:
#: 判準是一句話:**人拿原始頁對得出來的,不必當閘門;人對不出來的,才必須擋。**
#: 最終把關是人對著頁面影像複核,機器的價值在於補上人看不到的那一類,
#: 而不是把人已經會做的事再做一遍、順便製造一堆要人處理的 RED。
#:
#:   check_bucket_complete  有列對不到桶 → 那筆錢會從七桶裡無聲消失。
#:                          數字印在紙上、逐列都對,人打勾放行也看不出來
#:                          (實測:買入國庫券 16.3 億、CMO 45.4 億)。
#:   check_basis            成本口徑的七桶被當帳面發布。每一列都跟紙上一樣,
#:                          錯的是它落在 wide 還是 wide_cost(實測 20 格)。
#:
#: 其餘降級成**提示**(照樣算、照樣顯示,但不判 RED):
#:   check_rowsum   Σ列≠小計 —— 抄錯數字,人對圖一眼就看到
#:   check_page_ref 合計不在引用頁 —— 引錯頁,人對圖一眼就看到
#:   check_anchor   小計≠BS錨 —— 人翻得到 BS 那頁自己對
#:
#: `check_cross_period` 已整支移除:42/42 全是 no_witness,程式每條路徑都只回
#: no_witness(在等 prompt 升版報 prior_total)。留著它只是讓每一格的 witness
#: 清單多一行永遠不會亮的字。要做 W4 就重寫,不要留一個空殼佔位。
HARD_GATES = ("check_bucket_complete", "check_basis")


def _witness_counts(checks):
    """回傳 (n_ok, n_mismatch, n_no_witness, n_unbucketed)。**注意這是全部
    witness 的計數,不是分流判準** —— 分流只看 `HARD_GATES`(見 `classify_cell`)。

    `UNBUCKETED`(v9)自己一個計數,**不併進 n_ok 也不併進 n_mismatch** ——
    它兩者都不是:抄寫是對的(所以不是 mismatch),但還有列沒歸桶(所以不是
    全過)。併進任何一邊都會讓畫面把兩種不同的狀況顯示成同一種。
    """
    ok = sum(1 for c in checks.values() if c["status"] == "OK")
    bad = sum(1 for c in checks.values() if c["status"] == "MISMATCH")
    nw = sum(1 for c in checks.values() if c["status"] == "no_witness")
    ub = sum(1 for c in checks.values() if c["status"] == "UNBUCKETED")
    return ok, bad, nw, ub


def classify_cell(doc, cls, checks, book):
    """單一格的分流結果。`checks` 來自 `witness.run_witness`(程式重算過的,
    不是模型自報的)。

    RED  = 有硬閘門不過(人對原始頁看不出來的那一類,見 `HARD_GATES`)
    GREY = 連 book 都沒有,無從驗起(不是「證據不足」,是「沒有資料」)
    GREEN= 硬閘門都過了 —— 意思是「機器沒有意見」,**不等於這格一定對**,
           最終仍由人對著頁面影像複核。提示類 witness 沒過會照樣顯示在畫面上。
    """
    ok, bad, nw, ub = _witness_counts(checks)
    # **只有 MISMATCH 判 RED。** `UNBUCKETED`(v9)不在此列 —— 那是字典缺字,
    # 待辦是點一個下拉,不是重抄;判 RED 的話使用者會去重抄,而重抄必然撞
    # 同一道(失敗點在模型下游)。見 `docs/plan_v9_不擋人.md` §一。
    hard_bad = [g for g in HARD_GATES
                if (checks.get(g) or {}).get("status") == "MISMATCH"]
    if hard_bad:
        status = "RED"
    elif not book or book.get("rows") is None:
        status = "GREY"
    else:
        status = "GREEN"
    return {
        "status": status,
        "witnesses": checks,
        "n_ok": ok, "n_mismatch": bad, "n_no_witness": nw,
        "n_unbucketed": ub,
        "hard_failed": hard_bad,
        # 未歸桶的總額 —— 給畫面直接顯示,不必自己去 witness 裡挖
        # (「錢要看得見」在每一層都要成立,不是只有複核台那一頁)。
        "unbucketed": (checks.get("check_bucket_complete") or {}).get("unbucketed", 0),
        "book": book,
    }


def is_ratified(doc, cls):
    path = os.path.join(LEDGER_DIR, f"{doc}.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return cls in json.load(f)


# ── 沒有 ratify() / requeue() 了 ──────────────────────────────────────────
# 2026-08-11(`docs/plan_v6_一台機器.md` R0-3)退場。**不要加回來。**
#
# 這裡原本有一支 `ratify()`,把一格凍結進 `v4/ledger/`;而 `core/webdata.ratify()`
# 做同一件事,寫進 `facts/`。**一件事兩個實作,而且落在兩個不同的地方** ——
# 於是「人確認過了」這個事實會因為你按的是哪一顆按鈕而存到不同的檔案裡,
# 兩邊互不知道。R0-4 砍掉 `build.rebuild_v4()` 之後,寫進 `v4/ledger/` 的
# 那一份**完全不影響發布**,那顆按鈕就變成純粹的謊言。
#
# 現在只有一個 ratify:`core/webdata.ratify()`,寫 `facts/`、蓋 `_src`、
# append-only(人工裁示過的格不准被機器無聲覆蓋,見 `test_ratify_guard.py`)。
# v4 複核頁的「我看過原始頁,照這樣歸檔」改走 `records_of()` → 那一支。


def records_of(doc, cls):
    """v4 的一格 → `facts/` 的 records。取不到回 `[]`。

    抽出來是因為兩個呼叫端要用同一份轉換:`file_green()`(機器自動歸檔)
    與 `/api/v4/ratify`(人按下去歸檔)。**兩邊不准各自轉一次** ——
    那正是這個檔案上面那段註解在講的事。
    """
    from v4 import adapter

    raw_path = os.path.join(reader.OUT_DIR, f"{doc}.json")
    if not os.path.exists(raw_path):
        return []
    with open(raw_path, encoding="utf-8") as f:
        parsed = (json.load(f) or {}).get("parsed")
    if not isinstance(parsed, dict):
        return []
    blk = parsed.get(cls)
    if not isinstance(blk, dict):
        return []
    return adapter.to_facts_records(doc, cls, blk, parsed.get("bs_date")) or []


def classify(doc):
    """一份文件三格的分流結果。ratified 過的格直接回凍結值,不重算
    witness(帳本本身就是快取,見檔頭)。"""
    raw_path = os.path.join(reader.OUT_DIR, f"{doc}.json")
    if not os.path.exists(raw_path):
        return None
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    parsed = raw.get("parsed")
    if not parsed:
        return None

    ledger_path = os.path.join(LEDGER_DIR, f"{doc}.json")
    frozen = {}
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            frozen = json.load(f)

    # 三類都 ratify 過就不必重抽 PDF 重算 witness——docstring 講的「帳本本身
    # 就是快取」原本沒兌現(這裡以前無條件先跑 run_witness),ratify 越多格
    # 越沒省到。全 reader.pages_text() 有 LRU 保底,這裡是再省一次全跳過。
    if all(cls in frozen for cls in CLASSES):
        checks_all = {}
    else:
        checks_all = witness.run_witness(doc) or {}
    out = {}
    for cls in CLASSES:
        if cls in frozen:
            out[cls] = {"status": "RATIFIED", "book": frozen[cls]["book"],
                         "ratified_by": frozen[cls]["by"], "ratified_at": frozen[cls]["at"]}
        else:
            cls_data = parsed.get(cls) or {}
            book = cls_data.get("book")
            checks = checks_all.get(cls, {})
            out[cls] = classify_cell(doc, cls, checks, book)
            out[cls]["cost"] = cls_data.get("cost")
            out[cls]["cost_note"] = cls_data.get("cost_note")
        # 逐桶口徑要讓複核的人看得到 —— 「這格的帳面是 null」不是出錯,是文件
        # 真的沒揭露逐桶帳面(只印了一整筆評價調整)。畫面上不講的話,人只會
        # 看到網站少一塊數字卻不知道為什麼。RATIFIED 的格也要算(它一樣會發布)。
        _b = out[cls].get("book")
        out[cls]["basis"] = _basis_of_book(_b)
    return out


def get_cell(doc, cls):
    """取得單一格的分流與帳本結果。找不到則回傳 None。"""
    cells = classify(doc)
    return cells.get(cls) if cells else None


def load_all():
    """`v4/raw/` 裡每一份已讀過的文件,分流結果 + 銀行/期別標籤。
    這是 overview 頁與 review queue 共用的底層資料。"""
    out = []
    for path in sorted(glob.glob(os.path.join(reader.OUT_DIR, "*.json"))):
        doc = os.path.basename(path)[:-5]
        cells = classify(doc)
        if cells is None:
            continue
        bank, period = _bank_and_kind(doc)
        out.append({"doc": doc, "bank": bank, "period": period, "cells": cells})
    return out


def review_queue():
    """人的工作清單,三段:

        red   硬閘門不過 —— **擋著不發布**,一定要處理
        grey  連 book 都沒有,無從驗起
        hint  硬閘門過了(所以會發布),但有提示類 witness 沒過 —— 建議看一眼

    第三段是 2026-08-03 收斂 witness 時補的,而且**非補不可**:那次把
    rowsum/anchor/page_ref 從閘門降成提示,7 格因此從 RED 變成 GREEN 直接發布。
    如果佇列只列 RED/GREY,這 7 格會publish 而且**不出現在任何清單上**——
    沒有人會再看它們一眼。降級的前提是「人對原始頁複核得到」,那就必須有一份
    清單告訴人要看哪幾格,否則降級等於靜靜放行。
    """
    red, grey, hint = [], [], []
    for doc_entry in load_all():
        doc, bank, period = doc_entry["doc"], doc_entry["bank"], doc_entry["period"]
        for cls, c in doc_entry["cells"].items():
            checks = c.get("witnesses", {}) or {}
            max_diff = max(
                (abs(w["diff"]) for w in checks.values()
                 if w.get("diff") is not None), default=0)
            row = {"doc": doc, "bank": bank, "period": period, "cls": cls,
                   "status": c["status"], "max_diff": max_diff,
                   "witnesses": checks}
            if c["status"] == "RED":
                red.append(row)
            elif c["status"] == "GREY":
                grey.append(row)
            else:
                soft = [w for w, v in checks.items()
                        if v.get("status") == "MISMATCH" and w not in HARD_GATES]
                if soft:
                    hint.append({**row, "soft_failed": soft})
    red.sort(key=lambda r: -r["max_diff"])
    hint.sort(key=lambda r: -r["max_diff"])
    return {"red": red, "grey": grey, "hint": hint}


def _filed_by_v4(recs):
    """這格現在的內容是不是 v4 自己寫進去的(而不是 v3 抄的、也不是人改的)。
    判準只看 `_by.via`,不猜 —— 人改過的列帶 `_src`,而 `file_cell()` 本身
    還有 append-only 守衛擋人工裁示過的格,這裡不重複那道判斷。"""
    return bool(recs) and all(
        (r.get("_by") or {}).get("via") == "v4/reader" for r in recs)


def file_green(docs=None, dry_run=False, refresh=False, force=False, classes=None):
    """把分流為 **GREEN / RATIFIED** 的格歸檔進 `facts/`。

    這是 A-1 接縫的**使用端**(docs/plan_工具化.md 階段 A):在此之前 v4 的資料
    只活在 `v4/raw` + 本帳本裡,靠 `build.rebuild_v4()` 另開一條讀取路徑才進得了
    網站。現在改成一律先落進 `facts/`,`build.py` 因此只需要一條讀取路徑。

    **只吃 GREEN/RATIFIED,RED 一律不填** —— 與 `build.rebuild_v4()` 原本的
    判準一字不差,所以這次遷移不會讓任何現在沒發布的東西冒出來。RED 是
    「有 witness 失敗、要人看」,它該留在複核台,不是靜靜進事實庫。

    **已經在 `facts/` 裡的格跳過,不覆蓋** —— `build.pick()` 一向是 v3 優先
    (v3 coverage 遠大於 v4),而 `file_cell()` 是整格替換;不跳過就會把 v3
    抄好的內容換成 v4 的,那不是合併是取代。

    人工裁示過的格由 `file_cell()` 自己擋(append-only),這裡不重複判斷。

    `refresh=True` 時,**`facts/` 裡已經是 v4 自己寫的那些格會重新寫一次** ——
    給的是 adapter 改版後的新形狀(例如補上 `bs_anchor`)。v3 抄的格、人改過的
    格一律不碰:重寫自己寫過的東西是更新,重寫別人寫的東西是取代。

    `force=True` 時**連別人寫的格也覆蓋** —— 2026-08-12 加,給網頁上的
    「重抄」按鈕用。**理由**:那顆按鈕的確認框明講「現有內容會被覆蓋
    (舊版存進 work/history/)」,而使用者按了確認。上面那條「不覆蓋」是為了
    防止批次遷移時 v4 靜靜取代 v3 的資料 —— **它防的是機器自作主張,不是
    使用者明確要求**。沒有這個參數的話,重抄會讀完 PDF、算完 witness,然後
    靜靜丟掉結果,而 UI 因為那格狀態仍是 `done` 還顯示「✓ 抄列完成」
    (實測:`202402_玉山_個體|OCI` 停在 7/29 的 gemini 資料,重抄多次都沒變)。

    ⚠️ **人工裁示過的格仍然擋著** —— 那道 append-only 保護在 `file_cell()`
    自己身上(帶 `_src` 的格機器不准覆蓋),`force` 不會、也不該穿透它。

    `classes=[...]` 限定只歸檔這幾類。**跟 `force` 是一組的**:網頁上按的是
    「重抄 這一格」,確認框列的也只有這一格的人工列,但 v4 的 reader 一次讀
    整份文件、`classify()` 一次回三類 —— 不限定的話按一次 OCI 會把 Trading
    跟 AC 也一起覆蓋掉,而那兩格使用者從來沒確認過。爆炸半徑要等於確認框
    講的範圍。
    """
    import facts as facts_mod
    from core import webdata
    from v4 import adapter

    cells_now = facts_mod.load()
    existing = set(cells_now)
    targets = docs if docs is not None else [e["doc"] for e in load_all()]
    filed, skipped, blocked = [], [], []
    for doc in targets:
        # `classify()` 直接回 `{cls: 分流}`,沒有外層 "cells" —— 那層是
        # `load_all()` 才包上去的。
        info = classify(doc) or {}
        for cls, c in info.items():
            if classes is not None and cls not in classes:
                continue
            key = f"{doc}|{cls}"
            if c.get("status") not in ("GREEN", "RATIFIED"):
                skipped.append((key, c.get("status")))
                continue
            if key in existing and not force and not (refresh and _filed_by_v4(cells_now[key])):
                skipped.append((key, "facts/ 已有(不覆蓋);這是批次歸檔的保護,"
                                     "要覆蓋請用網頁上的「重抄」(會帶 force)"))
                continue
            # 轉換走 `records_of()` —— 跟 `/api/v4/ratify` 同一支,不各自轉一次。
            recs = records_of(doc, cls)
            if not recs:
                skipped.append((key, "raw 讀不到這一格 / 轉不出 record"))
                continue
            if dry_run:
                filed.append(key)
                continue
            try:
                webdata.file_cell(doc, cls, recs, via="v4/reader")
                filed.append(key)
            except webdata.EditError as e:
                blocked.append((key, str(e).splitlines()[0]))
    return {"filed": filed, "skipped": skipped, "blocked": blocked}
