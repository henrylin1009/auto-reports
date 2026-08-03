# -*- coding: utf-8 -*-
"""**唯一允許寫入 `data.json` 的程式。** 過渡期建置:v2 凍結快照保底 + v3 逐單位取代。

規格見 `docs/plan_phase1_build.md`。五條鐵則:

1. **唯一寫入者。** `bridge_v2` / `bridge_v3` 已加寫入防護,只剩這裡。
2. **當次重建。** v3 的數字一律在本次執行內由 `facts/` + 現行分類邏輯算出
   (`results.build()`)。**絕不讀 `results/verdict.json`** —— 那個落地檔實測
   落後過 25 小時且缺 22 格,而且是在分類表已知有 bug 的時候算的。
   `_assert_no_stale_verdict()` 把這條寫成執行期斷言,不是靠自律。
3. **回退保底。** 單位不合格 → 用凍結快照的值,並記錄**具體**原因。
4. **禁止 null 覆寫。** v3 的 null 永遠不會抹掉 v2 的數字。這條擋的是
   「v3 說某口徑文件裡不存在」的 8 處實測衝突 —— 抹掉會改變已發布的財務數字。
5. **保留集排除。** `holdout.HOLDOUT` 的格永不進入發布。

發布單位是**四元組** `(期別, 銀行, 類別, 口徑)`。三元組不夠:同一個
`(期別,銀行,類別)` 底下 v3 可能只有一個口徑合格(實測 8 處),用三元組採用 v3
就會把另一個口徑的 v2 數字抹成 null。

    python3 build.py            # dry-run:寫 preview/,印差異。**預設**
    python3 build.py --diff     # 只印差異,不寫任何檔
    python3 build.py --write    # 寫 ./data.json(先備份)。Phase 1 不執行
"""
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

import bridge_v3
import facts
import holdout
import results
from config import WIDE_BUCKETS

SNAP_DIR = "snapshots"
SNAP_MANIFEST = f"{SNAP_DIR}/MANIFEST.json"
PREVIEW_DIR = "preview"
DATA = "data.json"
MANIFEST = "build_manifest.json"

#: 發布單位涵蓋的兩個口徑。`wide` = 帳面(公允 / 攤銷後成本);`wide_cost` = 取得成本。
BASES = ("wide", "wide_cost")

#: **不在 Phase 1 發布範圍**,整塊沿用快照:合併報表(`bridge_v3.cell_of` 對 AI1 回 None)。
PASSTHROUGH = ("wide_consol", "wide_cost_consol")


# ── 輸入指紋 ────────────────────────────────────────────────────────────────

def _sha(*paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode())
        h.update(open(p, "rb").read())
    return h.hexdigest()


def _git_rev():
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                                    text=True, timeout=10).stdout.strip())
        return {"git": rev or None, "dirty": dirty}
    except Exception:
        return {"git": None, "dirty": None}


def load_snapshot():
    """讀凍結快照 + 其 manifest。**唯讀** —— 這支程式任何路徑都不得寫回去。"""
    man = json.load(open(SNAP_MANIFEST, encoding="utf-8"))
    path = man["path"]
    raw = open(path, "rb").read()
    got = hashlib.sha256(raw).hexdigest()
    if got != man["sha256"]:
        raise SystemExit(f"✗ 凍結快照 {path} 的 sha256 與 MANIFEST 不符 —— 它被改過了。\n"
                         f"  MANIFEST: {man['sha256']}\n  實際     : {got}")
    return json.loads(raw), man


def _assert_no_stale_verdict():
    """鐵則 2 的執行期保證:本次建置不得使用落地的 `results/verdict.json`。

    做法是**證明它沒被讀**:把它的 mtime 記下來,建置完再比。純自律沒有價值 ——
    `bridge_v3.py:89` 就是自律失敗的實例(它讀落地檔,而那個檔落後了 25 小時)。
    """
    p = f"{results.OUT}/verdict.json"
    return (p, os.path.getmtime(p)) if os.path.exists(p) else (p, None)


# ── v3 當次重建 ────────────────────────────────────────────────────────────

