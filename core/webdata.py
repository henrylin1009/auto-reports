# -*- coding: utf-8 -*-
"""複核台的**資料層**:純函式,不碰 HTTP、不碰任何 UI 框架。

`server.py` 只負責把這裡的回傳值轉成 JSON。這樣切的理由不是潔癖 ——
UI 換過兩次了(Streamlit → 自刻網站),每換一次都重寫一遍取數邏輯,
就是每換一次都要重驗一遍「35 已抄 / 90 可抄」對不對。

⚠️ **`source_page` 存的是 0-based**,與 `locate.Located.pages` 的候選頁
直接對應,不是印在紙上的頁碼。這點踩過一次(抄列模板 +1、核對讀值 -1,
兩邊都錯),所以在這裡集中處理,呼叫端一律不要自己加減。
"""
import datetime
import glob
import json
import os

import buckets
import config
import facts as facts_mod
import fill
import locate
from core import queue as queue_mod

#: 只做 2023+。≤2022 那些四大表被掃成影像、文字層沒有科目代碼,定位不到,
#: 且已裁示不在範圍內(docs/plan_ui_redesign.md §一裁示①)。
CUTOFF_YEAR = 2023


def docs_in_scope():
    return sorted(d for d in fill._all_docs() if int(d[:4]) >= CUTOFF_YEAR)


def split_doc(doc):
    """`202504_5847_AI3` → (`202504`, `5847`, `AI3`)。"""
    period, bank, code = doc.split("_")
    return period, bank, code


def cell_status(cells, blocked_keys, index, doc, cls):
    """一格(文件 × 類別)的四種狀態。`na` = 錨讀不到或無候選頁;2023+ 的基準
    是 0,但欄位仍保留 —— 假設會過期,沉默地跳過比顯示 `na` 危險。"""
    key = f"{doc}|{cls}"
    if key in cells:
        return "done"
    if key in blocked_keys:
        return "blocked"
    if index["cells"].get(doc, {}).get(cls):
        return "todo"
    return "na"


def overview():
    """矩陣:期別(列) × 銀行+代碼(欄)。**代碼集合從資料推導,不寫死列舉** ——
    寫死過兩次,兩次都讓某一份檔無聲消失(先漏 AI1、修完又漏 AI2)。"""
    cells = facts_mod.load()
    blocked_keys = set(queue_mod.by_cell())
    index = fill._load_index()
    docs = docs_in_scope()

    periods = sorted({split_doc(d)[0] for d in docs}, reverse=True)
    cols = sorted({split_doc(d)[1] + " " + split_doc(d)[2] for d in docs})

    grid, stats = {}, {"done": 0, "todo": 0, "blocked": 0, "na": 0}
    for doc in docs:
        period, bank, code = split_doc(doc)
        states = {}
        for cls in locate.CLASSES:
            s = cell_status(cells, blocked_keys, index, doc, cls)
            states[cls] = s
            stats[s] += 1
        grid[f"{period}|{bank} {code}"] = {"doc": doc, "classes": states}

    return {"periods": periods, "cols": cols, "grid": grid, "stats": stats}


def cell_detail(key):
    """一格已抄好的內容,給核對畫面用。每列附上算好的桶,
    `bucket=None` 代表分類表沒收錄(**不准填「其他」頂替** —— 「其他」是
    表上真的存在的科目,拿來當「不知道」的收容所會讓錯誤看起來像正常值)。"""
    cells = facts_mod.load()
    if key not in cells:
        return None
    doc, cls = key.split("|", 1)
    loc = locate.locate(f"pdf_cache/{doc}.pdf")

    records = []
    for rec in cells[key]:
        rows = []
        for row in rec["rows"]:
            rows.append({
                "name": row["name"],
                "group": row.get("group") or "",
                "value": row["cols"].get(rec["total_col"]),
                "bucket": buckets.bucket(row),
            })
        records.append({
            "source_page": rec["source_page"],      # 0-based
            "source_kind": rec["source_kind"],
            "total_col": rec["total_col"],
            "printed_total": rec["printed_total"],
            "rows": rows,
        })

    return {
        "key": key, "doc": doc, "cls": cls,
        "anchor": loc.anchors.get(cls),
        "pages": sorted({r["source_page"] for r in records}),
        "records": records,
    }


def todo_cells():
    """還沒抄、且有候選頁可抄的格。排序沿用 `fill._doc_sort_key`
    (2023+ 優先、年報優先),讓網站的順序與 `fill.py next` 一致。"""
    cells = facts_mod.load()
    rejected = fill._rejected_keys()
    index = fill._load_index()
    out = []
    for doc in sorted(docs_in_scope(), key=fill._doc_sort_key):
        for cls in locate.CLASSES:
            key = f"{doc}|{cls}"
            if key in cells or key in rejected:
                continue
            if index["cells"].get(doc, {}).get(cls):
                out.append({"key": key, "doc": doc, "cls": cls})
    return out


def fill_context(doc, cls):
    """抄列台要的:錨值、候選頁、規矩全文、一份空白模板。"""
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    pages = list(loc.pages[cls])
    return {
        "doc": doc, "cls": cls,
        "anchor": loc.anchors.get(cls),
        "pages": pages,                              # 0-based
        "rules": fill.RULES,
        "template": {"records": [{
            "source_page": pages[0] if pages else 0, # 0-based,不要 +1
            "source_kind": "附註", "total_col": "",
            "printed_total": loc.anchors.get(cls),
            "rows": [{"name": "", "group": "", "cols": {}}],
        }]},
    }


def pending_entries():
    """待人裁示的科目名。合流兩個佇列,見 `core/queue.py`。"""
    return queue_mod.pending()


def confirm_bucket(name, bucket_name, reason, today=None, path="buckets.py"):
    """把人工裁示寫進 `buckets.SYN`。

    **這是唯一的寫入點**,而且對應的是 `fill.py` 自己印出來的指示
    (「提案已寫入 …,請使用者審核後收錄進 buckets.SYN」)—— 不是為了 UI
    方便新開的接受分支。收錄後仍要 `git diff` 審過再 commit,
    git 就是這裡的審核介面(見 buckets.py 檔頭)。
    """
    if bucket_name not in config.BUCKETS:
        raise ValueError(f"「{bucket_name}」不是 config.BUCKETS 裡的桶")
    norm = buckets.norm(name)
    if norm in buckets._SYN_N:
        return {"written": False, "why": "已收錄"}

    today = today or datetime.date.today().isoformat()
    text = open(path, encoding="utf-8").read()
    marker = "SYN = {"
    idx = text.index(marker) + len(marker)
    insertion = (f"\n    # {reason}(複核台裁示,{today})\n"
                 f"    {name!r}: {bucket_name!r},")
    open(path, "w", encoding="utf-8").write(text[:idx] + insertion + text[idx:])
    buckets._SYN_N[norm] = bucket_name       # 本次 process 立刻生效,不必重啟
    return {"written": True}


def requeue(cell_key):
    """把卡住的格放回待抄佇列 —— 只刪標記檔,不動 `facts/`
    (那些格從沒歸檔過,重跑一次是乾淨的,同 `fill.py requeue`)。"""
    doc, cls = cell_key.split("|", 1)
    p = f"{fill.BLOCKED_DIR}/{doc}__{cls}.json"
    if os.path.exists(p):
        os.remove(p)
        return {"removed": True}
    return {"removed": False}
