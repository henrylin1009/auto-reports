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
from core.webdata import EditError

from v4 import reader, witness

LEDGER_DIR = "v4/ledger"
CLASSES = witness.CLASSES


def _bank_and_kind(doc):
    """`202504_5843_AI3` → ("兆豐", "202504")。純字串解析,不猜。"""
    parts = doc.split("_")
    period = parts[0] if parts else "?"
    code = None
    for p in parts[1:]:
        if p in config.BANKS:
            code = p
    bank = config.BANKS.get(code, code or "?")
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
    """回傳 (n_ok, n_mismatch, n_no_witness)。**注意這是全部 witness 的計數,
    不是分流判準** —— 分流只看 `HARD_GATES`(見 `classify_cell`)。"""
    ok = sum(1 for c in checks.values() if c["status"] == "OK")
    bad = sum(1 for c in checks.values() if c["status"] == "MISMATCH")
    nw = sum(1 for c in checks.values() if c["status"] == "no_witness")
    return ok, bad, nw


def classify_cell(doc, cls, checks, book):
    """單一格的分流結果。`checks` 來自 `witness.run_witness`(程式重算過的,
    不是模型自報的)。

    RED  = 有硬閘門不過(人對原始頁看不出來的那一類,見 `HARD_GATES`)
    GREY = 連 book 都沒有,無從驗起(不是「證據不足」,是「沒有資料」)
    GREEN= 硬閘門都過了 —— 意思是「機器沒有意見」,**不等於這格一定對**,
           最終仍由人對著頁面影像複核。提示類 witness 沒過會照樣顯示在畫面上。
    """
    ok, bad, nw = _witness_counts(checks)
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
        "hard_failed": hard_bad,
        "book": book,
    }


def is_ratified(doc, cls):
    path = os.path.join(LEDGER_DIR, f"{doc}.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return cls in json.load(f)


def ratify(doc, cls, book, by="user"):
    """把一格凍結進帳本。**append-only**:已經 ratified 的格拒絕覆寫,要改
    走 `requeue()` 先撤銷,不准這裡靜靜蓋掉——那等於讓「人工確認過」這件事
    可以被無聲推翻。"""
    import datetime

    os.makedirs(LEDGER_DIR, exist_ok=True)
    path = os.path.join(LEDGER_DIR, f"{doc}.json")
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    if cls in data:
        raise EditError(
            f"{doc}|{cls} 已經 ratified過,帳本是 append-only,"
            f"要改先 requeue() 撤銷,不能直接覆蓋。")
    data[cls] = {"book": book, "by": by,
                 "at": datetime.datetime.now().isoformat(timespec="minutes")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data[cls]


def requeue(doc, cls):
    """撤銷 ratify——人工發現凍結的格其實有錯時的救回口。**顯式操作**,
    不是 classify() 的副作用。"""
    path = os.path.join(LEDGER_DIR, f"{doc}.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if cls not in data:
        return False
    del data[cls]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return True


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


def file_green(docs=None, dry_run=False, refresh=False):
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
        raw_path = os.path.join(reader.OUT_DIR, f"{doc}.json")
        parsed = None
        if os.path.exists(raw_path):
            with open(raw_path, encoding="utf-8") as f:
                parsed = (json.load(f) or {}).get("parsed")
        if not isinstance(parsed, dict):
            parsed = None
        for cls, c in info.items():
            key = f"{doc}|{cls}"
            if c.get("status") not in ("GREEN", "RATIFIED"):
                skipped.append((key, c.get("status")))
                continue
            if key in existing and not (refresh and _filed_by_v4(cells_now[key])):
                skipped.append((key, "facts/ 已有(不覆蓋)"))
                continue
            blk = (parsed or {}).get(cls)
            if not isinstance(blk, dict):
                skipped.append((key, "raw 讀不到這一格"))
                continue
            recs = adapter.to_facts_records(doc, cls, blk, (parsed or {}).get("bs_date"))
            if not recs:
                skipped.append((key, "轉不出 record"))
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