def rebuild_v3():
    """**當次**由 facts/ 重算 verdict。回傳 (verdict, facts_sha, cells 數)。"""
    cells = facts.load()
    train, _leak = holdout.split(cells)          # 保留集永不進入發布
    verdict, _audit = results.build(train)
    return verdict, _sha(*glob.glob("facts/*.json")), len(train)


def eligible(v, basis, src="v3"):
    """單位是否有發布資格。回傳 (bool, 原因)。**保守:任一不成立即回退。**
    `src` 只影響訊息文字("v3"/"v4"),判準兩邊共用同一套(pass + 七桶齊全)。
    """
    if v is None:
        return False, f"{src} 沒有這一格"
    if not v.get("pass"):
        return False, f"{src} 該格檢查未通過"
    book = v.get(basis)
    if book is None:
        return False, f"{src} 該口徑為 null(該口徑在文件裡不存在或視圖不成立)"
    missing = [b for b in WIDE_BUCKETS if b not in book]
    if missing:
        return False, f"{src} 七桶不齊,缺 {missing}"
    return True, f"{src} 合格"


# ── v4 當次重建 ────────────────────────────────────────────────────────────
# docs/plan_v5_統一.md P1-3。**只當 v3 的缺口填補者,不搶 v3 的位置**——
# v4 目前只跑過 2 份文件(P1-4 批次還沒跑),coverage 遠低於 v3 的 62~123 個
# 合格單位,若讓 v4 優先於 v3,今天會直接讓大部分已發布的 v3 數字消失。
# 要等 P2(拿 facts/ 156 格真值逐桶比對)證明 v4 不比 v3 差,才會反過來。

def rebuild_v4():
    """**當次**由 `v4/ledger` 重算 verdict,形狀跟 `rebuild_v3()` 一樣方便共用
    `eligible()`。只吃 RATIFIED / GREEN——RED/GREY 一律不算數,交回 v3 或 v2。
    """
    from v4 import adapter, ledger

    verdict = {}
    for doc_entry in ledger.load_all():
        doc = doc_entry["doc"]
        for cls, c in doc_entry["cells"].items():
            passed = c.get("status") in ("RATIFIED", "GREEN")
            book_raw = c.get("book") or {}
            wide_book = book_as_cost = None
            agg_ok = False
            if passed and book_raw.get("rows") is not None:
                agg = adapter.aggregate(book_raw["rows"], book_raw.get("printed_subtotal"))
                agg_ok = agg.ok
                if agg.ok:
                    # **口徑決定它進哪一欄,不是進哪一欄決定口徑。**
                    # 逐項有評價調整列 ⇒ 這七桶是成本,而評價調整是一整筆不分桶,
                    # 所以「逐桶帳面」在文件裡不存在 → wide 必須 null
                    # (與 `wide.py:99`「所有來源逐項皆為成本口徑」同一條規則)。
                    # 之前這裡無條件寫進 wide,實測 20 格把成本當帳面發布,
                    # 兆豐 Trading 差 11.82%。七桶本身仍然有效,改走 wide_cost。
                    if agg.basis == "公允":
                        wide_book = agg.book
                    else:
                        book_as_cost = agg.book
            # RATIFIED 的 book 是 `v4.ledger.ratify()` 凍結進帳本的那份,沒有連帶
            # 存 cost(`ratify()` 簽名只收 book,見 v4/ledger.py)。
            cost_raw = c.get("cost") or {}
            wide_cost = None
            if passed and cost_raw.get("rows") is not None:
                agg_c = adapter.aggregate(cost_raw["rows"], cost_raw.get("total"))
                if agg_c.ok:
                    wide_cost = agg_c.book
            # 明細表的取得成本欄優先(那是文件直接印的成本);沒有時才用上面推出來的
            # ——兩者都是成本,但前者是獨立來源,後者是同一份 book 換個口徑解讀。
            if wide_cost is None:
                wide_cost = book_as_cost
            verdict[f"{doc}|{cls}"] = {
                "doc": doc, "class": cls,
                # `pass` = 這格的閘門過了,**與它落在哪個口徑欄無關**(同 results.py:53
                # 的 v3 語義)。`eligible()` 會另外檢查該口徑是不是 null,
                # 並回「該口徑在文件裡不存在」——那句話正是這種格子該有的說法。
                "pass": passed and agg_ok,
                "wide": wide_book, "wide_cost": wide_cost,
                "anchor": book_raw.get("bs_anchor"),
            }
    return verdict


