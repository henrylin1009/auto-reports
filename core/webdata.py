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


def doc_detail(doc):
    """**一份文件的三類一起給**。這是使用者實際的工作單位 —— 你是「處理這份
    財報」,不是「處理 202504_5847_AI3|OCI 這一格」(2026-07-29 裁示)。

    每類的形狀依狀態而定,前端不必再自己判斷要打哪支 API:
      done  → `cell`(逐列 + 桶),核對用
      todo  → `fill`(錨、候選頁、模板),抄列用
      na    → 兩個都 None
    `pages` 一律拉到最上層,因為三類共用同一個頁圖檢視器。
    """
    cells = facts_mod.load()
    blocked = {os.path.basename(p)[:-5].replace("__", "|")
               for p in glob.glob(f"{fill.BLOCKED_DIR}/*.json")}
    index = fill._load_index()

    out, pages = {}, []
    for cls in locate.CLASSES:
        st = cell_status(cells, blocked, index, doc, cls)
        d = {"status": st, "cell": None, "fill": None}
        if st == "done":
            d["cell"] = cell_detail(f"{doc}|{cls}")
            pages += d["cell"]["pages"]
        elif st in ("todo", "blocked"):
            d["fill"] = fill_context(doc, cls)
            pages += d["fill"]["pages"]
        out[cls] = d
    return {"doc": doc, "classes": out, "pages": sorted(set(pages))}


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


def bucket_view():
    """十個桶 × 收進去的科目名。**看的是 Decision 不是 buckets.SYN** ——
    SYN 是規則,Decision 是「這一列實際落在哪」,兩者可能不同(規則改過、
    人裁示過單一格)。畫面要呈現的是後者,否則你看到的是應然不是實然。

    同名不同桶是**真的會發生**的(富邦 202304 Trading 同一份附註裡「其他」
    出現兩次、桶不同),所以聚合鍵是 (bucket, name),不是 name。

    `state` 取該組裡**最弱**的一個:只要有一列還沒 CONFIRMED,整組就不算確認 ——
    「大部分確認了」在這裡等於沒確認。
    """
    from core import decision_store

    RANK = {"UNCLASSIFIED": 0, "PROVISIONAL": 1, "CONFIRMED": 2}
    groups = {}
    for cell_key, decs in decision_store.load().items():
        for d in decs:
            k = (d.get("mapping"), d["name"])
            g = groups.setdefault(k, {"bucket": d.get("mapping"), "name": d["name"],
                                      "n": 0, "state": "CONFIRMED", "cells": set()})
            g["n"] += 1
            g["cells"].add(cell_key)
            if RANK[d["state"]] < RANK[g["state"]]:
                g["state"] = d["state"]

    cols = {b: [] for b in config.BUCKETS}
    loose = []                       # mapping is None → 還沒有桶可以放
    for g in groups.values():
        g["cells"] = sorted(g["cells"])
        (cols[g["bucket"]] if g["bucket"] in cols else loose).append(g)
    for v in cols.values():
        v.sort(key=lambda g: (g["state"] != "UNCLASSIFIED", g["state"] != "PROVISIONAL", -g["n"]))
    loose.sort(key=lambda g: -g["n"])

    tally = {"confirmed": 0, "provisional": 0, "unclassified": 0}
    for g in list(groups.values()):
        tally[g["state"].lower()] += g["n"]
    return {"buckets": config.BUCKETS,
            "cols": cols, "unclassified": loose, "tally": tally}


def rebucket(name, to, global_=False, approved_by="henrylin", today=None):
    """把「一個科目名」改判到 `to` 桶 —— 分桶檢視拖曳的落地。

    **兩個動作分開,這是刻意的**(使用者 2026-07-29 裁示的選項 C):
      · 預設:立一條 taxonomy rule 並更新現有 Decision。改的是**分類紀錄**。
      · `global_`:額外寫進 `buckets.SYN`。那是**原始碼層的同義詞表**,
        會影響往後每一次抄列與每一份文件 —— 所以要另外點頭。

    CONFIRMED 不是隨便標的:`I3a` 要求指到一條 CONFIRMED 的 rule,`I3b` 要求
    那條 rule 至少有一條 `kind=="human"` 的依據。這裡兩條都補齊,不然
    `validate_decision` 會當場抓到。
    """
    from core import decision_store
    from core import decisions as dmod

    if to not in config.BUCKETS:
        raise ValueError(f"「{to}」不是 config.BUCKETS 裡的桶")
    today = today or datetime.datetime.now().isoformat(timespec="seconds")
    norm = buckets.norm(name)
    rule_id = f"tax:{norm}"

    path = os.path.join("taxonomy", "rules.json")
    rules = json.load(open(path, encoding="utf-8"))
    ref = dmod.make_reference(
        "human", f"分桶檢視拖曳:「{name}」→「{to}」 (by {approved_by})", today)
    hit = next((r for r in rules if r["rule_id"] == rule_id), None)
    if hit:
        hit.update(mapping=to, state=dmod.CONFIRMED,
                   approved_by=approved_by, approved_at=today)
        hit["references"] = list(hit.get("references") or []) + [ref]
    else:
        rules.append(dmod.make_rule(rule_id, "name", to, dmod.CONFIRMED, [ref],
                                    approved_by=approved_by, approved_at=today))
    json.dump(rules, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)

    cells = decision_store.load()
    touched = 0
    for decs in cells.values():
        for d in decs:
            if buckets.norm(d["name"]) != norm:
                continue
            d.update(mapping=to, state=dmod.CONFIRMED, taxonomy_ref=rule_id,
                     at=today, by="rebucket")
            touched += 1
    decision_store.save(cells)

    syn = None
    if global_:
        syn = confirm_bucket(name, to, f"分桶檢視拖曳(by {approved_by})")
    return {"rows": touched, "rule": rule_id, "syn": syn}


def requeue(cell_key):
    """把卡住的格放回待抄佇列 —— 只刪標記檔,不動 `facts/`
    (那些格從沒歸檔過,重跑一次是乾淨的,同 `fill.py requeue`)。"""
    doc, cls = cell_key.split("|", 1)
    p = f"{fill.BLOCKED_DIR}/{doc}__{cls}.json"
    if os.path.exists(p):
        os.remove(p)
        return {"removed": True}
    return {"removed": False}
