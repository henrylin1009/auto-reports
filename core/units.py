# -*- coding: utf-8 -*-
"""發布單位的判定。atomic unit = (期別, 銀行, 類別) —— 見 plan_clean_core.md §1 R1。

**採用是 all-or-nothing**:一次切換該格的每一個投影(data / wide / wide_cost)。
四元組(帶口徑)是錯的切法 —— data 區塊也是同一格的投影,四元組管不到它,
實測會在同一頁上顯示 419.67 億與 788 億兩個數字。

⚠️ **`adopt()` 判 provenance=="v3" 只是 technical candidate,不是正式發布資格
(2026-07-28 使用者裁示)。** 鐵則 5(見 docs/plan_clean_core.md §3.4)是
`buckets.SYN` 要先完成批准遷移、每條建立 reference,命中才有資格當
CONFIRMED 的來源;在 B1 完成前,今天的 SYN 命中一律只是 PROVISIONAL。
`adopt()` today 完全不知道 SYN 遷移進度 —— 它只核對六道檢查/七桶/holdout,
**沒有查 Decision/CONFIRMED 狀態**,所以它現在的判定只能當「v3 這條資料路徑
本身結構合格」的技術判斷,C4 把它接進真正的發布流程前,**不得把這裡的
provenance=="v3" 直接當成可以上網站的發布資格**,也不得把現有 SYN 命中
視為已經是 CONFIRMED。這條要等 B1(SYN 遷移 + reference)完成、且 C4 把
CONFIRMED 檢查接進 `adopt()`(或它的呼叫端)之後才能解除。

⚠️ Phase A 範圍限制(不是自行放寬):v3 verdict 今天**沒有** `data` 這個投影
(`results.build()` 只產出 `wide`/`wide_cost`;把 `data` 變成同源投影是 R1 的
「推論」,列在 C4)。所以 all-or-nothing 的**可核對範圍**這裡只涵蓋 v3 實際
可能供應的 wide/wide_cost 兩項;`data` 是否已填仍然算進
`projections_present()`(給 C4 用),但 `adopt()` 不會因為 v3 供不出 `data`
就判它 CONTRADICTION —— 那是把「v3 尚未接手 data」錯報成「v3 反悔」。
"""
from config import WIDE_BUCKETS

PROJECTIONS = ("data", "wide", "wide_cost")

#: v3 verdict 今天實際能供應、因此可以核對 all-or-nothing 的投影。
_V3_CHECKABLE = ("wide", "wide_cost")

# 回退的三種狀態。**不准合併成一種** —— 見 R2。
NOT_YET = "NOT_YET"  # v3 對這格沒有意見(facts 未抄錄)
BLOCKED = "BLOCKED"  # v3 抄了但六道檢查沒過
CONTRADICTION = "CONTRADICTION"  # v3 判該口徑文件裡不存在,而 v2 有數字 → 需人工裁示
ADOPTED = "ADOPTED"


def projections_present(snapshot, cell, cls):
    """快照對 (cell, cls) 已經填了哪些投影。回傳 PROJECTIONS 的子集。"""
    present = set()
    data_cell = (snapshot.get("data") or {}).get(cell) or {}
    if data_cell.get(cls):
        present.add("data")
    for proj in _V3_CHECKABLE:
        book = (snapshot.get(proj) or {}).get(cell) or {}
        if book and any(book.get(f"{cls}_{b}") is not None for b in WIDE_BUCKETS):
            present.add(proj)
    return present


def _unit_key(cell, cls):
    return f"{cell}|{cls}"


def adopt(verdict, snapshot, cell, cls, holdout_keys, ledger):
    """回傳 {"provenance": "v3"|"v2", "state": ..., "reason": str, "projections": [...]}。

    採用 v3 的條件(全部成立):
      ① verdict 存在且 pass
      ② 快照對該格已填的**每一個**(v3 可核對的)投影,v3 都供應得出來
      ③ 七桶齊全
      ④ key 不在 holdout
    否則整格留 v2,一個投影都不動,並依上面三種狀態分類回退原因。

    ratchet(R2):ledger 記為 v3 的 unit 若這次不合格 → 回傳 state=CONTRADICTION
    且 reason 標明「已發布過 v3 卻不再合格」。呼叫端要讓 build 失敗,不是靜靜回退。
    """
    unit = _unit_key(cell, cls)
    ledger = ledger or {}
    holdout_keys = holdout_keys or ()
    was_v3 = ledger.get(unit) == "v3"

    def fallback(state, reason):
        if was_v3 and state != CONTRADICTION:
            return {"provenance": "v2", "state": CONTRADICTION,
                    "reason": f"已發布過 v3 卻不再合格:{reason}", "projections": []}
        return {"provenance": "v2", "state": state, "reason": reason, "projections": []}

    if verdict is None:
        return fallback(NOT_YET, "v3 沒有這一格(facts 尚未抄錄)")

    fk = f"{verdict.get('doc')}|{verdict.get('class')}"
    if fk in holdout_keys:
        return fallback(BLOCKED, f"key 在 holdout({fk}),永不採用")

    if not verdict.get("pass"):
        return fallback(BLOCKED, "v3 該格六道檢查未通過")

    for basis in _V3_CHECKABLE:
        book = verdict.get(basis)
        if book is not None:
            missing = [b for b in WIDE_BUCKETS if b not in book]
            if missing:
                return fallback(BLOCKED, f"v3 七桶不齊,缺 {missing}({basis})")

    present = projections_present(snapshot, cell, cls)
    unsupplied = sorted(p for p in present if p in _V3_CHECKABLE and verdict.get(p) is None)
    if unsupplied:
        return fallback(
            CONTRADICTION,
            f"快照已有 {unsupplied} 但 v3 判該口徑在文件裡不存在(null)")

    return {"provenance": "v3", "state": ADOPTED, "reason": "v3 合格",
            "projections": sorted(p for p in _V3_CHECKABLE if verdict.get(p) is not None)}
