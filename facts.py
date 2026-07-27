# -*- coding: utf-8 -*-
"""事實庫:一份文件一個檔,進 git。抄一次,除非發現抄錯否則永不重跑。

    load()       {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`
    save(cells)  按 doc 分檔寫回 facts/
    validate()   回傳問題清單。空 list = 通過。**不修資料,只報告。**
"""
import glob
import json
import os

DIR = "facts"

REQUIRED_REC = ("doc", "class", "source_page", "source_kind", "total_col",
                "printed_total", "rows")
OPTIONAL_REC = ("printed_totals", "note", "_by")
REQUIRED_ROW = ("name", "cols")
OPTIONAL_ROW = ("group",)


def load():
    """→ {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`。"""
    cells = {}
    for p in sorted(glob.glob(f"{DIR}/*.json")):
        cells.update(json.load(open(p, encoding="utf-8")))
    problems = validate(cells)
    if problems:
        raise ValueError("facts.load(): 事實庫驗證失敗:\n" + "\n".join(problems))
    return cells


def save(cells):
    """按 doc 分檔寫回。一個大檔的 git diff 在 169 格之後沒人看得動。"""
    os.makedirs(DIR, exist_ok=True)
    by_doc = {}
    for key, recs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = recs
    for doc, part in by_doc.items():
        json.dump(part, open(f"{DIR}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)


def validate(cells):
    """回傳問題清單。空 list = 通過。**不修資料,只報告。**"""
    problems = []
    for key, recs in cells.items():
        k_doc, k_cls = key.split("|", 1)
        for i, rec in enumerate(recs):
            tag = f"{key}[{i}]"
            missing = [f for f in REQUIRED_REC if f not in rec]
            if missing:
                problems.append(f"{tag}: 缺必要欄位 {missing}")
                continue
            unknown = [f for f in rec if f not in REQUIRED_REC + OPTIONAL_REC]
            if unknown:
                problems.append(f"{tag}: 出現未知欄位 {unknown}")
            if rec["doc"] != k_doc or rec["class"] != k_cls:
                problems.append(
                    f"{tag}: key 與內容不一致 key={k_doc}|{k_cls} "
                    f"內容={rec['doc']}|{rec['class']}")
            if not rec["rows"]:
                problems.append(f"{tag}: rows 為空")
            total_col_seen = False
            for j, row in enumerate(rec["rows"]):
                rtag = f"{tag}.rows[{j}]"
                rmissing = [f for f in REQUIRED_ROW if f not in row]
                if rmissing:
                    problems.append(f"{rtag}: 缺必要欄位 {rmissing}")
                    continue
                runknown = [f for f in row if f not in REQUIRED_ROW + OPTIONAL_ROW]
                if runknown:
                    problems.append(f"{rtag}: 出現未知欄位 {runknown}")
                if not isinstance(row["name"], str) or not row["name"]:
                    problems.append(f"{rtag}: name 不是非空字串")
                if not isinstance(row["cols"], dict):
                    problems.append(f"{rtag}: cols 不是 dict")
                    continue
                for col, val in row["cols"].items():
                    if isinstance(val, bool) or not isinstance(val, int):
                        problems.append(f"{rtag}: cols[{col!r}] 不是 int:{val!r}")
                if rec["total_col"] in row["cols"]:
                    total_col_seen = True
            if not total_col_seen:
                problems.append(f"{tag}: total_col {rec['total_col']!r} 沒有出現在任何一列的 cols 裡")
            if "printed_totals" in rec:
                pt = rec["printed_totals"]
                if not isinstance(pt, dict):
                    problems.append(f"{tag}: printed_totals 不是 dict")
                else:
                    for col, val in pt.items():
                        if not isinstance(col, str):
                            problems.append(f"{tag}: printed_totals key 不是字串:{col!r}")
                        if isinstance(val, bool) or not isinstance(val, int):
                            problems.append(f"{tag}: printed_totals[{col!r}] 不是 int:{val!r}")
    return problems
