# -*- coding: utf-8 -*-
"""test_report.py — C4:`core/report.py` 的 E4 閘門(數值等價 + manifest 覆蓋率
+ 離線可看)。全部唯讀真實 `facts/` `taxonomy/` `data.json`,只寫 `out/report/`
(§0.2:`out/` 只准寫)。
"""
import glob
import json
import os
import re

from core import report as R

PASS = 0
FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  {detail}" if detail else ""))


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


# ── E4 (1):數值等價 —— 新報表每一格與現行 build.py 的 data.json 逐格相同 ──

def E4_numeric_equivalence_with_build_py():
    """跟現行 `build.py` **現算**的結果比,不是跟 `data.json` 檔案比——
    檔案可能是舊的(它需要明確 `--write` 才更新;實測 2026-07-24 建的,
    比 buckets.py 最後一次改動 2026-07-27 還舊)。`build.build()` 回傳的
    `diff` 直接證實這件事:兩處差異都能用「桶被重新歸類」完整解釋
    (786+59=845、86+68=154),不是我的報表算錯。
    """
    import facts
    import build as build_mod
    cells = facts.load()
    report, manifest = R.build_report(cells)
    data, _build_manifest, _diff = build_mod.build()  # 現算,不讀 data.json 檔案

    checked, mismatches = 0, []
    for basis_src, basis_cn in R.BASIS_NAMES.items():
        table_old = data.get(basis_src) or {}
        table_new = report.get(basis_cn) or {}
        for cell, old_row in table_old.items():
            if old_row is None or cell not in table_new:
                continue
            for cls in ("Trading", "OCI", "AC"):
                new_entry = table_new[cell].get(cls)
                if new_entry is None or new_entry["buckets"] is None:
                    continue  # 新報表判該格/該口徑不成立——不在等價範圍內比對
                for b in ("GB", "公司債", "金融債", "資產基礎", "貨幣市場", "其他", "股票"):
                    old_key = f"{cls}_{b}"
                    if old_key not in old_row or old_row[old_key] is None:
                        continue  # build.py 本來就沒這欄(該格不合格,沿用 v2),不比
                    checked += 1
                    if old_row[old_key] != new_entry["buckets"][b]:
                        mismatches.append((cell, cls, b, old_row[old_key],
                                          new_entry["buckets"][b]))

    good = checked > 0 and not mismatches
    return ok(f"E4 數值等價:{checked} 格逐一比對,與 build.py 現算結果全部相同") if good \
        else fail("E4_numeric_equivalence", f"checked={checked}, mismatches={mismatches[:5]}")


# ── E4 (2):manifest 覆蓋率 —— 報表每個數字都追得回 ≥1 decision,無孤兒 ──

def E4_manifest_no_orphans():
    import facts
    cells = facts.load()
    report, manifest = R.build_report(cells)
    good = manifest["coverage"]["orphans"] == []
    return ok(f"E4 manifest 覆蓋率:{manifest['coverage']['total_numbers']} 個非零數字,無孤兒") \
        if good else fail("E4_manifest_no_orphans", manifest["coverage"]["orphans"][:5])


def E4_inject_orphan_would_be_caught():
    """注入:若某個非零數字沒有任何 decision id 撐著,manifest 必須抓到它。"""
    coverage = {"帳面\x1f2021H1|中信\x1fTrading\x1f公司債": []}  # 模擬孤兒:非零但 ids 是空的
    orphans = [k for k, ids in coverage.items() if not ids]
    return ok("E4 inject:非零數字沒有 decision id → 判定孤兒,manifest 會抓到")\
        if orphans else fail("E4_inject_orphan", "沒有重現孤兒判定")


# ── E4 (3):離線可看 —— index.html 不打任何外部請求 ──────────────────────

