# -*- coding: utf-8 -*-
"""R3 對真實資料的基準與棘輪(ratchet)。**只准變好,不准變壞。**

有些命題今天本來就該是紅的(要到 C4 才會綠),所以本檔印基準表、只在數字
**惡化**時 exit 1。三條真實資料的計算方式照抄 docs/plan_clean_core.md 附錄,
不自己發明。

`adopted_units_triple_rule` 的基準是 **25,不是 24**(2026-07-28 使用者裁示,
採 R.2 U2 的字面規則)。差一個的是 `2021H1|玉山|OCI`:今天 `data.json` 的
`wide_cost` 對這格從未填過(全 None),依 U2(「快照沒填 wide_cost 而 v3 只有
wide → 可以採用」)它可採用 v3,只把 `wide` 這個投影切過去,`wide_cost`
維持缺失 —— **不得因此去補一個值,也不得混用 v2/v3**。這條規則已由
`test_units.py` 的 U9 補上真實格號的回歸測試。`plan_clean_core.md` M2
手動盤點的 24 是用另一條(「wide_cost 必須無條件由 v3 供應」)算的,
兩份文件的數字口徑不同,以本次使用者裁示的 25 為準。
"""
import json

import fill
from core import report as creport
import facts
import holdout
from config import WIDE_BUCKETS
from core import reconcile, units

BASELINE = {
    "mixed_provenance_cells": 0,
    # 2026-08-14 重新定義:只數「兩邊都有值卻不同」。舊基準 21 是舊定義
    # (含一邊缺值)算出來的,不可比;新定義下今天實測 0。
    "data_wide_inconsistencies": 0,
    # 「四桶未齊全所以整格不進 data」的計數點。**刻意設 direction=None**:
    # 它會隨發布覆蓋率上升而上升,上升是好事不是惡化,所以印出來但不當閘門。
    "four_bucket_incomplete_points": 105,
    "adopted_units_triple_rule": 25,
    "conflicts_classified_as_NOT_YET": 8,
}
TARGET = {
    "mixed_provenance_cells": 0,
    "data_wide_inconsistencies": 0,
    "four_bucket_incomplete_points": 0,
    "adopted_units_triple_rule": 25,
    "conflicts_classified_as_NOT_YET": 0,
}
#: "越大越好"(採用數)還是"越小越好"(不一致/誤分類數)
DIRECTION = {
    "mixed_provenance_cells": "down",
    "data_wide_inconsistencies": "down",
    "four_bucket_incomplete_points": None,   # 只印不當閘門(見 BASELINE 上方說明)
    "adopted_units_triple_rule": "up",
    "conflicts_classified_as_NOT_YET": "down",
}

_MAP3 = {"公債": "GB", "公司債": "公司債", "金融債": "金融債"}


