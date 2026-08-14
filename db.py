# -*- coding: utf-8 -*-
"""三張表:documents / observations / rulings。R1(`docs/plan_v6_一台機器.md`)。

**這支是 `facts/` 的儲存後端,不是取代 `facts.py` 的 API。**
`facts.load()` / `facts.save()` / `facts.remove()` 的呼叫端一個字都不用改 ——
它們今天呼叫的還是那三支函式,只是這三支函式現在會判斷 `facts.db` 存不存在,
存在就走這裡,不存在就走原本的 `facts/*.json` 直讀直寫(這條舊路徑保留,
沒有 `facts.db` 的環境 —— 例如 clone 下來還沒跑過 migrate 的人 —— 行為不變)。

## 為什麼是這個形狀,不是逐列 append-only

理想上 `observations` 該是逐列的機器抄寫紀錄、`rulings` 該是逐列的人工裁示紀錄,
差一列就多一筆。但 `facts/*.json` 現有的內容**沒有逐列的歷史**——`_src` 只記
「這一列現在是人改的」,不記「改之前是什麼」。逐列還原完整歷史需要重寫
`core/webdata.edit_row()` 等四個寫入點的內部邏輯,那是比 R1 本身更大的工程,
不在這次的範圍。

**這裡做的是格層級的快照式 append-only**:每次寫入是「這一格(doc|cls)現在
長這樣」的完整快照,插入一筆新列,從不 UPDATE、不 DELETE。**這樣做仍然拿到
R1 要的核心性質**:一個共同的儲存後端(不再有 `facts/` JSON 與 `v4/ledger`
两套並存)、人工裁示永遠蓋過機器(`rulings` 表在 `materialize_cells()` 裡
優先於 `observations`)、可以重播 git blame 之外的稽核軌跡(`by`/`at`/`why`)。

機器寫 `observations`,人工寫 `rulings` —— 判準沿用既有的
`core.webdata.human_ratified()`:一格的 records 裡任何一列帶 `_src`,
就是人工裁示過,寫進 `rulings`;否則寫進 `observations`。這條判準
`facts.save()` 本來就要用(它是唯一能分辨呼叫端是機器還是人的地方),
不是新發明的規則。

## 表

    documents     一份 PDF:doc、sha256、fetched_at。R2(上傳通道)會需要它,
                  這次先建表、migrate 時從 pdf_cache/ 掃進去,還沒有人讀它。
    observations  {doc, cls, records_json, extractor, at}。機器寫,append-only。
    rulings       {doc, cls, records_json, by, at, why}。人工寫,append-only。
                  `records_json` 是 NULL 代表「這格被撤銷了」(對應 `facts.remove()`)。

## 現在的狀態算法

    materialize_cells() 對每個 (doc, cls):
        取 rulings 裡這格最新的一筆(id 最大)
            存在且 records_json 非 NULL → 用它(人工蓋過機器)
            存在且 records_json 是 NULL → 這格不存在(被撤銷,略過)
            不存在                      → 退回 observations 最新一筆
"""
import datetime
import glob
import hashlib
import json
import os
import sqlite3

PATH = "facts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc TEXT PRIMARY KEY,
    sha256 TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc TEXT NOT NULL,
    cls TEXT NOT NULL,
    records_json TEXT NOT NULL,
    extractor TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rulings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc TEXT NOT NULL,
    cls TEXT NOT NULL,
    records_json TEXT,
    by TEXT,
    at TEXT NOT NULL,
    why TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_cell ON observations(doc, cls, id);
