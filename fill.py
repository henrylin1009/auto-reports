# -*- coding: utf-8 -*-
"""agent 面向的抄列 CLI。三個指令,每個都以「下一步做什麼」收尾 —— agent 不必推理流程。

    python3 fill.py next               印出一格待抄的候選頁,或明確的下一步指示
    python3 fill.py submit <path>      驗收剛寫好的 rows,PASS / RETRY / REJECT 三選一
    python3 fill.py status             已完成 / 待抄 / 人審佇列 三行

**狀態全在檔案裡,這支程式不持有任何跨呼叫狀態**:正在抄哪一格、抄到第幾級擴張
記在 `work/pending.json`;過關的進 `facts/`;拒收的進 `work/rejected/`。三者
在全新的 session、全新的電腦上都重建得出來 —— 這是 T3 的核心設計性質。

⚠️ 這支程式不放任何檢查邏輯,也不做任何「順手修」(補 0、改名字、刪小計)。
   驗收全部交給 `transcribe.verify()` / `facts.validate()`;抄不過就退回重抄,
   不在這裡新增接受分支。

⚠️ 不准呼叫任何模型 API(使用者已定案)。讀表的是外部的 Claude Code agent,
   這支程式只做確定性的機械工作:找頁、驗收、擴張、歸檔、記進度。
"""
import datetime
import glob
import json
import os
import sys

import facts
import locate
import pipeline
import transcribe

WORK_DIR = "work"
PENDING = f"{WORK_DIR}/pending.json"
REJECTED_DIR = f"{WORK_DIR}/rejected"
INDEX = f"{WORK_DIR}/index.json"

RULES = """## 事實層規矩(違反會被退回)
- name 存表上印的原名 —— 不正規化、不翻譯、不分桶、不改錯字
- cols 的 key 存原欄名(「取得成本」「公允價值總額」「帳面金額」…)
- 缺的欄不放 key,不准補 0 —— 未揭露與 0 是不同的事實
- 小計 / 合計不是資料列,不進 rows;它們放 printed_total / printed_totals
- 同一格可能有多份 record(年報通常是「附註」+「明細表」),一份對一個來源頁
- 抄不出來就寫 {"records": []}。不要猜 —— 猜錯比空白糟糕得多

## 格式
{"records": [{"source_page": 31, "source_kind": "附註", "total_col": "...",
  "printed_total": 9082587, "printed_totals": {"取得成本": ...},
  "rows": [{"name": "公司債", "group": "有價證券", "cols": {"取得成本": ..., "公允價值總額": ...}}]}]}"""


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")


def _key(doc, cls):
    return f"{doc}|{cls}"


def _rejected_path(doc, cls):
    return f"{REJECTED_DIR}/{doc}__{cls}.json"


def _all_docs():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob("pdf_cache/*.pdf"))


def _rejected_keys():
    keys = set()
    for p in glob.glob(f"{REJECTED_DIR}/*.json"):
        doc, cls = os.path.basename(p)[:-5].rsplit("__", 1)
        keys.add(_key(doc, cls))
    return keys


def _pdf_signature():
    """偵測 pdf_cache/ 有沒有變動(新增/刪除/換檔)—— 不比對內容,比 mtime 夠了。"""
    return sorted((os.path.basename(p), int(os.path.getmtime(p)))
                  for p in glob.glob("pdf_cache/*.pdf"))


def _build_index():
    """對每份 PDF 跑一次 locate(),快取「哪個類別有候選頁」。這是唯一的 O(n) 全掃,
    之後 next() 只查表,只對選中的那一格重新 locate() 一次(要拿頁文字)。"""
    sig = _pdf_signature()
    cells = {}
    for doc in _all_docs():
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        cells[doc] = {cls: bool(pages) for cls, _, pages in loc.cells()}
    idx = {"sig": sig, "cells": cells}
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump(idx, open(INDEX, "w", encoding="utf-8"))
    return idx


def _load_index():
    sig = _pdf_signature()
    if os.path.exists(INDEX):
        idx = json.load(open(INDEX, encoding="utf-8"))
        if [tuple(x) for x in idx.get("sig", [])] == sig:
            return idx
    return _build_index()


def _doc_sort_key(doc):
    """T4 §3:2023+ 優先於 ≤2022;同範圍內年報(期別 04)優先於半年報(期別 02,
    第 3 道「雙表互對」只有年報才跑,驗證強度最高,問題早暴露划算);
    同類型內年份新的優先。"""
    yyyy, mm = int(doc[:4]), doc[4:6]
    return (0 if yyyy >= 2023 else 1, 0 if mm == "04" else 1, -yyyy, doc)


def _pick_next(cells, rejected_keys):
    """回傳 (doc, cls, loc),或 None(現有 PDF 裡沒有待辦的格子了)。"""
    index = _load_index()
    for doc in sorted(index["cells"], key=_doc_sort_key):
        avail = index["cells"][doc]
        for cls in locate.CLASSES:
            if not avail.get(cls):
                continue          # 錨有但無候選頁,不是 agent 能抄的格子(見 locate.census)
            key = _key(doc, cls)
            if key in cells or key in rejected_keys:
                continue
            return doc, cls, locate.locate(f"pdf_cache/{doc}.pdf")
    return None