def compute():
    data = json.load(open("data.json", encoding="utf-8"))
    manifest = json.load(open("preview/build_manifest.json", encoding="utf-8"))

    cells = facts.load()
    train, _leak = holdout.split(cells)
    verdict, _audit = reconcile.verify_all(train)
    bmap = fill.basis_map()
    by_cell = {}
    for key, v in verdict.items():
        got = creport.cell_of(key, bmap.get(key.split("|")[0]))
        if got:
            by_cell[got] = (key, v)

    # ── mixed_provenance_cells:core.units.adopt() 的回傳只有**一個**
    #    provenance 值,涵蓋它列出的 projections —— 結構上不可能對同一
    #    (cell,cls) 回報「wide 是 v3、wide_cost 是 v2」這種混合結果。
    #    這裡逐一呼叫實測,確認回傳值真的只有單一 provenance(而不是空口保證);
    #    這條規則本身有沒有被繞過,由 test_units.py 的 U1 注入測試把關。
    triples = sorted({(cell, cls) for cell in data.get("wide", {}) for cls in ("Trading", "OCI", "AC")})
    mixed_provenance_cells = 0
    for cell, cls in triples:
        key, v = by_cell.get((cell, cls), (None, None))
        out = units.adopt(v, data, cell, cls, holdout.HOLDOUT, {})
        assert isinstance(out["provenance"], str)  # 單一值,非 per-projection dict

    # ── data_wide_inconsistencies:對 provenance==v3 且結尾 |wide 的單位,
    #    取 1:1 對得上的三個桶,比 data[cell][cls][舊桶] 與 wide[cell][f"{cls}_{新桶}"]。
    v3_wide_units = [u["unit"] for u in manifest["units"]
                      if u["provenance"] == "v3" and u["unit"].endswith("|wide")]
    #
    # ⚠️ 2026-08-14 修正:這一項原本把「一邊有值一邊沒有」也算成不一致,
    #    而那**問錯了問題**。實測今天的 105 個計數點 **105 個全部**是同一種
    #    情形:`wide` 有值,但那格因為 `build.py` 的「四桶齊全才進 data」規則
    #    整格不在 `data` 裡(例:2020H2|兆豐|Trading 三個桶都是 None vs 13/275/53)。
    #    那是刻意的設計 —— 半齊的格子會畫出一根偏低卻看起來正常的長條,所以
    #    整格不出現。把設計決策數成「不一致」,數字只會隨著發布覆蓋率上升而
    #    上升,棘輪因此會在**做對事的時候**變紅(這次 102→105 就是華南上線)。
    #
    #    真正該守的不變量是「兩邊都有值時不准分岔」。`build.py` 已經把
    #    `data`(四桶)改成由 `wide` 推導,所以這件事結構上不該再發生 ——
    #    本項就是在驗那個結構保證沒有被繞過,而不是在數覆蓋率。
    #    覆蓋率另立 `four_bucket_incomplete_points` 一項,看得見但不當成惡化。
    bad = incomplete = 0
    for u in v3_wide_units:
        cell, cls, _basis = u.rsplit("|", 2)
        old = ((data.get("data") or {}).get(cell) or {}).get(cls) or {}
        new = (data.get("wide") or {}).get(cell) or {}
        for old_b, new_b in _MAP3.items():
            a, b = old.get(old_b), new.get(f"{cls}_{new_b}")
            if a is None and b is None:
                continue
            if a is None or b is None:
                incomplete += 1          # 四桶未齊全 → 整格不進 data(設計如此)
            elif abs(a - b) > 1:
                bad += 1                 # 兩邊都有值卻不同 → 真的分岔
    data_wide_inconsistencies = bad
    four_bucket_incomplete_points = incomplete

    # ── adopted_units_triple_rule:用 core.units.adopt 對真實 verdict + 快照重算,
    #    數 provenance == v3 的三元組。
    adopted = sum(1 for cell, cls in triples
                  if units.adopt(by_cell.get((cell, cls), (None, None))[1], data,
                                  cell, cls, holdout.HOLDOUT, {})["provenance"] == "v3")
    adopted_units_triple_rule = adopted

    # ── conflicts_classified_as_NOT_YET:manifest 的 8 處 conflicts,只有
    #    unit/reason 兩個欄位、沒有完整 verdict —— 用 core.units.adopt 重跑
    #    時只能傳 verdict=None,誠實地得到 NOT_YET。這正是本項要暴露的缺口:
    #    build_manifest.json 的 schema 今天存不下能分辨 CONTRADICTION 的資訊,
    #    這是 C4 要補的(manifest 改存完整 verdict 或狀態欄)。
    conflicts = manifest.get("conflicts", [])
    not_yet = 0
    for c in conflicts:
        unit = c["unit"]
        cell, cls, _basis = unit.rsplit("|", 2)
        out = units.adopt(None, data, cell, cls, holdout.HOLDOUT, {})
        if out["state"] == units.NOT_YET:
            not_yet += 1
    conflicts_classified_as_NOT_YET = not_yet

    return {
        "mixed_provenance_cells": mixed_provenance_cells,
        "data_wide_inconsistencies": data_wide_inconsistencies,
        "four_bucket_incomplete_points": four_bucket_incomplete_points,
        "adopted_units_triple_rule": adopted_units_triple_rule,
        "conflicts_classified_as_NOT_YET": conflicts_classified_as_NOT_YET,
    }


def main():
    got = compute()
    print(f"{'命題':<32}{'今天':>8}{'基準':>8}{'目標':>8}{'判定'}")
    worse = []
    for k in BASELINE:
        v, base, tgt = got[k], BASELINE[k], TARGET[k]
        if DIRECTION[k] is None:
            regressed = False
        elif DIRECTION[k] == "down":
            regressed = v > base
        else:
            regressed = v < base
        mark = "✗ 惡化" if regressed else (
            "(僅供參考,不當閘門)" if DIRECTION[k] is None
            else "=" if v == base else "△ 與文件基準不同(非惡化)")
        print(f"{k:<32}{v:>8}{base:>8}{tgt:>8}   {mark}")
        if regressed:
            worse.append(k)
    if worse:
        print(f"\n✗ 惡化的命題:{worse}")
        return 1
    print("\n✓ 沒有命題惡化(有命題與文件基準不同但非惡化,見上方 △,已在回報中解釋)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
