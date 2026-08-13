# -*- coding: utf-8 -*-
"""**唯一允許寫入 `data.json` 的程式。** 四張發布表全部由 `facts/` 當次重建。

規格見 `docs/plan_phase1_build.md`。四條鐵則:

1. **唯一寫入者。** `bridge_v2` / `bridge_v3` 已退場,只剩這裡。
2. **當次重建。** 數字一律在本次執行內由 `facts/` + 現行分類邏輯算出
   (`results.build()`)。**絕不讀 `results/verdict.json`** —— 那個落地檔實測
   落後過 25 小時且缺 22 格,而且是在分類表已知有 bug 的時候算的。
   `_assert_no_stale_verdict()` 把這條寫成執行期斷言,不是靠自律。
3. **一格只有兩種下場:有數字,或 null。** 不合格就寫 null,並記錄**具體**原因。
   前端把 null 畫成灰底斜紋 —— 看得出來是缺的。
4. **保留集排除。** `holdout.HOLDOUT` 的格永不進入發布。

⚠️ **2026-08-10 拿掉了「v2 凍結快照保底」。** 原本不合格的格子會沿用 v2 的數字,
實測結果是 383 個發布單位裡 **194 個(51%)由 v2 供應**,而那些數字沒有經過
這支程式的任何一道閘門 —— 「該擋的會被擋住」在當時是假的。其中 88 個的理由是
「v3 判該口徑文件裡不存在」,也就是 **v2 很可能印了一個文件裡根本沒有的數字**
(`docs/` 的逐頁普查:9 格裡 7 格文件真的只有一個口徑)。
代價量過:93 個原本有數字的單位變 null,只有 4 個(期別×銀行)整格全空
—— 2022H1 中信/國泰/玉山、2025H1 富邦。使用者 2026-08-10 裁示:缺就顯示缺。

發布單位是**四元組** `(期別, 銀行, 類別, 表)`。三元組不夠:同一個
`(期別,銀行,類別)` 底下可能只有一個口徑成立(實測 8 處),分開記才看得出來
是「另一個口徑不存在」而不是「整格沒抄」。

    python3 build.py            # dry-run:寫 preview/,印差異。**預設**
    python3 build.py --diff     # 只印差異,不寫任何檔
    python3 build.py --write    # 寫 ./data.json(先備份)。Phase 1 不執行
"""
import collections
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

import config
import facts
import fill
import holdout
import results
from config import CLASSES, WIDE_BUCKETS
from core import report

SNAP_DIR = "snapshots"
SNAP_MANIFEST = f"{SNAP_DIR}/MANIFEST.json"
PREVIEW_DIR = "preview"
DATA = "data.json"
MANIFEST = "build_manifest.json"

#: 發布單位涵蓋的兩個口徑。`wide` = 帳面(公允 / 攤銷後成本);`wide_cost` = 取得成本。
#: 順序要與 `core.report.TABLES` 的值對齊(個體/合併各一組帳面+成本表)。
BASES = ("wide", "wide_cost")

#: `provenance` 的第三種值:這一格**沒有任何合格來源**,發布 null。
#: 不是「壞掉」也不是「還沒抄」—— 是哪一種,看同一筆的 `reason`。
NONE_SRC = "none"


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
    已刪除的 `bridge_v3.py` 就是自律失敗的實例(它讀落地檔,而那個檔落後過 25 小時)。
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


# ── 為什麼沒有 rebuild_v4() ────────────────────────────────────────────────
# 2026-08-11(`docs/plan_v6_一台機器.md` R0-4)砍掉。**不要加回來。**
#
# 它原本的角色是「v3 的缺口填補者」:v3 不合格的格改問 v4。實測之後發現
# 這個安排在做的事情是**把驗不到的東西當成驗過的發布出去**:
#
#   由 v4 供應的 40 個發布單位(34 格)裡,check_anchor(合計 == BS 錨)
#   只有 6 格是 OK,**其餘 28 格是 `no_witness`** —— 不是對不上,是沒有錨、
#   根本沒驗。而 `classify_cell()` 的 GREEN 判準只看「硬閘門有沒有 MISMATCH」,
#   `no_witness` 不是 MISMATCH,於是這 28 格一路 GREEN 到發布。
#
# 同一批格在 v3 這邊是「④這個類別沒有錨,無法檢查閉合」→ 擋下。
# **兩條管線對同一件事的判斷相反**:v4 說「驗不到 = 通過」,v3 說「驗不到 = 擋」。
# 這正是 R0-0 在 `core/closure.py` 修掉的那個 conflation,只是換到了分流這一層。
#
# 專案的最高原則(`docs/plan_v4_執行計畫.md` §0)是:
#   **任何發布出去的數字,都必須有算術證明它對得上資產負債表;
#     證不了的一律是 null,不准猜。**
# 依這條原則,那 40 個單位本來就不該在網站上。砍掉 rebuild_v4() 之後它們變成
# null,**這不是回歸,是把一個一直都在的錯誤停掉**。
#
# 要救它們的正確做法是把錨補回來(重跑 reader / 改 prompt,讓 `bs_anchor`
# 真的讀到),不是放寬分流規則讓 `no_witness` 繼續當 GREEN。