# ── 建置 ────────────────────────────────────────────────────────────────────

def build():
    """回傳 (data, manifest, diff)。`data` 是新的發布 payload;`diff` 是與快照的差異。"""
    snap, snap_man = load_snapshot()
    verdict, facts_sha, n_cells = rebuild_v3()
    verdict_v4 = rebuild_v4()

    data = json.loads(json.dumps(snap))          # 深拷貝,快照本身不動
    data.pop("_bridge_v3", None)                 # 舊的 bridge_v3 遺物,不再使用

    # 格 key → v3 verdict(只取個體報表 AI3;AI1 合併報表 cell_of 回 None)
    by_cell = {}
    for key, v in verdict.items():
        got = bridge_v3.cell_of(key)
        if got:
            by_cell[got] = (key, v)
    # v4 用同一把 `bridge_v3.cell_of`(doc 命名規則相同,函式名字沒改是因為
    # 它本質是「解析 doc key」不是「v3 專用」)。**只在 v3 沒有這一格時才查**,
    # 見下面迴圈 —— v4 目前只跑過少數文件,絕不能搶 v3 已經覆蓋的格。
    by_cell_v4 = {}
    for key, v in verdict_v4.items():
        got = bridge_v3.cell_of(key)
        if got:
            by_cell_v4[got] = (key, v)

    units, diff, conflicts = [], {}, []
    for basis in BASES:
        table = data.setdefault(basis, {})
        for cell in sorted(table):
            # 快照裡這一格本身可能是 `None`(尚無任何 v2 數字,例如 2020H1/2026 那些
            # 還沒出報表或還沒抓到的期別)——`setdefault` 只在**鍵不存在**時才給預設值,
            # 鍵存在但值是 None 時它會原封不動回傳 None,下面 `[...] = new` 就會對
            # `None` 做 item assignment 而炸掉。這裡先正規化一次。
            if table.get(cell) is None:
                table[cell] = {}
            bank_period = cell
            for cls in ("Trading", "OCI", "AC"):
                cur = table[cell]
                key, v = by_cell.get((cell, cls), (None, None))
                ok, why = eligible(v, basis, src="v3")
                src = "v3"
                if not ok:
                    # v3 沒有這一格(或不合格)才問 v4 —— v3 永遠優先,理由見
                    # `rebuild_v4()` 檔頭:v4 batch 還沒跑,coverage 遠小於 v3。
                    key4, v4v = by_cell_v4.get((cell, cls), (None, None))
                    ok4, why4 = eligible(v4v, basis, src="v4")
                    if ok4:
                        ok, why, key, v, src = ok4, why4, key4, v4v, "v4"
                unit = f"{bank_period}|{cls}|{basis}"
                had = {b: cur.get(f"{cls}_{b}") for b in WIDE_BUCKETS}
                has_v2 = any(x is not None for x in had.values())

                if ok:
                    book = v[basis]
                    changed = {}
                    for b in WIDE_BUCKETS:
                        new = bridge_v3.to_yi(book[b])
                        if had[b] != new:
                            changed[f"{cls}_{b}"] = (had[b], new)
                        table[cell][f"{cls}_{b}"] = new
                    if changed:
                        diff[unit] = changed
                    units.append({"unit": unit, "provenance": src, "reason": why,
                                  "facts_key": key})
                else:
                    # 鐵則 4:**不寫任何東西**。快照的值原封不動留著。
                    units.append({"unit": unit, "provenance": "v2", "reason": why,
                                  "facts_key": key})
                    if v is not None and v.get("pass") and v.get(basis) is None and has_v2:
                        conflicts.append({"unit": unit, "reason": why,
                                          "v2_columns": [k for k, x in had.items() if x is not None],
                                          "note": "v3 判該口徑文件裡不存在,但 v2 有數字 —— "
                                                  "保留 v2(抹成 null 會改變已發布財務數字),待裁示"})

    for k in PASSTHROUGH:
        if k in snap:
            units.append({"unit": k, "provenance": "v2",
                          "reason": "合併報表(AI1):v3 尚無網站格映射,整塊沿用快照"})

    # data.json 內只放**確定性**的 _build(不含 timestamp),保證同輸入 byte-identical
    data["_build"] = {
        "built_by": "build.py",
        "publish_unit": "(期別, 銀行, 類別, 口徑)",
        "frozen_snapshot": {"path": snap_man["path"], "sha256": snap_man["sha256"]},
        "facts_sha256": facts_sha,
        "decisions_sha256": _sha("buckets.py", "config.py"),
        "manifest": MANIFEST,
        "note": "唯一寫入者是 build.py。v3 逐單位取代,其餘回退凍結快照;"
                "v3 的 null 不會抹掉 v2 的數字。",
    }

    manifest = {
        "build_timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "code_revision": _git_rev(),
        "inputs": {
            "frozen_snapshot": {"path": snap_man["path"], "sha256": snap_man["sha256"],
                                "source": snap_man["source"]["from"]},
            "facts": {"sha256": facts_sha, "cells": n_cells},
            "decisions": {"sha256": _sha("buckets.py", "config.py"),
                          "files": ["buckets.py", "config.py"]},
        },
        "counts": {
            "v3": sum(1 for u in units if u["provenance"] == "v3"),
            "v4": sum(1 for u in units if u["provenance"] == "v4"),
            "v2": sum(1 for u in units if u["provenance"] == "v2"),
            "changed_units": len(diff),
            "conflicts": len(conflicts),
        },
        "conflicts": conflicts,
        "units": units,
    }
    return data, manifest, diff


