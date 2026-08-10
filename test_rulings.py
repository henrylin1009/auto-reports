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
    "data_wide_inconsistencies": 21,
    "adopted_units_triple_rule": 25,
    "conflicts_classified_as_NOT_YET": 8,
}
TARGET = {
    "mixed_provenance_cells": 0,
    "data_wide_inconsistencies": 0,
    "adopted_units_triple_rule": 25,
    "conflicts_classified_as_NOT_YET": 0,
}
#: "越大越好"(採用數)還是"越小越好"(不一致/誤分類數)
DIRECTION = {
    "mixed_provenance_cells": "down",
    "data_wide_inconsistencies": "down",
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
    bad = 0
    for u in v3_wide_units:
        cell, cls, _basis = u.rsplit("|", 2)
        old = ((data.get("data") or {}).get(cell) or {}).get(cls) or {}
        new = (data.get("wide") or {}).get(cell) or {}
        for old_b, new_b in _MAP3.items():
            a, b = old.get(old_b), new.get(f"{cls}_{new_b}")
            if a is None and b is None:
                continue
            # 93 個比對點 = 31 個單位 × 3 個桶,一個有值一個沒有也算不一致
            # (M1 的 93 個比對點就是 31×3,沒有排除任何一邊缺值的情形)。
            if a is None or b is None or abs(a - b) > 1:
                bad += 1
    data_wide_inconsistencies = bad

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
        "adopted_units_triple_rule": adopted_units_triple_rule,
        "conflicts_classified_as_NOT_YET": conflicts_classified_as_NOT_YET,
    }


def main():
    got = compute()
    print(f"{'命題':<32}{'今天':>8}{'基準':>8}{'目標':>8}{'判定'}")
    worse = []
    for k in BASELINE:
        v, base, tgt = got[k], BASELINE[k], TARGET[k]
        if DIRECTION[k] == "down":
            regressed = v > base
        else:
            regressed = v < base
        mark = "✗ 惡化" if regressed else ("=" if v == base else "△ 與文件基準不同(非惡化)")
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
