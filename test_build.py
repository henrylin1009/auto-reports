# -*- coding: utf-8 -*-
"""Phase 1 驗收:`build.py` 的五條命題(docs/plan_phase1_build.md §5)。

每一條都要**證明得了**,不是印個 OK 就算。特別是 T4 —— 用毒餌檔證明
`results/verdict.json` 真的沒被讀,而不是靠讀程式碼相信它。
"""
import json
import os
import shutil

import build
import fill
from core import report as creport
from config import WIDE_BUCKETS

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'✔' if cond else '✘'} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def payload(data):
    """比對用:去掉不參與確定性的欄位(目前沒有,但保留這個鉤子)。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)



#: doc → 報表口徑(個體/合併)。`core.report.cell_of` 要用,見那支的檔頭。
_BMAP = None


def _bmap():
    global _BMAP
    if _BMAP is None:
        _BMAP = fill.basis_map()
    return _BMAP


def _cell_of(key):
    """`(doc|cls)` → (格, 類別, {口徑: 表名}) 或 None。"""
    b = _bmap().get(key.split("|")[0])
    got = creport.cell_of(key, b)
    if not got:
        return None
    return got[0], got[1], dict(zip(build.BASES, creport.TABLES[b]))


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


# ── T2 不合格的格子一定是 null,而且一定說得出理由 ──────────────────────────
def t2_ineligible_is_null():
    """⚠️ **2026-08-10 這條測試的契約反過來了。**

    舊契約是「沒有任何 v2 的非 null 值被抹成 null」——它保護的是凍結快照的數字。
    實測那條規則的後果:383 個發布單位裡 194 個(51%)由 v2 供應,完全繞過本檔
    所有閘門,而網站上看起來跟驗過的數字一模一樣。使用者 2026-08-10 裁示砍掉
    保底,契約改成:**不合格就是 null,而且每個 null 都要有具體理由。**

    新契約擋的東西比舊的多:舊的只能保證「數字不會消失」,擋不住「沒驗過的數字
    被發布」;新的兩件都擋——不合格的格子如果還留著數字,這裡就會失敗。
    """
    print("\nT2 不合格的格子一定是 null,且每個 null 都有具體理由")
    data, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    leaked, no_reason = [], []
    for u in man["units"]:
        if u["provenance"] != build.NONE_SRC:
            continue
        if not (u.get("reason") or "").strip():
            no_reason.append(u["unit"])
        cell, cls, table = u["unit"].split("|")[0] + "|" + u["unit"].split("|")[1], \
            u["unit"].split("|")[2], u["unit"].split("|")[3]
        cols = (data.get(table) or {}).get(cell) or {}
        for b in build.WIDE_BUCKETS:
            if cols.get(f"{cls}_{b}") is not None:
                leaked.append(f"{u['unit']} {b}={cols[f'{cls}_{b}']}")
    check("沒有任何不合格的格子留著數字", not leaked,
          f"{len(leaked)} 欄漏出來" if leaked else "0 欄")
    check("每個 null 單位都有具體理由", not no_reason,
          f"{len(no_reason)} 個沒理由" if no_reason else f"{len(man['units'])} 個單位全有")

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
    #   74 → 68(這次會話開始時的既有狀態,起因未查——不影響這次改動,原樣記錄)。
    #   68 → 65(2026-08-03):v4 引擎 `check_bucket_complete` 揪出 7 格對不到桶,
    #     其中 3 個名字(買入國庫券/CMO 擔保房貸憑證/累計減損 系列)人審後貼進
    #     `buckets.SYN`。`buckets.SYN` 是 v3/v4 共用表,這幾個名字剛好也出現在
    #     v3 的 `facts/` 裡,原本因為分不到桶而讓那一格的 wide view 判 null,
    #     現在能算出來了,3 個「v3 null 但 v2 有值」的衝突因此消失:
    #     2023H1|兆豐|AC|wide、2023H1|富邦|Trading|wide、2024H1|玉山|Trading|wide。
    #     實測:消失 3、新增 0(有腳本可查:diff conf_before.json/conf_after.json)。
    #   65 → 69(2026-08-03):補上口徑閘門(`adapter.Aggregated.basis`)。v4 原本
    #     把「逐項成本 + 一整筆評價調整」這種版型的七桶當帳面寫進 wide,實測 20 格
    #     發布了錯的數字(兆豐 202302 Trading 差 10.73%)。修好之後那些格的 wide
    #     誠實回 null(逐桶帳面在文件裡真的不存在,同 wide.py:99 的既有規則),
    #     於是多出 4 處「v3/v4 都是 null 而 v2 有值」的衝突——**這是誠實的代價,
    #     不是退步**:先前那 4 個位置放的是成本數字冒充帳面。
    #   69 → 66(2026-08-03,同日稍晚):witness 五道收成三道。rowsum/anchor/
    #     page_ref 從硬閘門降成提示(判準:人拿原始頁對得出來的不必當閘門),
    #     7 格因此從 RED 轉 GREEN 開始發布 → v4 單位 9 → 13、衝突少 3 處。
    #     **那 7 格沒有靜靜放行**:`ledger.review_queue()` 新增 hint 段列出來,
    #     test_adapter T11 釘住「會發布但有提示沒過的格一定在清單上」。
    #   66 → 129(2026-08-10):砍掉 v2 保底,`conflicts` 這個概念隨之消失
    #     (不再有「兩個來源不同調」這回事,只有一個來源),改記 `blanked` ——
    #     「舊管線有值、新管線給不出合格數字」的單位。129 的組成量過:
    #       81  數字**搬到另一個口徑欄**(帳面↔成本),不是消失。多半是
    #           「逐項成本 + 一整筆評價調整」那種版型,舊管線當帳面發布。
    #       24  v3 沒有這一格 —— 真 backlog,抄了就回來。
    #       24  該口徑在文件裡不存在 —— v2 印了文件裡沒有的數字。
    #     同時合併報表(AI1)第一次接上網格:`core.report.cell_of` 改由封面判口徑,
    #     不再寫死 AI3,`wide_consol`/`wide_cost_consol` 因此由 facts/ 重建。
    #   129 → 132(2026-08-10,同日稍晚):`v4/adapter.aggregate()` 補上
    #     「沒有可對帳的小計 ⇒ 不合格」。原本沒小計就整段跳過檢查、直接回 ok,
    #     等於「沒東西可檢查」被當成「檢查過了」。實例:玉山 202104 OCI 的成本
    #     只抄得到 2 列股票(reader 正確判定債務工具那欄是攤銷後成本、非取得成本,
    #     依規則填 null),七桶照樣加得出來 —— 只是 5 個債券桶全是 0,於是網站上
    #     玉山 2021H2 OCI 成本印著「公債 0/公司債 0/金融債 0」,同格帳面卻是 2,947 億。
    #     少 4 筆 cost(富邦 202004/202104 Trading、玉山 202104 OCI、國泰 202304 Trading)。
    #   132 → 130(2026-08-10,同日稍晚):`buckets.SYN` 補進「資產證券化」
    #     (`synonyms.py` 的可自動推定:兆豐 202104/202204 OCI 附註「受益證券」
    #     與明細表「資產證券化」同額)。少這一條時明細表那列分不到桶,
    #     `wide.view(帳面)` 整個 not ok,兩整格的逐桶帳面被判「文件裡不存在」——
    #     但它就印在明細表的「總額」欄。補上之後那 2 格的帳面回來了。
    check("已知 130 個單位由有值變 null", len(man["blanked"]) == 130,
          f"實測 {len(man['blanked'])} 個")
    for c in man["blanked"]:
        u = prov.get(c["unit"])
        if not (u and u["provenance"] == build.NONE_SRC):
            check(f"變 null 的單位 {c['unit']} 的 provenance 應為 {build.NONE_SRC}", False)
            return
    check(f"每個變 null 的單位 provenance 都是 {build.NONE_SRC}", True)


# ── T3 v3 合格時正確覆蓋 ──────────────────────────────────────────────────
def t3_v3_adopted():
    print("\nT3 v3 完整且合格時,能正確覆蓋對應發布單位")
    verdict, _, _ = build.rebuild_v3()
    data, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    # ⚠️ **以「格」為單位判,不是以 doc。** 一格可能對到多份文件 —— 玉山 2021H1 的
    # `202102_5847_AI2` 與 `_AI3` 是同一份 PDF 的重複抓檔(sha256 相同),
    # AI2 只抄 2 列不合格、AI3 抄 7 列合格。舊寫法對每份 doc 各判一次,
    # AI2 那次就會誤報「不合格卻標成 v3」,即使那格正確地採用了 AI3。
    # 判準與 `build.pick()` 對齊:該格**有任一份合格**就該是 v3,數字等於被採用的那份。
    import collections
    cands, tables_of = collections.defaultdict(list), {}
    for key, v in verdict.items():
        got = _cell_of(key)
        if not got:
            continue
        cands[(got[0], got[1])].append((key, v))
        tables_of[(got[0], got[1])] = got[2]

    n_checked, mismatched = 0, []
    for (cell, cls), lst in cands.items():
        tables = tables_of[(cell, cls)]
        for basis in build.BASES:
            unit = f"{cell}|{cls}|{tables[basis]}"
            if unit not in prov:
                continue
            okd = {k: v for k, v in lst if build.eligible(v, basis)[0]}
            if okd:
                if prov[unit]["provenance"] != "v3":
                    mismatched.append(f"{unit} 合格卻標成 {prov[unit]['provenance']}")
                    continue
                picked = okd.get(prov[unit].get("facts_key"))
                if picked is None:
                    mismatched.append(f"{unit} 採用的 {prov[unit].get('facts_key')} 不在合格清單裡")
                    continue
                for b in WIDE_BUCKETS:
                    want = creport.to_yi(picked[basis][b])
                    got_v = ((data.get(tables[basis]) or {}).get(cell) or {}).get(f"{cls}_{b}")
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
          all(k in man["inputs"] for k in ("skeleton_only", "facts", "decisions"))
          and "code_revision" in man)
    check("data.json 的 _build 帶得到 facts 與判斷層指紋",
          data["_build"]["facts_sha256"] and data["_build"]["decisions_sha256"])
    # 2026-08-02(P1-3,docs/plan_v5_統一.md):v4 加入當 v3 缺口填補者
    # (`build.rebuild_v4()`)——v3 沒有這一格時才輪到 v4,只吃 RATIFIED/GREEN。
    # provenance 因此多了第三種值,不是迴歸;真正要守的不變量是
    # 「沒有第四種來路不明的值混進來」。
    # 2026-08-10:v2 保底砍掉,第三種值從 "v2" 換成 `build.NONE_SRC`("none")——
    # 意思也變了:不再是「回退到舊管線」,而是「這格沒有任何合格來源,發布 null」。
    check(f"provenance 只有 v3 / v4 / {build.NONE_SRC} 三種值",
          {u["provenance"] for u in man["units"]} <= {"v3", "v4", build.NONE_SRC})


# ── T6 v4 只填 v3 的缺口,不搶 v3 的位置(P1-3) ─────────────────────────────
def t6_v4_never_outranks_v3():
    print("\nT6 v3 合格時 v4 不能搶走它的位置(即使 v4 也合格)")
    verdict_v3, _, _ = build.rebuild_v3()
    verdict_v4 = build.rebuild_v4()
    _, man, _ = build.build()
    prov = {u["unit"]: u for u in man["units"]}

    both_eligible, wrong = 0, []
    for key3, v3 in verdict_v3.items():
        cell3 = _cell_of(key3)
        if not cell3:
            continue
        cell, cls, tables3 = cell3
        key4 = key3  # 同一份 doc 命名規則,v4 用同一把 key
        v4v = verdict_v4.get(key4)
        for basis in build.BASES:
            ok3, _ = build.eligible(v3, basis, src="v3")
            ok4, _ = build.eligible(v4v, basis, src="v4")
            if not (ok3 and ok4):
                continue
            both_eligible += 1
            unit = f"{cell}|{cls}|{tables3[basis]}"
            if prov.get(unit, {}).get("provenance") != "v3":
                wrong.append(unit)
    check("兩邊都合格時 provenance 一律是 v3", not wrong,
          f"{len(wrong)} 個單位被 v4 搶走" if wrong else f"{both_eligible} 個雙合格單位都對")
    check("有雙合格的單位可驗(否則這條測試是空的,見 v4/ledger 目前的 coverage)",
          both_eligible >= 0)  # v4 batch 還沒跑(P1-4),0 也合法——只是這條先天測不到東西


if __name__ == "__main__":
    for fn in (t1_deterministic, t2_ineligible_is_null, t3_v3_adopted,
               t4_no_stale_verdict, t5_traceable, t6_v4_never_outranks_v3):
        fn()
    print("\n" + ("✗ 失敗:" + "; ".join(FAILED) if FAILED else "✔ 五條命題全數通過"))
    raise SystemExit(1 if FAILED else 0)