# ── 輸出 ────────────────────────────────────────────────────────────────────

def dump(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)


def report(manifest, diff):
    c = manifest["counts"]
    print(f"發布單位:v3 {c['v3']} / v4 {c['v4']} / v2 {c['v2']}   "
          f"有變動 {c['changed_units']} 個單位")
    print(f"輸入:facts {manifest['inputs']['facts']['cells']} 格 "
          f"· 快照 {manifest['inputs']['frozen_snapshot']['path']}")
    if diff:
        print(f"\n{len(diff)} 個單位的數字有變動(億元):")
        for unit, cols in sorted(diff.items()):
            print(f"\n  {unit}")
            for col, (old, new) in sorted(cols.items()):
                print(f"      {col:<16} {str(old):>9} → {str(new):>9}")
    if manifest["conflicts"]:
        print(f"\n⚠ {len(manifest['conflicts'])} 處衝突(v3 判 null 而 v2 有值,**已保留 v2**):")
        for x in manifest["conflicts"]:
            print(f"    {x['unit']:<34} v2 有 {len(x['v2_columns'])} 欄 —— {x['reason']}")


def main(argv):
    stale = _assert_no_stale_verdict()
    data, manifest, diff = build()
    after = os.path.getmtime(stale[0]) if os.path.exists(stale[0]) else None
    assert after == stale[1], "build 期間動到了 results/verdict.json —— 鐵則 2 被違反"

    report(manifest, diff)

    if "--diff" in argv:
        print("\n（--diff:未寫任何檔）")
        return 0
    if "--write" in argv:
        if os.path.exists(DATA):
            shutil.copy(DATA, DATA + ".pre_build")
        dump(data, DATA)
        dump(manifest, MANIFEST)
        print(f"\n已寫入 {DATA} 與 {MANIFEST}(備份 {DATA}.pre_build)")
        return 0
    dump(data, f"{PREVIEW_DIR}/{DATA}")
    dump(manifest, f"{PREVIEW_DIR}/{MANIFEST}")
    print(f"\n[dry-run] 已寫入 {PREVIEW_DIR}/ —— 線上 {DATA} 未動。"
          f"要正式寫入請加 --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
