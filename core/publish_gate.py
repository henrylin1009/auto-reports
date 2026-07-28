# -*- coding: utf-8 -*-
"""B3:把 Decision 的 CONFIRMED/PROVISIONAL/UNCLASSIFIED 狀態接上
`wide.view()` 已經在做的事,**不重寫 `wide.py`**(禁改清單)。

`wide.view()` 今天已經做對一半(`plan_phaseB.md` §5 B3):
    - `buckets.bucket(row) is None` 的列進 `View.unknown`,**留原名與金額**
    - `View.unknown` 非空 ⇒ `View.ok` 為 False(三段恆等式的一部分)
這正是 I4(未知不冒充 OTHER/null,仍參與恆等式檢查)的算術半邊。

B3 補的是**發布狀態半邊**:一格 wide 的算術即使全對(`View.ok`),也不等於
「可發布」——若其中有 Decision 停在 PROVISIONAL(例如 taxonomy 還沒 ratify、
或 B1.5 之後 BUCKET_RULES 又改了導致降級),那一格**已存檔但不可發布**。

`status` 因此拆成兩個數字(`plan_phaseB.md`「已完成」拆成已存檔/可發布):

    archived     facts/ 裡有這一格(不論分不分得出桶、不論 Decision 狀態)
    publishable  archived ∧ 算術三段恆等式成立 ∧ 該格所有列的 Decision 皆 CONFIRMED

**分岔是產出,不是退步。** 36 格今天兩者相等,不代表以後永遠相等。
"""
import buckets
import wide
from core import decision_store
from core import ingest as ingest_mod


def _decisions_for_cell(cell_key, recs, decisions_dir=None, taxonomy_dir="taxonomy"):
    """優先用 `decisions/` 裡已落地的紀錄;沒有就**現算**(不寫檔)——
    這樣舊資料(B2 上線前就在 `facts/` 裡的 36 格)也能算出狀態,
    不必等每一格都真的跑過一次 ingest 才看得到 status。"""
    persisted = decision_store.load(decisions_dir).get(cell_key)
    if persisted:
        return [d for d in persisted if not d.get("superseded")]
    return ingest_mod._decide_rows(cell_key, recs, taxonomy_dir)


def decision_summary(cell_key, recs, decisions_dir=None, taxonomy_dir="taxonomy"):
    """→ {"total", "confirmed", "provisional", "unclassified"}。"""
    decs = _decisions_for_cell(cell_key, recs, decisions_dir, taxonomy_dir)
    out = {"total": len(decs), "confirmed": 0, "provisional": 0, "unclassified": 0}
    for d in decs:
        state = d.get("state")
        if state == "CONFIRMED":
            out["confirmed"] += 1
        elif state == "PROVISIONAL":
            out["provisional"] += 1
        else:
            out["unclassified"] += 1
    return out


def coarse_status(cell_key, recs, decisions_dir=None, taxonomy_dir="taxonomy"):
    """一格 → {"archived", "publishable", "arithmetic_ok", "fully_confirmed",
    "decisions", "reasons"}。**不改 `wide.view()` 的判斷,只轉述它。**"""
    views = wide.cell(recs)
    arithmetic_ok = any(v.ok for v in views.values())
    summary = decision_summary(cell_key, recs, decisions_dir, taxonomy_dir)
    fully_confirmed = summary["total"] > 0 and summary["confirmed"] == summary["total"]

    reasons = []
    if not arithmetic_ok:
        reasons.append("三段恆等式在兩個口徑都不成立(或有未知列)")
    if not fully_confirmed:
        reasons.append(f"{summary['provisional']} 列 PROVISIONAL、"
                        f"{summary['unclassified']} 列 UNCLASSIFIED,尚未全數 CONFIRMED")

    return {
        "archived": True,  # 呼叫端本來就是拿 facts/ 裡已有的 recs 進來
        "arithmetic_ok": arithmetic_ok,
        "fully_confirmed": fully_confirmed,
        "publishable": arithmetic_ok and fully_confirmed,
        "decisions": summary,
        "reasons": reasons,
    }


def status_all(cells, decisions_dir=None, taxonomy_dir="taxonomy"):
    """{cell_key: recs} → {"archived", "publishable", "cells": {cell_key: coarse_status}}。

    **`archived` 恆等於 `len(cells)`**(呼叫端已經是從 `facts.load()` 拿到的東西,
    定義上都在檔案裡)——這個數字擺出來是為了跟 `publishable` 並排對照,
    不是因為它會變。真正會變的是 `publishable`。
    """
    per_cell = {k: coarse_status(k, recs, decisions_dir, taxonomy_dir)
                for k, recs in cells.items()}
    return {
        "archived": len(cells),
        "publishable": sum(1 for v in per_cell.values() if v["publishable"]),
        "cells": per_cell,
    }
