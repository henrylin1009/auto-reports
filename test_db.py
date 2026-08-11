#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 驗收(`docs/plan_v6_一台機器.md`):三張表(documents/observations/rulings)
是不是真的做到「共同資料模型」,不是換個地方存同一堆 JSON。

四條命題,每條都是能失敗的(不是恆真):

    D1  遷移逐位元組等價:`db.migrate_from_json()` 匯入的內容與原始 facts/*.json
        結構完全相同 —— 不多、不少、不變形
    D2  往返無損:`db.export_json()` 匯出的檔案與遷移前的檔案位元組完全相同
    D3  人工蓋過機器:同一格先寫 observation 再寫 ruling,`materialize_cells()`
        回傳的是 ruling 那份,不是先寫的那份;反過來寫也一樣(不是「後寫的贏」
        這種時序巧合,是「rulings 表優先」這條規則)
    D4  並行寫入不掉資料:N 個 thread 同時寫同一格,筆數必須是 N,不是 1

執行: python3 test_db.py     exit 0 = 全綠
"""
import glob
import json
import os
import shutil
import tempfile
import threading

import db

PASS = FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  —— {detail}" if detail else ""))


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {detail}")


def check(label, cond, detail=""):
    (ok if cond else fail)(label, detail)


def _fresh_db():
    p = tempfile.mktemp(suffix=".db")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(p + ext):
            os.remove(p + ext)
    return p


def d1_migration_is_structurally_identical():
    print("\nD1 遷移逐格結構相同(針對真實 facts/,唯讀)")
    p = _fresh_db()
    try:
        r = db.migrate_from_json(facts_dir="facts", path=p, force=True)
        check("遷移有格數回報", r["cells"] > 0, f"{r['cells']} 格")

        db_cells = db.materialize_cells(path=p)

        json_cells = {}
        for fp in sorted(glob.glob("facts/*.json")):
            json_cells.update(json.load(open(fp, encoding="utf-8")))

        check("key 集合相同", set(db_cells) == set(json_cells),
              f"db-only={sorted(set(db_cells)-set(json_cells))[:3]} "
              f"json-only={sorted(set(json_cells)-set(db_cells))[:3]}")

        diffs = [k for k in set(db_cells) | set(json_cells)
                 if json.dumps(db_cells.get(k), sort_keys=True, ensure_ascii=False)
                 != json.dumps(json_cells.get(k), sort_keys=True, ensure_ascii=False)]
        check("內容逐格相同", not diffs, f"{len(diffs)} 格有差:{diffs[:5]}")
    finally:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)


def d2_export_round_trip():
    print("\nD2 匯出往返無損(針對真實 facts/,只匯出到 tmp,不動真的 facts/)")
    p = _fresh_db()
    tmpdir = tempfile.mkdtemp(prefix="d2_")
    try:
        db.migrate_from_json(facts_dir="facts", path=p, force=True)
        docs = db.export_json(cells=db.materialize_cells(path=p), facts_dir=tmpdir)
        check("匯出了文件", len(docs) > 0, f"{len(docs)} 份")

        orig = {os.path.basename(f) for f in glob.glob("facts/*.json")}
        new = {os.path.basename(f) for f in glob.glob(f"{tmpdir}/*.json")}
        check("檔名集合相同", orig == new)

        diffs = [n for n in orig
                 if open(f"facts/{n}", "rb").read() != open(f"{tmpdir}/{n}", "rb").read()]
        check("內容逐位元組相同", not diffs, f"{len(diffs)} 個檔案有差:{diffs[:5]}")
    finally:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)
        shutil.rmtree(tmpdir, ignore_errors=True)


def _cell():
    return {"doc": "D3TEST", "class": "Trading", "source_page": 0,
            "source_kind": "附註", "total_col": "合計", "printed_total": 1,
            "rows": [{"name": "政府公債", "cols": {"合計": 1}}]}


def d3_human_beats_machine():
    print("\nD3 人工裁示永遠蓋過機器(不是時序巧合,是表優先)")
    KEY = "D3TEST|Trading"
    p = _fresh_db()
    try:
        # 順序一:先機器、後人工 —— 人工要贏
        db.record_observation({KEY: [dict(_cell(), printed_total=100)]}, path=p)
        db.record_ruling({KEY: [dict(_cell(), printed_total=999)]}, by="t", path=p)
        cells = db.materialize_cells(path=p)
        check("先機器後人工:人工贏", cells[KEY][0]["printed_total"] == 999)

        # 順序二:反過來,先人工、後機器 —— 人工還是要贏(不是「後寫的贏」)
        db.record_observation({KEY: [dict(_cell(), printed_total=12345)]}, path=p)
        cells2 = db.materialize_cells(path=p)
        check("後機器仍蓋不過先前的人工裁示(rulings 表優先,不看時間)",
              cells2[KEY][0]["printed_total"] == 999,
              f"實際 {cells2[KEY][0]['printed_total']}")

        # 注入:若 materialize_cells 改成「看哪筆 id 最大」而不分表,這條會抓到
    finally:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)


def d3b_deletion_is_a_tombstone_not_erasure():
    print("\nD3b 撤銷是墓碑,不是抹除(append-only 到底)")
    KEY = "D3BTEST|Trading"
    p = _fresh_db()
    try:
        db.record_observation({KEY: [_cell()]}, path=p)
        check("寫入後讀得到", KEY in db.materialize_cells(path=p))
        db.record_deletion(KEY, by="t", why="測試撤銷", path=p)
        check("撤銷後讀不到", KEY not in db.materialize_cells(path=p))

        conn = db.connect(p)
        n = conn.execute("SELECT count(*) FROM observations WHERE doc='D3BTEST'").fetchone()[0]
        conn.close()
        check("底層 observation 那一筆沒有被刪掉(只是被蓋過)", n == 1, f"實際 {n} 筆")
    finally:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)


def d4_concurrent_writes_all_land():
    print("\nD4 並行寫入不掉資料")
    KEY = "D4TEST|Trading"
    N = 30
    p = _fresh_db()
    errors = []

    def writer(i):
        try:
            db.record_observation(
                {KEY: [dict(_cell(), doc="D4TEST", printed_total=i)]},
                extractor=f"w{i}", path=p)
        except Exception as e:
            errors.append((i, str(e)))

    try:
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        conn = db.connect(p)
        n = conn.execute("SELECT count(*) FROM observations WHERE doc='D4TEST'").fetchone()[0]
        conn.close()
        check(f"{N} 個 thread 同時寫,筆數是 {N}(不是 1)", n == N and not errors,
              f"實際 {n} 筆,錯誤 {errors[:3]}")
    finally:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(p + ext):
                os.remove(p + ext)


if __name__ == "__main__":
    for fn in (d1_migration_is_structurally_identical, d2_export_round_trip,
               d3_human_beats_machine, d3b_deletion_is_a_tombstone_not_erasure,
               d4_concurrent_writes_all_land):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
