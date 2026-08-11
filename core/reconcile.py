# -*- coding: utf-8 -*-
"""判定層。核心動作只有一件:讓判定層吃「錨值整數」,不吃 `Located`。

`transcribe.verify(recs, loc)` 對 `loc` 的全部用途是 `check_anchor()` 裡的
`loc.anchors.get(rec["class"])`。所以這裡只寫一個最小 adapter,讓判定層可以
吃 `anchors/*.json`(零 PDF),而不必每格重解析一份 139~200 頁的 PDF。

Ring 1:**只 `from transcribe import ...`,不把六道檢查抄過來整理。**
拆 `transcribe.py` 這個 god module 是另一步,綁在一起會讓等價閘門分不出
差異是搬家還是拆分。
"""
import json
import os

import transcribe
import wide
from core import closure, store

OUT_DIR = "out"


class _Anchors:
    """只暴露 transcribe 真正用到的那一個屬性。**不要繼承 Located,不要補其他方法**
    —— 多補一個方法,就多一條讓 PDF 依賴偷偷回來的路。"""

    def __init__(self, mapping):
        self.anchors = mapping  # {"Trading": 9082587, ...}


def verdict_of(cell_key, recs, anchors_mapping):
    """(cell_key, recs, anchors_mapping) → Verdict dict。純函數。

    逐欄照抄 `results.build()` 現在算的東西,一個欄位都不准加減、不准改名 ——
    這是 E2 等價閘門要比對的內容。
    """
    fallback = anchors_mapping.get(recs[0]["class"])
    anchor, anchor_mismatch = closure.merge_anchor(recs, fallback)
    anchors = _Anchors(anchors_mapping)
    ok, checks = transcribe.verify(recs, anchors, anchor=anchor)
    # `wide.py` 心智模型是「一份 record 就是一整張表」,不認章節模式的母表/子附註
    # 樹狀結構 —— 2026-07-31 起先用 `core.closure.flatten()` 把樹攤平成它認得的
    # 單根單份形狀再交給它。攤不平(ok=False)就不必攤,views 本來就全部被
    # `if ok else None` 蓋掉,攤平失敗的錯誤已經在 `checks["④合計==錨(整格拼樹)"]`
    # 裡了,不必在這裡重複處理。
    flat = recs
    if ok:
        flat, flat_err = closure.flatten(recs, fallback)
        if flat_err:
            ok, flat = False, recs
    views = wide.cell(flat)
    return {
        "doc": recs[0]["doc"], "class": recs[0]["class"], "pass": ok,
        "wide": views["帳面"].book if ok and views["帳面"].ok else None,
        "wide_cost": views["成本"].book if ok and views["成本"].ok else None,
        "side": {b: views["帳面"].side.get(b) for b in wide.SIDE} if ok else None,
        "others": views["帳面"].others if ok else [],
        "anchor": anchor,
    }, {
        "sources": [{"page": r["source_page"], "kind": r.get("source_kind"),
                     "rows": len(r["rows"]), "basis": __import__("buckets").basis_of(r)}
                    for r in recs],
        "checks": {k: (v if v else "通過") for k, v in checks.items()},
        "pass": ok,
        "anchor_mismatch": anchor_mismatch,
        "basis_gap": {b: v.reason for b, v in views.items() if v.book is None},
        "unknown": [{"name": n, "amount": a, "why": w}
                     for v in views.values() for n, a, w in v.unknown],
    }


def verify_all(cells, store_mod=store):
    """{格: recs} → {格: Verdict}。零 PDF —— anchors 由 `core.store.anchor_of` 供應。

    `out/` 只准寫,不准任何程式讀回來(R-A)。這支不讀 `out/`。
    """
    verdict, audit = {}, {}
    for key, recs in cells.items():
        doc = recs[0]["doc"]
        anchors_obj = store_mod.load_anchors(doc)
        mapping = {cls: c["amount"] for cls, c in anchors_obj["cells"].items()}
        verdict[key], audit[key] = verdict_of(key, recs, mapping)
    return verdict, audit


def dump(verdict, audit):
    """寫 out/verdict.json 與 out/audit.json。**只准寫,不准任何程式讀回來**(R-A)。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, obj in (("verdict", verdict), ("audit", audit)):
        json.dump(obj, open(f"{OUT_DIR}/{name}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