CREATE INDEX IF NOT EXISTS idx_rul_cell ON rulings(doc, cls, id);
"""


def exists(path=None):
    """`facts.db` 這個檔在不在。**只回答檔案存在性** —— 文件登記
    (`documents` 表、上傳去重)用這個。

    ⚠️ 不要拿它來決定「事實庫要不要走 DB」,那是另一個問題,見 `has_facts()`。
    兩者曾經是同一個函式,結果是 `test_upload` 的清理被跳過(它的 DB 只有
    `documents` 一張表有列)—— 一道判斷兩種用途,這個 repo 反覆踩的形狀。
    """
    return os.path.exists(path or PATH)


def has_facts(path=None):
    """`facts.db` 存在**而且真的有事實**(`observations` 或 `rulings` 有列)。

    ⚠️ 2026-08-14:原本只看檔案在不在,而那讓一個**空的 DB 檔劫持整個事實庫**。
    實測(乾淨 `git clone` + `pip install` + `python3 run_tests.py`):
      `test_upload.py` 起真的伺服器上傳檔案 → `server.py::_handle_upload`
      → `db.find_document_by_sha256()` → `connect()`,而 `sqlite3.connect()`
      **在唯讀查詢時也會把檔案建出來**(空的,只有 schema)。
      從那一刻起 `facts.load()` 走 DB 分支 → 回 **0 格**(JSON 裡明明有 203 格)。
    症狀是「所有資料無聲消失」,不是報錯 —— `build.py` 會照常產出一份全 null
    的 `data.json`,長得跟「今年真的沒資料」一模一樣。

    `.gitignore` 對這個檔的承諾是「沒有這個檔時 facts.py 自動退回直讀
    facts/*.json,clone 下來不需要它就能跑」。**空的 DB 在語意上就是沒有 DB**,
    所以判準改成「有沒有資料」而不是「檔案在不在」,承諾才真的成立。
    """
    p = path or PATH
    if not os.path.exists(p):
        return False
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return False
    try:
        for t in ("observations", "rulings"):
            try:
                if conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone():
                    return True
            except sqlite3.Error:      # 表還沒建 → 等同沒有資料
                continue
        return False
    finally:
        conn.close()


def connect(path=None):
    """開一個連線。**WAL + busy_timeout**——R1-5 的並行保護:兩個 process
    同時寫,SQLite 的鎖會讓其中一個等待再插入,不會有哪一筆憑空消失
    (append-only 的 INSERT 本來就不會互相覆蓋,鎖只是避免『資料庫忙碌』炸掉)。
    """
    p = path or PATH
    conn = sqlite3.connect(p, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def record_observation(cells, extractor=None, at=None, path=None):
    """機器寫入。`cells` 形如 `facts.load()` 的回傳:`{doc|cls: [record,...]}`。
    每個 key 各插一筆快照,append-only。"""
    conn = connect(path)
    try:
        at = at or _now()
        for key, recs in cells.items():
            doc, cls = key.split("|", 1)
            conn.execute(
                "INSERT INTO observations (doc, cls, records_json, extractor, at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc, cls, json.dumps(recs, ensure_ascii=False, sort_keys=True),
                 extractor, at))
        conn.commit()
    finally:
        conn.close()


def record_ruling(cells, by=None, at=None, why=None, path=None):
    """人工寫入(`ratify()` / `edit_row()`)。同上,寫進 `rulings`。"""
    conn = connect(path)
    try:
        at = at or _now()
        for key, recs in cells.items():
            doc, cls = key.split("|", 1)
            conn.execute(
                "INSERT INTO rulings (doc, cls, records_json, by, at, why) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc, cls, json.dumps(recs, ensure_ascii=False, sort_keys=True),
                 by, at, why))
        conn.commit()
    finally:
        conn.close()


def record_deletion(key, by=None, at=None, why=None, path=None):
    """撤銷一格(`facts.remove()` 的 DB 版)——寫一筆 `records_json=NULL` 的 ruling。
    **不是刪掉舊的列**,append-only 到底:歷史仍然查得到,只是「現狀」變成不存在。
    """
    doc, cls = key.split("|", 1)
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO rulings (doc, cls, records_json, by, at, why) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            (doc, cls, by, at or _now(), why))
        conn.commit()
    finally:
        conn.close()


def materialize_cells(path=None):
    """三張表 → `{doc|cls: [record,...]}`,形狀與 `facts.load()` 完全相同。
    純函數:只讀,不寫。"""
    conn = connect(path)
    try:
        cur = conn.execute(
            "SELECT doc, cls, records_json FROM ("
            "  SELECT doc, cls, records_json, id,"
            "         ROW_NUMBER() OVER (PARTITION BY doc, cls ORDER BY id DESC) rn"
            "  FROM rulings"
            ") WHERE rn = 1")
        latest_ruling = {(d, c): rj for d, c, rj in cur.fetchall()}

        cur = conn.execute(
            "SELECT doc, cls, records_json FROM ("
            "  SELECT doc, cls, records_json, id,"
            "         ROW_NUMBER() OVER (PARTITION BY doc, cls ORDER BY id DESC) rn"
            "  FROM observations"
            ") WHERE rn = 1")
        latest_obs = {(d, c): rj for d, c, rj in cur.fetchall()}
    finally:
        conn.close()

    cells = {}
    for (doc, cls), rj in latest_obs.items():
        if (doc, cls) not in latest_ruling:
            cells[f"{doc}|{cls}"] = json.loads(rj)
    for (doc, cls), rj in latest_ruling.items():
        if rj is not None:          # None = 這格被撤銷了,不進 cells
            cells[f"{doc}|{cls}"] = json.loads(rj)
    return cells


def export_json(cells=None, facts_dir="facts"):
    """DB → `facts/*.json`。**進 git 當快照與人可讀的 diff**,不是給程式讀的
    ——`facts.load()` 有 `facts.db` 時不會讀這些檔案。跟 `facts.save()` 原本
    直寫 JSON 時用的參數逐字相同(`ensure_ascii=False, indent=1, sort_keys=True`),
    這樣匯出的檔案與遷移前的檔案往返無損(R1-4 的驗收)。"""
    cells = cells if cells is not None else materialize_cells()
    os.makedirs(facts_dir, exist_ok=True)
    by_doc = {}
    for key, recs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = recs
    # 清掉已經沒有任何格的舊檔(該 doc 全部格被撤銷的情形)
    existing_docs = {os.path.basename(p)[:-5] for p in glob.glob(f"{facts_dir}/*.json")}
    for doc in existing_docs - set(by_doc):
        os.remove(f"{facts_dir}/{doc}.json")
    for doc, part in by_doc.items():
        json.dump(part, open(f"{facts_dir}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
    return sorted(by_doc)


# ── documents(R2:輸入通道)──────────────────────────────────────────────

def find_document_by_sha256(sha256, path=None):
    """這個內容雜湊有沒有登記過?回傳 doc id 或 None。

    **去重的判準是內容,不是檔名** —— R2-1 的驗收「拖同一份兩次只有一列」
    指的是同一份 PDF(位元組相同),不是同一個檔名。使用者兩次都叫
    `report.pdf` 但內容不同,那是兩份文件;同一份檔案改了名字重拖一次,
    是同一份文件。
    """
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT doc FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def register_document(doc, sha256, at=None, path=None):
    """登記一份文件。**呼叫前應該已經先查過 `find_document_by_sha256()`**
    ——這支本身不做去重判斷,只負責寫入(`doc` 是主鍵,重複呼叫是更新
    `fetched_at`,不是報錯:同一個 `doc` 名字重新上傳同一份是合法操作)。
    """
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO documents (doc, sha256, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(doc) DO UPDATE SET sha256=excluded.sha256, "
            "fetched_at=excluded.fetched_at",
            (doc, sha256, at or _now()))
        conn.commit()
    finally:
        conn.close()


def list_documents(path=None):
    conn = connect(path)
    try:
        cur = conn.execute("SELECT doc, sha256, fetched_at FROM documents ORDER BY doc")
        return [{"doc": d, "sha256": s, "fetched_at": t} for d, s, t in cur.fetchall()]
    finally:
        conn.close()


def migrate_from_json(facts_dir="facts", path=None, force=False):
    """一次性把現有 `facts/*.json` 匯入 `observations`(`extractor="legacy-import"`)。

    **不重播歷史**——現有 JSON 檔沒有逐次編輯的紀錄(`_src` 只記「現在是誰改的」,
    不記「改之前長怎樣」),所以每一格整份當一筆 observation 存進去,
    包含已經在裡面的 `_src` 標記。**這是誠實的一次性簡化**:遷移之後的新編輯
    會走 `record_ruling()`,從那時起才有真正分開的機器/人工軌跡。

    冪等保護:`facts.db` 已存在時預設拒絕(避免不小心蓋掉遷移後才發生的 rulings
    歷史),`force=True` 才會重來(刪掉舊檔重建)。
    """
    p = path or PATH
    if os.path.exists(p) and not force:
        raise RuntimeError(f"{p} 已存在,不重跑遷移。要重來請帶 force=True"
                           "(這會刪掉 migrate 之後累積的所有 rulings 歷史)。")
    if os.path.exists(p) and force:
        os.remove(p)
        for ext in ("-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)

    conn = connect(p)
    n_cells = 0
    try:
        for fp in sorted(glob.glob(f"{facts_dir}/*.json")):
            doc = os.path.basename(fp)[:-5]
            mtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(fp)).isoformat(timespec="seconds")
            part = json.load(open(fp, encoding="utf-8"))
            for key, recs in part.items():
                _, cls = key.split("|", 1)
                conn.execute(
                    "INSERT INTO observations (doc, cls, records_json, extractor, at) "
                    "VALUES (?, ?, ?, 'legacy-import', ?)",
                    (doc, cls, json.dumps(recs, ensure_ascii=False, sort_keys=True), mtime))
                n_cells += 1
            sha = hashlib.sha256(open(fp, "rb").read()).hexdigest()
            conn.execute(
                "INSERT OR REPLACE INTO documents (doc, sha256, fetched_at) VALUES (?, ?, ?)",
                (doc, sha, mtime))
        conn.commit()
    finally:
        conn.close()
    return {"cells": n_cells, "db": p}


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="facts.db 遷移 / 匯出工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="facts/*.json → facts.db")
    m.add_argument("--force", action="store_true")
    sub.add_parser("export", help="facts.db → facts/*.json(重新匯出)")
    sub.add_parser("status", help="現況:格數、db 存不存在")
    a = ap.parse_args()

    if a.cmd == "migrate":
        r = migrate_from_json(force=a.force)
        print(f"匯入 {r['cells']} 格 → {r['db']}")
    elif a.cmd == "export":
        docs = export_json()
        print(f"匯出 {len(docs)} 份文件到 facts/")
    elif a.cmd == "status":
        if exists():
            cells = materialize_cells()
            print(f"facts.db 存在:{len(cells)} 格")
        else:
            print("facts.db 不存在(仍在用 facts/*.json 直讀直寫)")


if __name__ == "__main__":
    _main()
