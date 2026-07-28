# -*- coding: utf-8 -*-
"""`decisions/{doc}.json` 的讀寫。Ring 1,IO-aware(**不是** `core/decisions.py`
那支零 IO 的純函數模組——本檔只負責落地,判斷邏輯一律在 `core.decisions`)。

格式刻意照抄 `facts.py` 的形狀:一份文件一個檔,一個大檔的 git diff 沒人看得動。

    load()            {格key: [decision, ...]}
    save(cells)        按 doc 分檔寫回
    load_review()      review/queue.jsonl → [entry, ...]
    append_review(...) 依 occurrence key 去重後 append,**不是無條件 append**
                        (`plan_phaseB.md` §4.5 的 idempotence 要求)
"""
import glob
import json
import os

DIR = "decisions"
REVIEW_QUEUE = "review/queue.jsonl"


def load(decisions_dir=None):
    d = decisions_dir or DIR
    cells = {}
    for p in sorted(glob.glob(f"{d}/*.json")):
        cells.update(json.load(open(p, encoding="utf-8")))
    return cells


def save(cells, decisions_dir=None):
    d = decisions_dir or DIR
    os.makedirs(d, exist_ok=True)
    by_doc = {}
    for key, decs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = decs
    for doc, part in by_doc.items():
        json.dump(part, open(f"{d}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)


def _occurrence_key(decision):
    """去重用的身分:record_fp + scope + row_fp(不看 ordinal——那只在同一次
    快照內有意義,見 `plan_phaseB.md` §2.2)。"""
    occ = decision.get("occurrence") or {}
    return (occ.get("record_fp"), occ.get("scope"), occ.get("row_fp"))


def load_review(review_path=None):
    p = review_path or REVIEW_QUEUE
    if not os.path.exists(p):
        return []
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def append_review(entries, review_path=None):
    """依 `_occurrence_key` 去重後 append。**不是無條件 append**——同一個
    occurrence 重跑一次 ingest 不該讓 review queue 長出第二筆(idempotence)。
    """
    p = review_path or REVIEW_QUEUE
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    existing = load_review(p)
    seen = {_occurrence_key(e["decision"]) for e in existing if e.get("decision")}
    new_lines = []
    for e in entries:
        key = _occurrence_key(e["decision"])
        if key in seen:
            continue
        seen.add(key)
        new_lines.append(json.dumps(e, ensure_ascii=False))
    if new_lines:
        with open(p, "a", encoding="utf-8") as f:
            for line in new_lines:
                f.write(line + "\n")
    return len(new_lines)


RESOLVED_LOG = "review/resolved.jsonl"


def remove_from_review(predicate, review_path=None):
    """依 `predicate(entry) -> bool` 決定要從佇列移除哪些,回傳被移除的清單。
    B4 三種處置(收錄/退回/人工擴頁)共用這支——處置完的 occurrence 不該
    繼續留在待審佇列裡,但**歷史要留**(見 `append_resolved`,不是單純刪掉)。
    """
    p = review_path or REVIEW_QUEUE
    entries = load_review(p)
    keep, removed = [], []
    for e in entries:
        (removed if predicate(e) else keep).append(e)
    if removed:
        with open(p, "w", encoding="utf-8") as f:
            for e in keep:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return removed


def append_resolved(entries, resolved_path=None):
    """B4 處置的審計紀錄——**只准 append,不准改寫歷史**。"""
    p = resolved_path or RESOLVED_LOG
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
