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


def _witness_counts(checks):
    """回傳 (n_ok, n_mismatch, n_no_witness) —— 分流唯一看的東西。"""
    ok = sum(1 for c in checks.values() if c["status"] == "OK")
    bad = sum(1 for c in checks.values() if c["status"] == "MISMATCH")
    nw = sum(1 for c in checks.values() if c["status"] == "no_witness")
    return ok, bad, nw


def classify_cell(doc, cls, checks, book):
    """單一格的分流結果。`checks` 來自 `witness.run_witness`(程式重算過的,
    不是模型自報的)。"""
    ok, bad, nw = _witness_counts(checks)
    if bad > 0:
        status = "RED"
    elif ok >= 2:
        status = "GREEN"
    else:
        status = "GREY"
    return {
        "status": status,
        "witnesses": checks,
        "n_ok": ok, "n_mismatch": bad, "n_no_witness": nw,
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
            continue
        cls_data = parsed.get(cls) or {}
        book = cls_data.get("book")
        checks = checks_all.get(cls, {})
        out[cls] = classify_cell(doc, cls, checks, book)
        out[cls]["cost"] = cls_data.get("cost")
        out[cls]["cost_note"] = cls_data.get("cost_note")
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
    """RED 排最前(按最大差額絕對值降冪),再來 GREY。GREEN/RATIFIED 不進來——
    這是整個 v4 的重點:人只看這個列表,不必逐份點開文件。"""
    red, grey = [], []
    for doc_entry in load_all():
        doc, bank, period = doc_entry["doc"], doc_entry["bank"], doc_entry["period"]
        for cls, c in doc_entry["cells"].items():
            if c["status"] not in ("RED", "GREY"):
                continue
            max_diff = max(
                (abs(w["diff"]) for w in c.get("witnesses", {}).values()
                 if w.get("diff") is not None), default=0)
            row = {"doc": doc, "bank": bank, "period": period, "cls": cls,
                   "status": c["status"], "max_diff": max_diff,
                   "witnesses": c.get("witnesses", {})}
            (red if c["status"] == "RED" else grey).append(row)
    red.sort(key=lambda r: -r["max_diff"])
    return {"red": red, "grey": grey}
