# -*- coding: utf-8 -*-
"""facts/ anchors/ taxonomy/ ledger 讀寫 + 雜湊。Ring 0/1 邊界模組
(plan_clean_core.md §2.1):`build_anchors`/`verify_anchors` 是 Ring 0
(讀 pdf_cache/、呼叫 `locate.locate`);`load_anchors`/`anchor_of` 是 Ring 1
(只讀 anchors/ 的 json,**不准 import pypdfium2,不准開 PDF**)。

anchors/{doc}.json schema:
    {
     "doc": "...", "pdf_sha256": "...", "bs_page": 12, "located_by": "locate.locate",
     "cells": {"Trading": {"amount": 9082587, "pages": [31, 135]}, ...}
    }

**過期防護**:`load_anchors()` 比對 `pdf_sha256` 與現場 PDF;PDF 換了就 raise
拒絕使用,不准自動重算。若 `pdf_cache/` 不存在(Ring 1 測試會把它改名),
則跳過比對直接用快取 —— 純層本來就不該依賴 PDF 在不在。
"""
import glob
import hashlib
import json
import os

import facts as _facts

ANCHORS_DIR = "anchors"
PDF_DIR = "pdf_cache"


def sha256_of(*paths):
    """內容雜湊。Ring 1。"""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode())
        h.update(open(p, "rb").read())
    return h.hexdigest()


# ── Ring 0:產生 anchors(讀 PDF) ────────────────────────────────────────

def build_anchors(doc):
    """呼叫 `locate.locate()`,寫 `anchors/{doc}.json`。**不改 locate**。Ring 0。"""
    import locate
    path = f"{PDF_DIR}/{doc}.pdf"
    loc = locate.locate(path)
    obj = {
        "doc": doc,
        "pdf_sha256": sha256_of(path),
        "bs_page": loc.bs_page,
        "located_by": "locate.locate",
        "cells": {cls: {"amount": amt, "pages": pages}
                  for cls, amt, pages in loc.cells()},
    }
    os.makedirs(ANCHORS_DIR, exist_ok=True)
    json.dump(obj, open(f"{ANCHORS_DIR}/{doc}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    return obj


def verify_anchors(docs=None):
    """重新推導全部並逐項比對,不符就列出差異。回傳差異清單(空 = 全部相符)。Ring 0。"""
    docs = docs if docs is not None else [
        os.path.splitext(os.path.basename(p))[0]
        for p in sorted(glob.glob(f"{ANCHORS_DIR}/*.json"))]
    diffs = []
    for doc in docs:
        stored = json.load(open(f"{ANCHORS_DIR}/{doc}.json", encoding="utf-8"))
        fresh = build_anchors_dry(doc)
        if stored != fresh:
            diffs.append((doc, stored, fresh))
    return diffs


def build_anchors_dry(doc):
    """跟 build_anchors 一樣重新推導,但不寫檔 —— 給 verify 用,避免比對時的
    副作用把「驗證」變成「順便重建」。"""
    import locate
    path = f"{PDF_DIR}/{doc}.pdf"
    loc = locate.locate(path)
    return {
        "doc": doc,
        "pdf_sha256": sha256_of(path),
        "bs_page": loc.bs_page,
        "located_by": "locate.locate",
        "cells": {cls: {"amount": amt, "pages": pages}
                  for cls, amt, pages in loc.cells()},
    }


# ── Ring 1:只讀 anchors/ 的 json ────────────────────────────────────────

def load_anchors(doc):
    """只讀 json。**不准 import pypdfium2,不准開 PDF**。Ring 1。

    過期防護:比對 `pdf_sha256` 與現場 PDF;PDF 換了就 raise。
    `pdf_cache/` 不存在時(Ring 1 測試把它改名)跳過比對,直接信任快取
    —— 純層不依賴 PDF 在不在。
    """
    obj = json.load(open(f"{ANCHORS_DIR}/{doc}.json", encoding="utf-8"))
    pdf_path = f"{PDF_DIR}/{doc}.pdf"
    if os.path.isdir(PDF_DIR) and os.path.exists(pdf_path):
        got = sha256_of(pdf_path)
        if got != obj["pdf_sha256"]:
            raise ValueError(
                f"anchors/{doc}.json 的 pdf_sha256 與現場 PDF 不符 —— PDF 換了。"
                f"拒絕使用,不自動重算。記錄={obj['pdf_sha256']} 現場={got}")
    return obj


def anchor_of(doc, cls):
    """→ int 或 None。Ring 1。"""
    obj = load_anchors(doc)
    cell = obj["cells"].get(cls)
    return cell["amount"] if cell else None


# ── facts/ 讀寫,包 facts.load/save ──────────────────────────────────────

def load_facts():
    """Ring 1。"""
    return _facts.load()


def save_facts(cells):
    """Ring 0。"""
    return _facts.save(cells)