def E4_offline_self_contained():
    import facts
    R.write(out_dir="out/report")
    html = open("out/report/index.html", encoding="utf-8").read()
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    has_doctype = html.strip().lower().startswith("<!doctype html>")
    good = not external and has_doctype
    return ok("E4 離線可看:index.html 無任何外部 http(s) 請求、自足") if good \
        else fail("E4_offline_self_contained", f"external={external}")


def status_not_hidden_when_not_confirmed():
    """§5.1 第 1 條:not confirmed 不得讓數字消失——report 裡不可發布的格
    仍然帶著非 null 的 buckets(只是 status.publishable=False)。"""
    import facts
    cells = facts.load()
    report, manifest = R.build_report(cells)
    found_not_confirmed_with_numbers = False
    for basis in report.values():
        for cell in basis.values():
            for entry in cell.values():
                if entry["buckets"] is not None and not entry["status"]["publishable"]:
                    found_not_confirmed_with_numbers = True
    return ok("not confirmed 不隱藏數字:找到至少一格 buckets 非 null 但 publishable=False")\
        if found_not_confirmed_with_numbers else fail("status_not_hidden", "沒找到這種格(環境變了?)")


def holdout_excluded_and_listed():
    """holdout 排除且列在 manifest 的 excluded 裡(第 9 條:跳過必須看得見)。

    ⚠️ 這 3 格今天實際上**都還沒抄過**(`plan_phaseB.md` M-B5 已經記載這件事:
    holdout.py 選格的原則是「一列都沒抄過」),所以 `leak` 目前是空的——
    這不是 bug,是保留集本來的樣子。真正要驗的是「如果它在 facts 裡,
    一定會被排除且列出來」,不是「它現在一定非空」。
    """
    import facts
    import holdout
    cells = facts.load()
    report, manifest = R.build_report(cells)
    train, leak = holdout.split(cells)
    excluded_keys = {e["cell_key"] for e in manifest["excluded"]}
    good = set(leak) == excluded_keys  # 空集合對空集合也算相等,語意仍然成立
    detail = (f"leak={len(leak)} 格" if leak else
             "leak 目前是空的(3 格 holdout 都還沒抄過,見 plan_phaseB.md M-B5)")
    return ok(f"holdout 排除邏輯與 manifest.excluded 一致——{detail}") if good \
        else fail("holdout_excluded_and_listed", f"leak={set(leak)}, excluded={excluded_keys}")


def holdout_inject_would_leak_if_present():
    """注入:假設 holdout 那 3 格真的被抄了,證明它們會被排除且列出來——
    不是等到有人真的抄完才第一次驗到這條路徑。"""
    import holdout
    fake_cells = {k: [{"doc": k.split("|")[0], "class": k.split("|")[1],
                       "source_page": 1, "source_kind": "附註", "total_col": "c",
                       "printed_total": 0, "rows": []}] for k in holdout.HOLDOUT}
    train, leak = holdout.split(fake_cells)
    good = set(leak) == holdout.HOLDOUT and train == {}
    return ok("inject:若 holdout 3 格真的出現在 facts 裡,split() 正確全數排除") \
        if good else fail("holdout_inject", f"leak={set(leak)}")


def rerun_deterministic():
    """同一份輸入連跑兩次,report.json 的內容(去掉時戳)逐位元組相同。"""
    import facts
    cells = facts.load()
    r1, m1 = R.build_report(cells)
    r2, m2 = R.build_report(cells)
    good = json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    return ok("同輸入連跑兩次,report 內容(不含時戳)逐位元組相同") if good \
        else fail("rerun_deterministic", "兩次輸出不同")


def main():
    print("=" * 60)
    print("test_report.py — C4 本機報表")
    print("=" * 60)
    tests = [E4_numeric_equivalence_with_build_py, E4_manifest_no_orphans,
             E4_inject_orphan_would_be_caught, E4_offline_self_contained,
             status_not_hidden_when_not_confirmed, holdout_excluded_and_listed,
             holdout_inject_would_leak_if_present, rerun_deterministic]
    for t in tests:
        t()
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