# ── 建置 ────────────────────────────────────────────────────────────────────

def build():
    """回傳 (data, manifest, diff)。`data` 是新的發布 payload;`diff` 是與前一版的差異。"""
    snap, snap_man = load_snapshot()
    verdict, facts_sha, n_cells = rebuild_v3()
    bmap = fill.basis_map()

    data = json.loads(json.dumps(snap))          # 深拷貝,快照本身不動
    data.pop("_bridge_v3", None)                 # 舊的 bridge_v3 遺物,不再使用
    data.pop("_bridge", None)                    # bridge_v2 的落款,已無來源可言

    def by_cell_of(vd):
        """verdict → `{(報表口徑, 格, 類別): [(facts_key, verdict), ...]}`。

        口徑一律走 `fill.basis_map()`(封面判),不看 doc 名字裡的 AI 編號 ——
        舊版寫死 AI3,合併報表因此整張網格永遠是空的。

        ⚠️ **值是 list,因為一格真的可能對到多份文件。** 實測:玉山 2021H1 的
        同一份 PDF 被存成 `202102_5847_AI2` 與 `_AI3` 兩個檔名(sha256 完全相同,
        是重複抓檔),兩份都判個體、都對到 `2021H1|玉山`。舊版寫死 AI3 時 AI2
        被順手擋掉;拿掉寫死之後如果還用 dict 直接覆寫,**誰贏由插入順序決定** ——
        AI2 只抄了 2 列、AI3 抄了 7 列,順序一翻那格就從有數字變成沒數字,
        而且沒有任何檢查看得到。挑選規則見 `pick()`。
        """
        out = collections.defaultdict(list)
        for key in sorted(vd):          # 排序:結果不隨 dict 插入順序改變
            b = bmap.get(key.split("|")[0])
            got = report.cell_of(key, b)
            if got:
                out[(b, got[0], got[1])].append((key, vd[key]))
        return out

    by_cell = by_cell_of(verdict)

    def pick(cands, basis, src):
        """一格的候選文件 → `(facts_key, verdict, ok, 理由)`。

        規則:**取唯一合格的那份。** 多份都合格時,數字一致才放行(同一份 PDF
        抄兩次本來就該一致);不一致就是真衝突,擋下來寫 null 並把文件列出來 ——
        這種時候猜哪份對,錯了沒有任何人看得見。
        """
        okd = [(k, v) for k, v in cands if eligible(v, basis, src)[0]]
        if len(okd) == 1:
            return okd[0][0], okd[0][1], True, f"{src} 合格"
        if len(okd) > 1:
            books = {json.dumps(v[basis], sort_keys=True) for _, v in okd}
            if len(books) == 1:
                return okd[0][0], okd[0][1], True, \
                    f"{src} 合格(同一格 {len(okd)} 份文件,七桶一致)"
            return okd[0][0], okd[0][1], False, \
                f"{src} 同一格有 {len(okd)} 份文件且數字不一致:{[k for k, _ in okd]}"
        if cands:
            return cands[0][0], cands[0][1], False, eligible(cands[0][1], basis, src)[1]
        return None, None, False, f"{src} 沒有這一格"

    units, diff, blanked = [], {}, []
    for rep_basis, tables in report.TABLES.items():
        for basis, table_name in zip(BASES, tables):
            old = data.get(table_name) or {}
            # 格的宇宙 = 前一版有的 ∪ 這次算得出來的。取聯集是為了讓新抄出來的
            # 期別/銀行能自己長出來,而不是被前一版的鍵列表悄悄擋掉。
            cells = sorted(set(old) | {c for (b, c, _) in by_cell if b == rep_basis})
            table = {}
            for cell in cells:
                cur = old.get(cell) or {}
                table[cell] = {}
                for cls in CLASSES:
                    key, v, ok, why = pick(by_cell.get((rep_basis, cell, cls), []),
                                           basis, "v3")
                    src = "v3"
                    unit = f"{cell}|{cls}|{table_name}"
                    had = {b: cur.get(f"{cls}_{b}") for b in WIDE_BUCKETS}

                    book = v[basis] if ok else None
                    changed = {}
                    for b in WIDE_BUCKETS:
                        new = report.to_yi(book[b]) if book else None
                        if had[b] != new:
                            changed[f"{cls}_{b}"] = (had[b], new)
                        table[cell][f"{cls}_{b}"] = new
                    if changed:
                        diff[unit] = changed
                    units.append({"unit": unit, "provenance": src if ok else NONE_SRC,
                                  "reason": why, "facts_key": key})
                    if not ok and any(x is not None for x in had.values()):
                        blanked.append({"unit": unit, "reason": why,
                                        "dropped_columns": [k for k, x in had.items()
                                                            if x is not None]})
            data[table_name] = table

    # `banks`/`periods` 也要從當次算出來的格子長出來,**不能沿用凍結骨架**。
    # ⚠️ 這是「新銀行永遠上不了網站」的根因(2026-08-14 修):格的宇宙上面已經
    #    取聯集、華南 2025H2 的 28 個欄位確實算出來了,但 `data["banks"]` 整份
    #    是從 2026-07-27 的骨架深拷貝來的,而那份骨架比華南/第一上線還早。
    #    結果是「有資料、但前端的銀行清單裡沒有這家」—— 網站什麼都不會顯示,
    #    也不會報錯,看起來就跟「這家沒抄」一模一樣。
    # 判準是**有沒有算出格子**,不是 banks.json 的完整名冊 —— 名冊裡列了但一格
    # 都沒抄的銀行(今天的第一銀行)不該在網站上長出一整排空欄位。
    # 排序照 banks.json 的代號,跟 `core/webdata.py` 的既有做法一致。
    # (`periods` 刻意不一起動 —— 它現在是半年度的固定座標軸,而格子裡另有
    #  2023Q1…2025Q4 這些季別;把季別併進去會整個換掉前端的 x 軸,是另一件事。)
    seen_banks = set()
    for table_name in (t for ts in report.TABLES.values() for t in ts):
        for cell, cols in (data.get(table_name) or {}).items():
            if "|" in cell and any(v is not None for v in (cols or {}).values()):
                seen_banks.add(cell.split("|")[1])
    roster = config.CODE_OF               # 銀行名 → 代號(來源:banks.json)
    unknown = seen_banks - set(roster)
    if unknown:                       # 抄出了名冊上沒有的銀行 → 是抄列或 docid 出錯
        raise SystemExit(f"build: 有資料但不在 banks.json 名冊裡的銀行:{sorted(unknown)}")
    data["banks"] = sorted(seen_banks, key=lambda n: roster[n])

    # 主儀表板讀的 `data`(四桶)**由 `wide` 推導**,不再是獨立來源。
    # 這欄原本只有 bridge_v2 寫過,build.py 從來沒動過它 —— 實測 2020H2|兆豐
    # Trading 的 `data.其他` 是 1.95 而 `wide.其他` 是 0,兩張圖各說各話而
    # 沒有任何檢查抓得到。推導之後定義上不可能再分岔。
    # ⚠️ 四桶**刻意不含**資產基礎/股票/貨幣市場 —— 這是沿用現行網站的口徑,
    #    不是新判斷。要不要把資產基礎算進「債券市值」是內容決策,另案處理。
    # ⚠️ **齊全才進來,缺一角就整格不出現。** `make_web.py` 的 `mv()` 把四桶直接
    #    相加、`tot()` 要三類都在,少一個不是畫得醜而是 TypeError;更要緊的是
    #    半齊的格子會畫出一根**偏低但看起來正常**的長條 —— 那正是這次要消滅的
    #    「錯的看起來像對的」。整格不出現時 `make_web.rb()` 回 None,長條直接跳過。
    FOUR = {"公債": "GB", "公司債": "公司債", "金融債": "金融債", "其他": "其他"}
    four_bucket = {}
    for cell, w in (data.get("wide") or {}).items():
        cols = {cls: {k: w.get(f"{cls}_{src}") for k, src in FOUR.items()}
                for cls in CLASSES}
        if all(v is not None for c in cols.values() for v in c.values()):
            four_bucket[cell] = cols
    data["data"] = four_bucket

    # data.json 內只放**確定性**的 _build(不含 timestamp),保證同輸入 byte-identical
    data["_build"] = {
        "built_by": "build.py",
        "publish_unit": "(期別, 銀行, 類別, 口徑)",
        "facts_sha256": facts_sha,
        "decisions_sha256": _sha("buckets.py", "config.py"),
        "manifest": MANIFEST,
        "note": "唯一寫入者是 build.py。四張發布表全部由 facts/ 當次重建;"
                "不合格的格子寫 null(前端畫灰底斜紋),不回退舊管線的數字。",
    }

    manifest = {
        "build_timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "code_revision": _git_rev(),
        "inputs": {
            "facts": {"sha256": facts_sha, "cells": n_cells},
            "decisions": {"sha256": _sha("buckets.py", "config.py"),
                          "files": ["buckets.py", "config.py"]},
            "skeleton_only": {"path": snap_man["path"], "sha256": snap_man["sha256"],
                              "note": "只供 periods/banks/review 這些非金額欄位,"
                                      "不再供應任何數字"},
        },
        "counts": {
            "v3": sum(1 for u in units if u["provenance"] == "v3"),
            NONE_SRC: sum(1 for u in units if u["provenance"] == NONE_SRC),
            "changed_units": len(diff),
            "blanked": len(blanked),
        },
        "blanked": blanked,
        "units": units,
    }
    return data, manifest, diff


