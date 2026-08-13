# -*- coding: utf-8 -*-
"""把 capital.json / pillar3.json 併進 `facts.db`(v11 R2)。

**這支不是取代 `capital_auto.py` / `scratchpad/extract_pillar3.py`。**
兩支抽取器照常寫自己的 json——這支只是把它們的輸出**再存一份**進 `facts.db`,
讓 capital/pillar3 跟債券部位的 facts 走同一個實體檔案,之後資料頁要接這些格
的核對介面時,查詢路徑是統一的。

## ⚠️ 不能借用 `observations` / `rulings` 表(2026-08-13 實測炸過一次)

第一版直接把 `capital.fair_value` / `pillar3` 當成新的 `cls` 值塞進
`db.record_observation()`。**這是錯的**:`facts.py:load()` 不分青紅皂白對
`db.materialize_cells()` 撈出來的**每一筆**做 `REQUIRED_REC` 驗證
(`doc/class/source_page/source_kind/total_col/printed_total/rows`)。
capital/pillar3 的紀錄形狀完全不同,插進同一張表的瞬間 `facts.load()`
(債券部位那條管線的**唯一**讀入口,`build.py` 每次都呼叫)當場拋錯,
整條發布管線斷線。

**教訓**:`observations`/`rulings` 是債券部位這條管線專用的表,不是「facts.db
裡隨便一張表」。要併進同一個檔案,必須是**另外的表**,不能共用 cls 命名空間
硬塞進去。這支改用 `capital_observations`(schema 與 `observations` 相同,
只是表名不同)——`facts.load()` 完全不知道這張表存在,兩邊互不干擾。

## doc 鍵怎麼定

    capital.*   doc = capital.json 原本的 key(例如 "202204_富邦_個體"),
                cls = f"capital.{kind}"(例如 "capital.fair_value")
    pillar3     doc = f"{period}_{bank}"(例如 "114H2_中信"),cls = "pillar3",
                records_json = 該期該行的完整紀錄(含個體/合併兩個口徑 + `_src`)

## 驗收:round-trip 必須無損,而且不能動到既有管線

`migrate()` 寫進去之後:
  1. `export_*()` 重建的內容要跟原始檔逐位元組相同(排序後比較)
  2. `python3 app.py build --diff` 的輸出要跟遷移前逐字相同
     ——這是「新表不會被舊管線讀到」的直接證明,不是猜的
"""
import json
import os
import sqlite3

PATH = "facts.db"
QUEUE = "review/capital_queue.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capital_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc TEXT NOT NULL,
    cls TEXT NOT NULL,
    records_json TEXT NOT NULL,
    extractor TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capobs_cell ON capital_observations(doc, cls, id);
