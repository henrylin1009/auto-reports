#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_acquire.py — 取得層的口徑維度 (A1-A7)

**背景(這支測試存在的理由)**:2026-08-12 之前,取得層只抓得到個體。
後果不只是「合併要手動」,而是合併整條路變成一個死結:

    expected_banks(合併) 只列「已經有合併檔的那幾家」
      → 沒檔就沒欄 → 沒欄就沒格可按 → 唯一進料口只剩拖放上傳,
        而且順序是反的(得先把檔拖進來,那一欄才會長出來)。

使用者要在合併網格上加國泰時撞到的就是這個:`add_bank()` 回「國泰已經在
清單裡」——完全正確,卻答的是另一個問題。A1 就是釘住這件事。

**A3 是這支測試的重點,也是最容易寫成恆真閘門的一條**:fetch_log 的 key
以前是 `{period}_{code}`,不帶口徑。同一期同一家的個體與合併是兩件獨立的
事實(TWSE 可以有其中一個而沒有另一個),共用 key 會讓「問過個體得到
absent」把合併那格也染成「查無」——兩種原因一種結果,鐵律 9。

## 怎麼確認這支不是恆真閘門(實際做過)

    A1  把 acquire.expected_banks() 改回 `if basis != SOLO: return []`   → A1 紅
    A3  把 acquire._key() 改回 `f"{period}_{code}"`                       → A3 紅
    A4  把 resolve.report_filename() 的 `kind == basis` 改回 `== SOLO`   → A4 紅
    A6  把 fetch_one() 的 `basis=basis` 拿掉(用 download 預設)          → A6 紅

**不打 TWSE**。A6 用 monkeypatch 攔 `resolve.download`,驗的是「口徑有沒有
一路傳到底」與「記進 log 的 key 對不對」,不是網路。

執行方式: python3 test_acquire.py       exit 0 = 全綠
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import docid
import locate
import resolve
from core import acquire

PASS = 0
FAIL = 0


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


# ── TWSE 清單的形狀 ───────────────────────────────────────────────────
# 真實清單的關鍵性質:同一期同時有個體與合併兩列,而且**列描述在連結之前**,
# 600 字窗口會跨到上一列(`resolve.report_filename` 的註解記著這個事故)。
# 這裡刻意把合併列排在個體列後面,讓合併列的窗口裡同時看得到自己的「合併」
# 與上一列的「個體」——最近標籤演算法必須挑近的那個。
LIST_HTML = """
<tr><td>112年度個體財務報告</td>
    <td><a href="#" onclick='readfile2("A","5835","202304_5835_AI3.pdf")'>下載</a></td></tr>
<tr><td>112年度合併財務報告</td>
    <td><a href="#" onclick='readfile2("A","5835","202304_5835_AI1.pdf")'>下載</a></td></tr>
"""


# ── A1 合併網格的欄位 ─────────────────────────────────────────────────

def a1_expected_banks_ignores_basis():
    """兩個口徑都回全部銀行 —— 國泰要出現在合併網格上。"""
    want = sorted(config.BANKS.values())
    eq("A1a expected_banks() 回全部設定裡的銀行", acquire.expected_banks(), want)
    # 死結的實質:合併網格上「有沒有國泰」不能取決於磁碟上有沒有國泰的合併檔。
    got = acquire.expected_banks()
    if "國泰" in got:
        ok("A1b 國泰在清單裡(不看 pdf_cache 有沒有它的合併檔)")
    else:
        fail("A1b", f"國泰不在 {got}")


# ── A2 檔名帶口徑 ─────────────────────────────────────────────────────

def a2_doc_name_carries_basis():
    eq("A2a doc_name 預設是個體",
       acquire.doc_name("202304", "5835"), "202304_國泰_個體")
    eq("A2b doc_name 收合併",
       acquire.doc_name("202304", "5835", locate.CONSOLIDATED), "202304_國泰_合併")
    # 兩個口徑不可以組出同一個名字,否則下游整個對不上。
    if acquire.doc_name("202304", "5835", locate.SOLO) != \
       acquire.doc_name("202304", "5835", locate.CONSOLIDATED):
        ok("A2c 兩個口徑組出不同檔名")
    else:
        fail("A2c", "個體與合併組出同一個檔名")


# ── A3 fetch_log 的 key 帶口徑 ────────────────────────────────────────

def a3_log_key_separates_bases():
    """個體問到 absent,不可以讓合併那格也變成 absent。"""
    log = {acquire._key("202304", "5835", locate.SOLO): {"status": "absent"}}
    solo = acquire.cell_fetch_state("202304", "5835", set(), log, locate.SOLO)
    cons = acquire.cell_fetch_state("202304", "5835", set(), log, locate.CONSOLIDATED)
    eq("A3a 個體那格讀到 absent", solo, "absent")
    eq("A3b 合併那格仍是 missing(沒問過)", cons, "missing")

    # 反向:有檔的那一格回 None(交給抄列那條線判),而且只認自己口徑的檔。
    present = {"202304_國泰_合併"}
    eq("A3c 合併有檔 → 不是抓檔問題",
       acquire.cell_fetch_state("202304", "5835", present, {}, locate.CONSOLIDATED), None)
    eq("A3d 合併有檔不會讓個體那格以為自己有檔",
       acquire.cell_fetch_state("202304", "5835", present, {}, locate.SOLO), "missing")


# ── A4 舊 key 遷移 ────────────────────────────────────────────────────

