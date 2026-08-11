#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工裁示過的格不准被無聲覆蓋(2026-08-10 裁示,選項 1)。

**為什麼要這條**:合併兩條管線時發現兩個 `ratify` 的語意相反 ——
`v4/ledger.ratify()` 是 append-only(已裁示的拒絕覆寫,要改先顯式 `requeue()`),
`core/webdata.ratify()` 直接覆寫。合併必須挑一個,使用者裁示保留 append-only:
**人確認過的東西被機器重跑蓋掉,正是「AI 抽 + 人審補」這個框架最怕的事。**

`_src` 是唯一的標記 —— 只有人工出口會蓋(見 `facts.py` OPTIONAL_ROW),
機器抄列路徑一律不蓋,所以不需要另外發明狀態欄位。

執行: python3 test_ratify_guard.py     exit 0 = 全綠
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import facts as facts_mod
from core import webdata

PASS = FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


def eq(label, got, want):
    ok(label) if got == want else fail(label, f"got {got!r}, want {want!r}")


DOC, CLS = "202504_5843_AI3", "AC"
KEY = f"{DOC}|{CLS}"


def _rec(with_src):
    row = {"name": "政府公債", "group": None, "cols": {"合計": 100}}
    if with_src:
        row["_src"] = {"by": "henrylin", "at": "2026-08-10T12:00"}
    return {"doc": DOC, "class": CLS, "source_kind": "附註", "source_page": 1,
            "total_col": "合計", "printed_total": 100, "rows": [row]}


def main():
    # ── 標記本身 ───────────────────────────────────────────────
    eq("H1 沒有 _src ⇒ 不算人工裁示", webdata.human_ratified([_rec(False)]), False)
    eq("H2 有 _src ⇒ 算人工裁示", webdata.human_ratified([_rec(True)]), True)
    eq("H3 空的/None 不算", webdata.human_ratified(None), False)

    ws = tempfile.mkdtemp(prefix="rg_")
    try:
        # 預先放一格「人工裁示過」的
        facts_mod.save({KEY: [_rec(True)]}, ws)

        # ── 守衛 ───────────────────────────────────────────────
        try:
            webdata.ratify(DOC, CLS, [_rec(False)], facts_dir=ws)
            fail("G1 覆蓋人工裁示過的格必須被擋", "沒有拋 EditError")
        except webdata.EditError as e:
            ok("G1 覆蓋人工裁示過的格被擋下")
            if "revoke" in str(e):
                ok("G1b 錯誤訊息有指出撤銷的方法")
            else:
                fail("G1b 錯誤訊息沒說怎麼撤銷", str(e)[:80])

        # 資料沒被動到
        eq("G2 被擋下時原資料原封不動",
           facts_mod.load(ws)[KEY][0]["rows"][0]["cols"]["合計"], 100)

        # ── 撤銷 ───────────────────────────────────────────────
        r = webdata.revoke(DOC, CLS, why="測試", facts_dir=ws)
        eq("R1 撤銷成功", r["revoked"], True)
        eq("R1b 有記錄它原本是人工裁示過的", r["was_human_ratified"], True)
        eq("R2 撤銷後該格不在事實庫", KEY in facts_mod.load(ws), False)
        eq("R3 重複撤銷不炸,回 False",
           webdata.revoke(DOC, CLS, facts_dir=ws)["revoked"], False)

        # ── 撤銷之後可以重新寫入 ───────────────────────────────
        facts_mod.save({KEY: [_rec(False)]}, ws)      # 機器重填
        eq("R4 撤銷後機器填的那份不帶 _src",
           webdata.human_ratified(facts_mod.load(ws)[KEY]), False)
        try:
            webdata.ratify(DOC, CLS, [_rec(False)], facts_dir=ws)
            ok("R5 沒有 _src 的格可以正常裁示(守衛不誤傷)")
        except webdata.EditError as e:
            fail("R5 守衛誤傷了沒被人動過的格", str(e)[:80])
    finally:
        shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    print("== 人工裁示不可被無聲覆蓋 ==")
    main()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