"""

CAPITAL_KINDS = ("fair_value", "pnl", "interest")


def _connect(path=None):
    conn = sqlite3.connect(path or PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _record(cells, extractor, path, at=None):
    conn = _connect(path)
    try:
        at = at or _now()
        for key, recs in cells.items():
            doc, cls = key.split("|", 1)
            conn.execute(
                "INSERT INTO capital_observations (doc, cls, records_json, extractor, at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc, cls, json.dumps(recs, ensure_ascii=False, sort_keys=True),
                 extractor, at))
        conn.commit()
    finally:
        conn.close()


def _materialize(path=None):
    """→ `{doc|cls: 內容}`,只取每格最新一筆(id 最大),純函數。"""
    conn = _connect(path)
    try:
        cur = conn.execute(
            "SELECT doc, cls, records_json FROM ("
            "  SELECT doc, cls, records_json, id,"
            "         ROW_NUMBER() OVER (PARTITION BY doc, cls ORDER BY id DESC) rn"
            "  FROM capital_observations"
            ") WHERE rn = 1")
        rows = cur.fetchall()
    finally:
        conn.close()
    return {f"{d}|{c}": json.loads(rj) for d, c, rj in rows}


def migrate_capital(path="capital.json", db_path=None, at=None):
    """capital.json 的三段(fair_value/pnl/interest)→ capital_observations。
    `equity`/`capital` 兩段不併——沒有消費端(見 docs/plan_v11_一條路線.md)。
    回寫入的格數。"""
    store = json.load(open(path, encoding="utf-8"))
    cells = {}
    for kind in CAPITAL_KINDS:
        for doc, recs in store.get(kind, {}).items():
            cells[f"{doc}|capital.{kind}"] = recs
    _record(cells, "capital_auto", db_path, at)
    return len(cells)


def migrate_pillar3(path="pillar3.json", db_path=None, at=None):
    """pillar3.json → capital_observations。一格 = 一家銀行一個期別。回寫入的格數。"""
    store = json.load(open(path, encoding="utf-8"))
    cells = {}
    for bank, periods in store.items():
        for period, rec in periods.items():
            cells[f"{period}_{bank}|pillar3"] = rec
    _record(cells, "extract_pillar3", db_path, at)
    return len(cells)


def export_capital(db_path=None):
    """facts.db(capital_observations)→ capital.json 的形狀(只有已併的三段)。"""
    cells = _materialize(db_path)
    out = {kind: {} for kind in CAPITAL_KINDS}
    for key, recs in cells.items():
        doc, cls = key.split("|", 1)
        if not cls.startswith("capital."):
            continue
        kind = cls[len("capital."):]
        if kind in out:
            out[kind][doc] = recs
    return out


def export_pillar3(db_path=None):
    """facts.db(capital_observations)→ pillar3.json 的形狀。"""
    cells = _materialize(db_path)
    out = {}
    for key, rec in cells.items():
        doc, cls = key.split("|", 1)
        if cls != "pillar3":
            continue
        period, bank = doc.split("_", 1)
        out.setdefault(bank, {})[period] = rec
    return out


# ── R3/R4(範圍縮小版):唯讀檢視,不碰 core/webdata.py ─────────────────
#
# 完整版 R3/R4(依 docs/plan_v11_一條路線.md)是把 capital/pillar3 接進
# `/api/cell` 的既有核對介面,依 kind 分派 checks/tally/rows。R2 那次「看起來
# 安全的設計」實測直接打斷了 `facts.load()`(債券部位那條管線的唯一讀入口)
# 之後,不該在同一次改動裡再對 `core/webdata.py`(1269 行,`/api/cell` 的
# 實作)做同等規模的手術而只驗一兩項——那是把同一種風險再犯一次。
#
# 這裡改成**完全獨立的新路徑**:新函式、新 API route、新頁面,一行都不碰
# `core/webdata.py` / `server.py` 既有的 `/api/cell` 分支。代價是核對頁還沒有
# 「選桶」「重抄」「就地改列」——那些留給下一輪照計劃 R3/R4 做。
# 換到的是「79 筆卡住的東西終於有地方看得到」,而且**不可能弄壞既有管線**,
# 因為讀的表(capital_observations)、讀的檔(review/capital_queue.jsonl)
# 都不是任何既有程式碼路徑會碰的東西。

def review_queue():
    """review/capital_queue.jsonl → 去重後的清單(每個 doc|kind|period 只留
    最新一筆,同 `db.materialize_cells()` 取最新的精神)。純函數,不寫檔。"""
    if not os.path.exists(QUEUE):
        return []
    latest = {}
    with open(QUEUE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            period = (r.get("rec") or {}).get("period")
            key = (r["doc"], r["kind"], period)
            latest[key] = r        # 檔案本身是 append-only,後面的覆蓋前面的
    return sorted(latest.values(), key=lambda r: (r["kind"], r["doc"]))


def overview(db_path=None):
    """已併進 facts.db 的格 + 還卡在佇列裡的格,合成一張總覽。

    只讀,不算分數——`pass/fail/no_witness` 這種判斷留給 R3 真正接進
    `/api/cell` 時再做(那裡才有 `capital.py` 的 `verify_*` 該吃的完整 context,
    例如 `verify_fair_value` 要 `doc` 去反查 `facts/` 的 AC 總額)。
    這裡只負責「有沒有、在哪裡」,不負責「對不對」。
    """
    cells = _materialize(db_path)
    migrated = []
    for key, content in sorted(cells.items()):
        doc, cls = key.split("|", 1)
        migrated.append({"doc": doc, "cls": cls, "key": key})
    queued = review_queue()
    return {
        "migrated": migrated,
        "migrated_count": len(migrated),
        "queued": queued,
        "queued_count": len(queued),
    }


def main():
    n1 = migrate_capital()
    n2 = migrate_pillar3()
    print(f"寫入 facts.db(capital_observations 表,與 observations/rulings 分開):"
          f"capital {n1} 格,pillar3 {n2} 格")

    orig_capital = json.load(open("capital.json", encoding="utf-8"))
    rebuilt_capital = export_capital()
    for kind in CAPITAL_KINDS:
        a = json.dumps(orig_capital[kind], sort_keys=True, ensure_ascii=False)
        b = json.dumps(rebuilt_capital[kind], sort_keys=True, ensure_ascii=False)
        assert a == b, f"capital.{kind} round-trip 不一致!"
    print("capital round-trip: 三段逐位元組相同 ✓")

    orig_p3 = json.load(open("pillar3.json", encoding="utf-8"))
    rebuilt_p3 = export_pillar3()
    a = json.dumps(orig_p3, sort_keys=True, ensure_ascii=False)
    b = json.dumps(rebuilt_p3, sort_keys=True, ensure_ascii=False)
    assert a == b, "pillar3 round-trip 不一致!"
    print("pillar3 round-trip: 逐位元組相同 ✓")


if __name__ == "__main__":
    main()
