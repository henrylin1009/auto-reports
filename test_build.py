# -*- coding: utf-8 -*-
"""Phase 1 驗收:`build.py` 的五條命題(docs/plan_phase1_build.md §5)。

每一條都要**證明得了**,不是印個 OK 就算。特別是 T4 —— 用毒餌檔證明
`results/verdict.json` 真的沒被讀,而不是靠讀程式碼相信它。
"""
import json
import os
import shutil

import build
import bridge_v3
from config import WIDE_BUCKETS

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'✔' if cond else '✘'} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def payload(data):
    """比對用:去掉不參與確定性的欄位(目前沒有,但保留這個鉤子)。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)


# ── T1 確定性 ───────────────────────────────────────────────────────────────
def t1_deterministic():
    print("\nT1 同一輸入重跑結果完全一致")
    a, ma, _ = build.build()
    b, mb, _ = build.build()
    check("data payload 逐 byte 相同", payload(a) == payload(b))
    check("輸入指紋相同", ma["inputs"] == mb["inputs"])
    check("_build 區塊不含 timestamp(否則無法 byte-identical)",
          "build_timestamp" not in a["_build"] and "at" not in a["_build"])
    check("manifest 有 timestamp(確定性資料與稽核資訊分開放)",
          "build_timestamp" in ma)


# ── T2 v3 不完整時,v2 值不消失 ────────────────────────────────────────────
def t2_no_null_overwrite():
    print("\nT2 v3 不完整時,既有 v2 值不會消失或變 null")
    snap, _ = build.load_snapshot()
    data, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    lost = []
    for basis in build.BASES:
        for cell, cols in (snap.get(basis) or {}).items():
            for col, old in (cols or {}).items():
                if old is None:
                    continue
                new = ((data.get(basis) or {}).get(cell) or {}).get(col)
                if new is None:
                    lost.append(f"{basis} {cell} {col}: {old} → None")
    check("沒有任何 v2 的非 null 值被抹成 null", not lost,
          f"{len(lost)} 筆被抹掉" if lost else "0 筆")

    check("已知 8 處衝突全部被偵測並保留 v2", len(man["conflicts"]) == 8,
          f"實測 {len(man['conflicts'])} 處")
    for c in man["conflicts"]:
        u = prov.get(c["unit"])
        if not (u and u["provenance"] == "v2"):
            check(f"衝突單位 {c['unit']} 的 provenance 應為 v2", False)
            return
    check("每個衝突單位的 provenance 都是 v2", True)


# ── T3 v3 合格時正確覆蓋 ──────────────────────────────────────────────────
def t3_v3_adopted():
    print("\nT3 v3 完整且合格時,能正確覆蓋對應發布單位")
    verdict, _, _ = build.rebuild_v3()
    data, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    n_checked, mismatched = 0, []
    for key, v in verdict.items():
        got = bridge_v3.cell_of(key)
        if not got:
            continue
        cell, cls = got
        for basis in build.BASES:
            ok, _ = build.eligible(v, basis)
            unit = f"{cell}|{cls}|{basis}"
            if unit not in prov:
                continue
            if ok:
                if prov[unit]["provenance"] != "v3":
                    mismatched.append(f"{unit} 合格卻標成 {prov[unit]['provenance']}")
                    continue
                for b in WIDE_BUCKETS:
                    want = bridge_v3.to_yi(v[basis][b])
                    got_v = ((data.get(basis) or {}).get(cell) or {}).get(f"{cls}_{b}")
                    if want != got_v:
                        mismatched.append(f"{unit} {b}: 期望 {want} 得到 {got_v}")
                n_checked += 1
            elif prov[unit]["provenance"] == "v3":
                mismatched.append(f"{unit} 不合格卻標成 v3")
    check(f"所有合格單位的數字 == 當次重建的 v3 值", not mismatched,
          f"檢查 {n_checked} 個合格單位;{len(mismatched)} 個不符")
    for m in mismatched[:5]:
        print("      ", m)
    check("有合格單位可驗(否則這條測試是空的)", n_checked > 0, f"{n_checked} 個")


# ── T4 不讀過期 verdict ───────────────────────────────────────────────────
def t4_no_stale_verdict():
    print("\nT4 build 不會讀取過期的 results/verdict.json")
    p = f"{build.results.OUT}/verdict.json"
    baseline, _, _ = build.build()

    if not os.path.exists(p):
        check("results/verdict.json 不存在,改以斷言路徑驗證", True)
        return
    bak = p + ".t4bak"
    shutil.copy(p, bak)
    try:
        # 毒餌:內容明顯錯誤。若 build 讀了它,輸出一定會變(或直接爆掉)。
        json.dump({"POISON|Trading": {"doc": "POISON", "class": "Trading", "pass": True,
                                      "wide": {b: 999999999 for b in WIDE_BUCKETS},
                                      "wide_cost": None, "side": {}, "others": [],
                                      "anchor": 1}},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False)
        poisoned, _, _ = build.build()
        check("毒餌注入後輸出完全不變", payload(baseline) == payload(poisoned))
        check("毒餌數字 999999999 沒有出現在輸出裡",
              "999999999" not in payload(poisoned))
    finally:
        shutil.move(bak, p)
    check("測試後已還原 results/verdict.json", os.path.exists(p))


# ── T5 可追溯 ─────────────────────────────────────────────────────────────
def t5_traceable():
    print("\nT5 任一輸出格都能追溯到 v2 snapshot 或 v3 facts / 分類規則")
    data, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}
    missing = []
    for basis in build.BASES:
        for cell, cols in (data.get(basis) or {}).items():
            for col, val in (cols or {}).items():
                if val is None:
                    continue
                cls = col.split("_")[0]
                unit = f"{cell}|{cls}|{basis}"
                if unit not in prov or not prov[unit].get("reason"):
                    missing.append(unit)
    check("每個非空發布單位都有 provenance + reason", not missing,
          f"{len(set(missing))} 個單位缺" if missing else f"{len(prov)} 個單位齊全")
    check("manifest 記錄了四種 revision",
          all(k in man["inputs"] for k in ("frozen_snapshot", "facts", "decisions"))
          and "code_revision" in man)
    check("data.json 的 _build 帶得到快照與 facts 指紋",
          data["_build"]["frozen_snapshot"]["sha256"] and data["_build"]["facts_sha256"])
    check("provenance 只有 v2 / v3 兩種值",
          {u["provenance"] for u in man["units"]} <= {"v2", "v3"})


if __name__ == "__main__":
    for fn in (t1_deterministic, t2_no_null_overwrite, t3_v3_adopted,
               t4_no_stale_verdict, t5_traceable):
        fn()
    print("\n" + ("✗ 失敗:" + "; ".join(FAILED) if FAILED else "✔ 五條命題全數通過"))
    raise SystemExit(1 if FAILED else 0)
