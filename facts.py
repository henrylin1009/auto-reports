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
#: `_src` = 這一列是人在網頁上改 / 增的,不是機器抄的
#: (`docs/plan_web_complete.md` §2)。形狀 `{"by", "at", "why", "evidence"?}`——
#: 跟 `_by` 同一個模式:稽核欄位,`wide`/`buckets`/`verify` 一律不准讀它,
#: 只讀 `name`/`cols`/`group`。**沒有 `_src` = 機器抄的**,這是唯一的判準,
#: 不需要另外存一個「是不是人工」的旗標。
OPTIONAL_ROW = ("group", "_src")


def load(facts_dir=None):
    """→ {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`。

    `facts_dir` 只給測試用(注入 tmp 目錄,見 `test_webdata.py`)——
    production 呼叫一律用預設值,不要傳。"""
    d = facts_dir or DIR
    cells = {}
    for p in sorted(glob.glob(f"{d}/*.json")):
        cells.update(json.load(open(p, encoding="utf-8")))
    problems = validate(cells)
    if problems:
        raise ValueError("facts.load(): 事實庫驗證失敗:\n" + "\n".join(problems))
    return cells


def save(cells, facts_dir=None):
    """按 doc 分檔寫回。一個大檔的 git diff 在 169 格之後沒人看得動。"""
    d = facts_dir or DIR
    os.makedirs(d, exist_ok=True)
    by_doc = {}
    for key, recs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = recs
    for doc, part in by_doc.items():
        json.dump(part, open(f"{d}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)


def remove(key, facts_dir=None):
    """刪掉一格,回傳有沒有刪到。

    **為什麼不能只做 `del cells[key]; save(cells)`**:`save()` 只寫 `cells` 裡
    還在的 doc,一份 doc 的格**全部**被刪光時,舊檔就留在磁碟上,下次 `load()`
    又整份讀回來 —— 刪除靜靜失效。實測於 `core.webdata.revoke()`
    (2026-08-10):撤銷後該格仍在事實庫裡。

    檔案佈局的知識留在本檔,不外洩給呼叫端自己去 unlink。
    """
    d = facts_dir or DIR
    cells = load(facts_dir)
    if key not in cells:
        return False
    doc = key.split("|")[0]
    del cells[key]
    if not any(k.split("|")[0] == doc for k in cells):
        p = f"{d}/{doc}.json"
        if os.path.exists(p):
            os.remove(p)                 # 這份 doc 一格不剩 → 連檔一起收掉
    save(cells, facts_dir)
    return True


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
