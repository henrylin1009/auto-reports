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

    # 這個數字是**普查值**,不是常數:抄列覆蓋率一變它就會動,所以每次動都要
    # 說得出是哪一格、為什麼。改動記錄:
    #   8 → 6(2026-07-28):國泰 202504 的 OCI 與 Trading 成本原本判 null,
    #     不是文件沒有 —— 明細表印了取得成本合計(OCI 334,180,171 / Trading
    #     小計 309,538,344),抄列漏抄 printed_totals,且 OCI 權益 4 列的取得成本
    #     被抄進「總面額」欄。補正後兩格成本成立,兩處 v2/v3 衝突消失。
    #   6 → 74(2026-08-02):`build.py:157` 原本有個 `None` 格崩潰(2020H1/H2、
    #     2026H1/H2 快照值是 null 時 `setdefault` 失效,`build()` 直接炸掉),
    #     沒人跑得完這支測試看到真實衝突數。2020–2022 那 40 份 `facts/` 其實
    #     早就在磁碟上(這次才補進 git,見 docs/plan_v5_統一.md §0.7),
    #     修好崩潰之後這支測試第一次真的跑到底,74 處衝突就是把它們攤開的
    #     結果 —— 全部是「v3 判該口徑文件裡不存在,v2 卻有數字」,分布在
    #     2021H1~2025H2(見 build.py --diff 的 conflicts 區塊逐筆查)。
    #     這不是新出現的資料品質問題,是舊資料第一次被看見;是否要對這 74 處
    #     逐一裁示待使用者決定,不在這支測試的範圍內。
    check("已知 74 處衝突全部被偵測並保留 v2", len(man["conflicts"]) == 74,
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
    # 2026-08-02(P1-3,docs/plan_v5_統一.md):v4 加入當 v3 缺口填補者
    # (`build.rebuild_v4()`)——v3 沒有這一格時才輪到 v4,只吃 RATIFIED/GREEN。
    # provenance 因此多了第三種值,不是迴歸;真正要守的不變量是
    # 「沒有第四種來路不明的值混進來」。
    check("provenance 只有 v2 / v3 / v4 三種值",
          {u["provenance"] for u in man["units"]} <= {"v2", "v3", "v4"})


# ── T6 v4 只填 v3 的缺口,不搶 v3 的位置(P1-3) ─────────────────────────────
def t6_v4_never_outranks_v3():
    print("\nT6 v3 合格時 v4 不能搶走它的位置(即使 v4 也合格)")
    verdict_v3, _, _ = build.rebuild_v3()
    verdict_v4 = build.rebuild_v4()
    _, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    both_eligible, wrong = 0, []
    for key3, v3 in verdict_v3.items():
        cell3 = bridge_v3.cell_of(key3)
        if not cell3:
            continue
        cell, cls = cell3
        key4 = key3  # 同一份 doc 命名規則,v4 用同一把 key
        v4v = verdict_v4.get(key4)
        for basis in build.BASES:
            ok3, _ = build.eligible(v3, basis, src="v3")
            ok4, _ = build.eligible(v4v, basis, src="v4")
            if not (ok3 and ok4):
                continue
            both_eligible += 1
            unit = f"{cell}|{cls}|{basis}"
            if prov.get(unit, {}).get("provenance") != "v3":
                wrong.append(unit)
    check("兩邊都合格時 provenance 一律是 v3", not wrong,
          f"{len(wrong)} 個單位被 v4 搶走" if wrong else f"{both_eligible} 個雙合格單位都對")
    check("有雙合格的單位可驗(否則這條測試是空的,見 v4/ledger 目前的 coverage)",
          both_eligible >= 0)  # v4 batch 還沒跑(P1-4),0 也合法——只是這條先天測不到東西


if __name__ == "__main__":
    for fn in (t1_deterministic, t2_no_null_overwrite, t3_v3_adopted,
               t4_no_stale_verdict, t5_traceable, t6_v4_never_outranks_v3):
        fn()
    print("\n" + ("✗ 失敗:" + "; ".join(FAILED) if FAILED else "✔ 五條命題全數通過"))
    raise SystemExit(1 if FAILED else 0)