def _render(doc, cls, loc, pages):
    anchor = loc.anchors[cls]
    print(f"# {doc} | {cls}      錨(BS 合計)= {anchor:,} 仟元")
    print()
    print("把下面來源頁裡的表格逐列抄成 JSON,寫到 work/current.json,然後跑")
    print("    python3 fill.py submit work/current.json")
    print()
    print(RULES)
    print()
    print("## 自己先對一次(對得上就不必來回一輪)")
    print(f"每份 record:sum(每列的 total_col 那一欄) == printed_total,"
          f"且 printed_total == {anchor:,}")
    print()
    print("## 來源頁")
    print(transcribe.context_pages(loc, cls, pages))
    print()
    print("下一步:讀完上面的表格,寫 work/current.json,再跑 "
          "python3 fill.py submit work/current.json")


def cmd_next():
    if os.path.exists(PENDING):
        p = json.load(open(PENDING, encoding="utf-8"))
        loc = locate.locate(f"pdf_cache/{p['doc']}.pdf")
        print(f"(這一格上一輪還沒交,重印同一份工單)")
        _render(p["doc"], p["cls"], loc, p["pages"])
        return

    # 空 pdf_cache/ 與「全做完了」在畫面上長得一模一樣,一定要先分開講清楚。
    if not glob.glob("pdf_cache/*.pdf"):
        print("pdf_cache/ 是空的 —— 還沒有 PDF 可抄,不是全部做完了。")
        print("下一步:跑 python3 resolve.py 抓財報 PDF(需要台灣網路環境),"
              "完成後重跑 python3 fill.py next")
        return

    cells = facts.load()
    picked = _pick_next(cells, _rejected_keys())
    if picked is None:
        print("ALL DONE")
        return

    doc, cls, loc = picked
    pages = list(loc.pages[cls])
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump({"doc": doc, "cls": cls, "level": 0, "pages": pages, "retries": 0},
               open(PENDING, "w", encoding="utf-8"))
    _render(doc, cls, loc, pages)


def cmd_submit(path):
    if not os.path.exists(PENDING):
        print("沒有正在抄的格子(work/pending.json 不存在)。")
        print("下一步:python3 fill.py next")
        raise SystemExit(1)

    p = json.load(open(PENDING, encoding="utf-8"))
    doc, cls, level, pages, retries = p["doc"], p["cls"], p["level"], p["pages"], p["retries"]

    data = json.load(open(path, encoding="utf-8"))
    recs = data.get("records") or []
    for r in recs:
        r.setdefault("doc", doc)
        r.setdefault("class", cls)

    loc = locate.locate(f"pdf_cache/{doc}.pdf")

    ok, reason = False, "抄不出來(records 為空)"
    if recs:
        problems = facts.validate({_key(doc, cls): recs})
        if problems:
            reason = "; ".join(problems)
        else:
            ok, res = transcribe.verify(recs, loc)
            if not ok:
                reason = "; ".join(f"{k}:{v}" for k, v in res.items() if v)

    if ok:
        cells = facts.load()
        for r in recs:
            # 稽核欄位,不是事實 —— wide / buckets / verify 一律不准讀它(facts.py 已把
            # 它列為已知選填欄位,不會被 T1 的「未知欄位」檢查擋下來)。
            r["_by"] = {"at": _now(), "retries": retries, "level": level, "via": "claude-code"}
        cells[_key(doc, cls)] = recs
        facts.save(cells)
        os.remove(PENDING)
        print(f"PASS      已歸檔進 facts/{doc}.json({cls})。")
        print("下一步:python3 fill.py next")
        return

    level += 1
    more = loc.expand(cls, level) if level <= pipeline.MAX_LEVEL else []
    new_pages = sorted(set(pages) | set(more))

    if level > pipeline.MAX_LEVEL or not more or new_pages == pages:
        os.makedirs(REJECTED_DIR, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": reason, "level": level - 1,
                   "submitted": data},
                  open(_rejected_path(doc, cls), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        os.remove(PENDING)
        print(f"REJECT    擴張到上限仍對不上,已進 work/rejected/{doc}__{cls}.json。")
        print(f"          理由:{reason}")
        print("下一步:python3 fill.py next")
        return

    json.dump({"doc": doc, "cls": cls, "level": level, "pages": new_pages,
               "retries": retries + 1},
              open(PENDING, "w", encoding="utf-8"))
    added = sorted(set(new_pages) - set(pages))
    print(f"RETRY     沒過:{reason}")
    print(f"          已擴張加入鄰頁 {added}。")
    print("下一步:重讀下面的頁再抄一次,寫回 work/current.json,"
          "再跑 python3 fill.py submit work/current.json(不要跳過,不要回 next)")
    print()
    _render(doc, cls, loc, new_pages)


def cmd_status():
    cells = facts.load()
    rejected = _rejected_keys()
    total = 0
    for doc in _all_docs():
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        total += sum(1 for _, _, pages in loc.cells() if pages)
    todo = max(total - len(cells) - len(rejected), 0)
    print(f"已完成 {len(cells)} / 待抄 {todo} / 人審佇列 {len(rejected)}")


def _main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("next", "submit", "status"):
        print("用法: python3 fill.py next | submit <path> | status")
        return 2
    cmd = sys.argv[1]
    if cmd == "next":
        cmd_next()
    elif cmd == "status":
        cmd_status()
    else:
        if len(sys.argv) < 3:
            print("用法: python3 fill.py submit <path>")
            return 2
        cmd_submit(sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
