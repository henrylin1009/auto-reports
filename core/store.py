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
    """**純內容**雜湊(不含路徑)。Ring 1。

    ⚠️ 2026-08-12 修:原本把路徑也餵進 digest(`h.update(p.encode())`),
    於是**檔案改名就會判定「PDF 換了」** —— 而這道防護的用途明明是
    「內容變了要拒用快取」(見檔頭)。doc id 從 `代碼_AI{n}` 改成
    `銀行名_口徑` 時,67 個 anchors 全部誤報 PDF 被換過,實際上一個位元組
    都沒動。**名字說「內容雜湊」而實作不是,這種不一致本身就是 bug。**

    三個呼叫端都只傳一個路徑;多路徑時仍照路徑排序決定串接次序,
    所以結果是確定的。
    """
    h = hashlib.sha256()
    for p in sorted(paths):
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


def ensure_anchors(doc):
    """新文件第一次歸檔時補上 `anchors/{doc}.json`(2026-08-12,v7 R2-3)。

    **不變量**:`facts/` 有這份 ⇒ `anchors/` 有這份。`core.reconcile.verify_all()`
    無條件 `load_anchors(doc)`,缺了就 `FileNotFoundError` 整支炸掉 —— 而
    `anchors/` 原本只由手動 CLI(`core.cli anchors`)產生,加一家新銀行時
    facts/ 有資料、anchors/ 卻是空的(華南實測,test_ring/test_rulings/test_jobs
    三支同時變紅)。這不該靠人記得跑一個指令來維持。

    ⚠️ **放在這裡而不是 `core/webdata.py`,是因為寫進 facts 的門不只一道。**
    第一版只加在 `webdata.file_cell()` 與 `webdata.ratify()`,實測才發現
    `fill_auto` 真正走的是 `core.ingest._write_facts_and_decisions()` ——
    它直接 `facts.save()`,兩道都繞過。`fill.py` 註解寫的「`file_cell()` 是
    機器寫進事實庫的唯一一道門」**不成立**。收成這一份放在 `build_anchors`
    隔壁,三個呼叫端共用(又一個「一道規則多個實作」)。

    只在檔案不存在時建(要讀 PDF,不必每格重算)。**建不起來不擋歸檔** ——
    資料已經通過驗收了,快取失敗不該讓它退回去,但要印出來讓人看到。
    """
    if os.path.exists(f"{ANCHORS_DIR}/{doc}.json"):
        return False
    try:
        build_anchors(doc)
        return True
    except Exception as e:                     # noqa: BLE001 — 快取失敗不擋歸檔
        print(f"⚠️ anchors/{doc}.json 建立失敗({type(e).__name__}: {e})——"
              f"資料已歸檔,但 reconcile 會跳過這份,"
              f"請手動跑 `python3 -m core.cli anchors`")
        return False


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