# ── 輸出 ────────────────────────────────────────────────────────────────────

def dump(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)


def summarize(manifest, diff):
    c = manifest["counts"]
    total = c["v3"] + c[NONE_SRC]
    print(f"發布單位 {total}:v3 {c['v3']} / 缺 {c[NONE_SRC]}   "
          f"有變動 {c['changed_units']} 個單位")
    print(f"輸入:facts {manifest['inputs']['facts']['cells']} 格")
    if diff:
        print(f"\n{len(diff)} 個單位的數字有變動(億元):")
        for unit, cols in sorted(diff.items()):
            print(f"\n  {unit}")
            for col, (old, new) in sorted(cols.items()):
                print(f"      {col:<16} {str(old):>9} → {str(new):>9}")
    if manifest["blanked"]:
        print(f"\n⚠ {len(manifest['blanked'])} 個單位由「有數字」變成 null "
              f"—— 舊管線有值,但新管線給不出合格的數字:")
        by_reason = collections.Counter(x["reason"] for x in manifest["blanked"])
        for reason, n in by_reason.most_common():
            print(f"    {n:>4}  {reason}")


def summarize_vs_live(data):
    """印「這次會把線上 `data.json` 改成什麼」。

    ⚠️ 2026-08-14 加。`summarize()` 印的 `diff` 比較基準是
    `snapshots/v2_frozen_20260727.json` —— 一份凍結的舊管線快照,**不是**磁碟上
    正在服役的 `data.json`。所以那份差異每次都印同一批 288 個單位,
    「這次改了什麼」反而看不見:實測過磁碟上的 data.json 與現算 0 差異時,
    `--diff` 照樣印 288 個單位。

    `更新網站.command` 的第 1 步就是拿那份差異問人「看起來對嗎?」,
    而它無法回答這個問題 —— 關卡等於空轉。這裡補上真正該看的那一份。
    """
    if not os.path.exists(DATA):
        print("\n(磁碟上沒有 data.json,這是第一次建置)")
        return
    live = json.load(open(DATA, encoding="utf-8"))

    def flat(d):
        out = {}
        for t, v in d.items():
            if not isinstance(v, dict):
                continue
            for cell, cols in v.items():
                if isinstance(cols, dict):
                    for c, val in cols.items():
                        out[(t, cell, c)] = val
        return out

    a, b = flat(live), flat(data)
    gained = [k for k in b if a.get(k) is None and b[k] is not None]
    lost = [k for k in a if a[k] is not None and b.get(k) is None]
    changed = [k for k in b if a.get(k) is not None and b[k] is not None and a[k] != b[k]]
    bank_d = (live.get("banks") or []) != (data.get("banks") or [])

    print("\n" + "=" * 60)
    print("與**線上 data.json**(這次會被覆蓋掉的那份)的差異")
    print("=" * 60)
    if not (gained or lost or changed or bank_d):
        print("  沒有任何欄位改變 —— 線上檔已經與 facts/ 同步。")
        return
    print(f"  null → 有值 : {len(gained):>4}")
    print(f"  有值 → null : {len(lost):>4}   ← 這一項不是 0 就要看清楚為什麼")
    print(f"  數字改變     : {len(changed):>4}   ← 這一項不是 0 就要看清楚為什麼")
    if bank_d:
        print(f"  銀行清單     : {live.get('banks')} → {data.get('banks')}")
    for label, ks in (("有值 → null", lost), ("數字改變", changed)):
        for k in sorted(ks)[:20]:
            print(f"    [{label}] {k[0]} {k[1]} {k[2]}: {a.get(k)} → {b.get(k)}")
        if len(ks) > 20:
            print(f"    … 另有 {len(ks) - 20} 筆")


def main(argv):
    stale = _assert_no_stale_verdict()
    data, manifest, diff = build()
    after = os.path.getmtime(stale[0]) if os.path.exists(stale[0]) else None
    assert after == stale[1], "build 期間動到了 results/verdict.json —— 鐵則 2 被違反"

    summarize(manifest, diff)
    summarize_vs_live(data)

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
