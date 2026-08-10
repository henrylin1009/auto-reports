# -*- coding: utf-8 -*-
"""人工待辦的**單一入口**。S0:把兩個互不相干的佇列合流成一份清單。

在這支之前,待辦分散在兩個地方,而且沒有人同時讀它們:

    core/decision_store.py  →  review/queue.jsonl     (B4 的三種處置)
    fill.py                 →  work/blocked/*.json    (分類表缺口卡住的格)

`core/workbench.py` 只讀第一個。真實資料裡第一個**檔案根本不存在**、第二個
有東西卡著,所以畫面顯示「待審 0」是假的。**畫面全綠而實際卡住,比缺功能危險**
——這是先於任何 UI 工作要修的東西(見 `docs/plan_ui_redesign.md` §五①)。

## 為什麼不讀 work/proposals.jsonl

那是**append-only 的歷史紀錄,不是待辦清單**。它按科目名全域去重地累積每次
BLOCKED 時的提案;某格後來被收錄放行了,提案仍留在檔案裡。實測:8 筆提案
對應的格子只有 1 格還卡著。拿它當待辦會超報。

**待辦的真相是 `work/blocked/*.json`**——那個檔存在就代表那格還卡著,
`fill.py requeue` 放行時會把檔案刪掉。

## 這支不寫,只讀

處置(收錄/退回/擴頁)仍走既有出口:`core.review.dispose_*` 與
`fill.py requeue`。合流只在**讀**的那一側,不動任何寫入路徑——
兩套流程各自的 idempotence 與審計紀錄都不受影響。
"""
import glob
import json
import os

import buckets
from core import decision_store

BLOCKED_GLOB = "work/blocked/*.json"


def _entry(source, cell_key, name, suggested, why, ref):
    """統一形狀。**`suggested` 是 None 就保持 None,不准填一個猜的桶**——
    `fill.py._taxonomy_gap()` 對「沒有任何規則命中」回的就是 None,
    那是「需要人判斷」的訊號,被填掉之後人就看不見了。"""
    return {"source": source, "cell_key": cell_key, "name": name,
            "suggested": suggested, "why": why, "ref": ref}


def _from_blocked(workspace):
    out = []
    for p in sorted(glob.glob(os.path.join(workspace, BLOCKED_GLOB))):
        doc, cls = os.path.basename(p)[:-5].rsplit("__", 1)
        data = json.load(open(p, encoding="utf-8"))
        for g in data.get("proposals") or []:
            out.append(_entry(
                "blocked", f"{doc}|{cls}", g.get("name"), g.get("bucket"),
                g.get("why") or "", {"path": p, "reason": data.get("reason"),
                                     "level": data.get("level")}))
    return out


def _from_review(workspace):
    p = os.path.join(workspace, decision_store.REVIEW_QUEUE)
    out = []
    for e in decision_store.load_review(p):
        dec = e.get("decision") or {}
        out.append(_entry(
            "review", e.get("cell_key"), dec.get("name"), dec.get("mapping"),
            f"state={dec.get('state')}", {"path": p, "decision": dec}))
    return out


def pending(workspace="."):
    """兩個來源合流,**再用 `buckets.SYN` 篩掉已經解決的**。

    ⚠️ **這道篩選是必要的,不是錦上添花**(2026-07-30 實測抓到):`work/blocked/`
    與 `review/queue.jsonl` 是兩份**存下來的快照**,confirm_bucket() 只寫
    `buckets.SYN`,從不回頭改這兩份快照。實測:138 筆裡有 **63 筆(46%)**
    的名字已經在 `buckets.SYN` 裡查得到桶——也就是說,那個名字**已經被人
    裁示過了**,只是存下來的舊佇列檔案沒人去清。

    `buckets.SYN` 才是唯一影響 `data.json` 的來源(`build.py` 的
    `decisions_sha256` 只算 `buckets.py`/`config.py`)。所以「還算不算待辦」
    這件事**用它現算**,不是看快照檔案還在不在——這正是
    `docs/plan_simplify.md` §5「待辦用算的,不用存的」的原則,提前在這裡
    落地一小步,不必等那份計畫的大改動。
    """
    raw = _from_blocked(workspace) + _from_review(workspace)
    return [e for e in raw
            if not (e["name"] and buckets.bucket({"name": e["name"]}) is not None)]


def count(workspace="."):
    """**必須與 `pending()` 同源**。兩個數字各自計算就是下一個假綠燈。"""
    return len(pending(workspace))


def by_cell(workspace="."):
    """{cell_key: [entry, ...]} —— 給總覽畫面在格子上標 ⚠ 用。"""
    out = {}
    for e in pending(workspace):
        out.setdefault(e["cell_key"], []).append(e)
    return out