def a4_old_log_keys_migrate():
    """帶口徑之前寫下的紀錄一律是個體(當時 fetch_one 第一行就擋掉非個體)。"""
    ws = tempfile.mkdtemp(prefix="acq_")
    old_log = acquire.LOG
    try:
        acquire.LOG = os.path.join(ws, "fetch_log.json")
        os.makedirs(os.path.dirname(acquire.LOG), exist_ok=True)
        json.dump({"202304_5835": {"status": "absent", "at": "2026-01-01T00:00:00"},
                   "202302_5847_合併": {"status": "ok", "at": "2026-01-02T00:00:00"}},
                  open(acquire.LOG, "w", encoding="utf-8"), ensure_ascii=False)
        log = acquire.load_log()
        eq("A4a 舊 key 補成個體", sorted(log),
           sorted(["202304_5835_個體", "202302_5847_合併"]))
        eq("A4b 遷移後的舊紀錄查得到",
           acquire.cell_fetch_state("202304", "5835", set(), log, locate.SOLO), "absent")
        eq("A4c 舊紀錄不會污染合併",
           acquire.cell_fetch_state("202304", "5835", set(), log,
                                    locate.CONSOLIDATED), "missing")
    finally:
        acquire.LOG = old_log
        shutil.rmtree(ws, ignore_errors=True)


# ── A5 TWSE 清單解析認得兩個口徑 ──────────────────────────────────────

def a5_report_filename_picks_by_basis():
    solo = resolve.report_filename(LIST_HTML, "202304", docid.SOLO)
    cons = resolve.report_filename(LIST_HTML, "202304", docid.CONSOLIDATED)
    eq("A5a 個體挑到 AI3 那列", solo, "202304_5835_AI3.pdf")
    eq("A5b 合併挑到 AI1 那列", cons, "202304_5835_AI1.pdf")
    if solo != cons:
        ok("A5c 兩個口徑挑到不同列(不是同一份檔改名兩次)")
    else:
        fail("A5c", f"兩個口徑都挑到 {solo}")
    eq("A5d 清單裡沒有的期別回 None",
       resolve.report_filename(LIST_HTML, "202204", docid.SOLO), None)
    # 不認得的口徑要當場炸,不要靜靜回 None —— 那會被記成 absent(「TWSE 沒有」),
    # 把一個打錯的參數說成一個關於世界的事實。
    try:
        resolve.report_filename(LIST_HTML, "202304", "隨便")
        fail("A5e", "不認得的口徑沒有丟例外")
    except ValueError:
        ok("A5e 不認得的口徑丟 ValueError,不是靜靜回 None")


# ── A6 口徑一路傳到 resolve,並記進正確的 key ─────────────────────────

def a6_fetch_one_threads_basis():
    """攔掉 download,只驗兩件事:傳下去的 basis、記回來的 key。"""
    ws = tempfile.mkdtemp(prefix="acq_")
    old_log, old_dl = acquire.LOG, resolve.download
    seen = []
    try:
        acquire.LOG = os.path.join(ws, "fetch_log.json")

        def fake(code, roc, month, tries=4, basis=docid.SOLO):
            seen.append({"code": code, "roc": roc, "month": month, "basis": basis})
            return None                       # 一律回「清單上沒有」→ 記成 absent

        resolve.download = fake
        acquire.fetch_one("202304", "5835", locate.CONSOLIDATED)
        eq("A6a basis 傳到 resolve.download", seen[-1]["basis"], locate.CONSOLIDATED)
        eq("A6b 民國年換算正確", (seen[-1]["roc"], seen[-1]["month"]), (112, "04"))

        log = acquire.load_log()
        eq("A6c 記在帶口徑的 key 底下", sorted(log), ["202304_5835_合併"])
        eq("A6d absent 的理由說得出是哪個口徑",
           log["202304_5835_合併"]["why"], "TWSE 清單上沒有這期的合併檔")

        acquire.fetch_one("202304", "5835", locate.SOLO)
        eq("A6e 個體另外記一筆,不覆蓋合併那筆", sorted(acquire.load_log()),
           sorted(["202304_5835_個體", "202304_5835_合併"]))
    finally:
        acquire.LOG, resolve.download = old_log, old_dl
        shutil.rmtree(ws, ignore_errors=True)


# ── A7 待抓清單帶著口徑走 ─────────────────────────────────────────────

def a7_missing_cells_carry_basis():
    """`server._fetch_run` 直接把這些 dict 交給 `fetch_one` —— 漏了 basis
    就會把合併那批當成個體去抓,而且抓回來還會覆蓋個體的檔。"""
    cells = acquire.missing_cells(locate.CONSOLIDATED, set(), log={})
    if not cells:
        fail("A7a", "合併沒有任何待抓格 —— 期別或欄位生成掛了")
        return
    bad = [c for c in cells if c.get("basis") != locate.CONSOLIDATED]
    eq("A7a 每一筆都帶合併口徑", bad, [])
    banks = {config.BANKS[c["code"]] for c in cells}
    if "國泰" in banks:
        ok("A7b 國泰的合併期別在待抓清單裡")
    else:
        fail("A7b", f"待抓清單只有 {sorted(banks)}")
    # 合併有四季,個體只有半年報/年報 —— 兩者期別本來就不同,不是設定。
    months = {c["period"][4:] for c in cells}
    eq("A7c 合併涵蓋四季", sorted(months), ["01", "02", "03", "04"])


if __name__ == "__main__":
    for fn in (a1_expected_banks_ignores_basis, a2_doc_name_carries_basis,
               a3_log_key_separates_bases, a4_old_log_keys_migrate,
               a5_report_filename_picks_by_basis, a6_fetch_one_threads_basis,
               a7_missing_cells_carry_basis):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'=' * 50}\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
