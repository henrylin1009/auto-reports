# -*- coding: utf-8 -*-
"""core.units 的合成輸入單元測試(R2)。不碰真實資料,見 test_rulings.py。

每一條命題都要「注入錯誤 → 測試失敗」才算數(plan_clean_core.md 的規矩)。
本檔跑法:`python3 test_units.py`,把每一條的「正常」與「注入」都印出來,
最後 exit 0/1。"""
import copy

from core import units


def _verdict(doc="202404_兆豐_個體", cls="OCI", passed=True, wide="filled", wide_cost="filled"):
    def book(tag):
        if tag is None:
            return None
        return {b: 1 for b in ["GB", "公司債", "金融債", "資產基礎", "貨幣市場", "其他", "股票"]}
    return {"doc": doc, "class": cls, "pass": passed,
            "wide": book(wide), "wide_cost": book(wide_cost)}


def _snapshot(cell, cls, has_wide=True, has_wide_cost=True, has_data=True):
    snap = {"data": {}, "wide": {}, "wide_cost": {}}
    if has_data:
        snap["data"][cell] = {cls: {"公債": 1}}
    if has_wide:
        snap["wide"][cell] = {f"{cls}_GB": 1}
    if has_wide_cost:
        snap["wide_cost"][cell] = {f"{cls}_GB": 1}
    return snap


CELL, CLS = "2024H2|兆豐", "OCI"


def U1(adopt_fn):
    """快照有 wide_cost 而 v3 供不出 → 整格 v2,wide 也不採用。"""
    v = _verdict(wide="filled", wide_cost=None)
    snap = _snapshot(CELL, CLS, has_wide=True, has_wide_cost=True)
    out = adopt_fn(v, snap, CELL, CLS, (), {})
    ok = out["provenance"] == "v2"
    return ok, out


def U2():
    """快照沒填 wide_cost 而 v3 只有 wide → 可以採用。"""
    v = _verdict(wide="filled", wide_cost=None)
    snap = _snapshot(CELL, CLS, has_wide=True, has_wide_cost=False)
    out = units.adopt(v, snap, CELL, CLS, (), {})
    return out["provenance"] == "v3", out


def U3(collapse_blocked_into_not_yet=False):
    """六道未過 → BLOCKED,不是 NOT_YET。"""
    v = _verdict(passed=False)
    snap = _snapshot(CELL, CLS)
    out = units.adopt(v, snap, CELL, CLS, (), {})
    if collapse_blocked_into_not_yet and out["state"] == units.BLOCKED:
        out = dict(out, state=units.NOT_YET)  # 注入:把 BLOCKED 併成 NOT_YET
    return out["state"] == units.BLOCKED, out


def U4():
    """verdict 不存在 → NOT_YET。"""
    snap = _snapshot(CELL, CLS)
    out = units.adopt(None, snap, CELL, CLS, (), {})
    return out["state"] == units.NOT_YET, out


def U5(force_not_yet=False):
    """v3 pass 但某口徑 null 且快照該投影有值 → CONTRADICTION。"""
    v = _verdict(wide=None, wide_cost="filled")
    snap = _snapshot(CELL, CLS, has_wide=True, has_wide_cost=True)
    out = units.adopt(v, snap, CELL, CLS, (), {})
    if force_not_yet and out["state"] == units.CONTRADICTION:
        out = dict(out, state=units.NOT_YET)  # 注入:歸成 NOT_YET
    return out["state"] == units.CONTRADICTION, out


def U6():
    """七桶缺一 → 不採用。"""
    v = _verdict()
    v["wide"].pop("股票")
    snap = _snapshot(CELL, CLS)
    out = units.adopt(v, snap, CELL, CLS, (), {})
    return out["provenance"] == "v2", out


def U7():
    """key 在 holdout → 永不採用(即使全部合格)。"""
    v = _verdict(doc="202502_兆豐_個體", cls="OCI")
    snap = _snapshot(CELL, CLS)
    out = units.adopt(v, snap, CELL, CLS, {"202502_兆豐_個體|OCI"}, {})
    return out["provenance"] == "v2", out


def U8(silent_fallback=False):
    """ledger 記為 v3 但這次不合格 → CONTRADICTION 且 reason 含「已發布過」。"""
    v = _verdict(passed=False)
    snap = _snapshot(CELL, CLS)
    ledger = {} if silent_fallback else {f"{CELL}|{CLS}": "v3"}
    out = units.adopt(v, snap, CELL, CLS, (), ledger)
    ok = (out["state"] == units.CONTRADICTION and "已發布過" in out["reason"])
    return ok, out


def U9(invent_wide_cost=False):
    """真實回歸(2026-07-28 使用者裁示):`2021H1|玉山|OCI`。

    快照(`data.json`)從未提供這格的 `wide_cost`(全 None),v3 只提供 `wide`。
    依 U2 的字面規則,這格**可以**採 v3,但只切 `wide` 這一個投影 ——
    `wide_cost` 必須維持缺失(None),**不得**回填 v2 的舊值,也**不得**
    憑空補一個 v3 沒給的數字。這是 `test_rulings.py` 把
    `adopted_units_triple_rule` 基準從 24 改成 25 的具體那一格,獨立寫一條
    回歸測試釘住它,不要只靠棘輪的總數字。
    """
    cell, cls = "2021H1|玉山", "OCI"
    v = _verdict(doc="202102_玉山_個體", cls=cls, wide="filled", wide_cost=None)
    snap = _snapshot(cell, cls, has_wide=True, has_wide_cost=False)
    out = units.adopt(v, snap, cell, cls, (), {})
    projections = set(out["projections"])
    if invent_wide_cost:
        projections.add("wide_cost")  # 注入:假裝 wide_cost 也被切過去了
    ok = (out["provenance"] == "v3"
          and projections == {"wide"}
          and "wide_cost" not in projections)
    return ok, out


def _run(name, fn, *args, expect_pass=True):
    ok, out = fn(*args)
    mark = "✓" if ok == expect_pass else "✗"
    tag = "正常" if expect_pass else "注入(必須紅)"
    print(f"  {mark} {name} [{tag}] → {out}")
    return ok == expect_pass


def main():
    allok = True

    print("U1 快照有 wide_cost 而 v3 供不出 → 整格 v2")
    allok &= _run("U1", U1, units.adopt, expect_pass=True)
    print("  注入:讓 adopt 假裝可以回傳 v3 →")

    def bad_adopt(*a):
        out = units.adopt(*a)
        out = dict(out, provenance="v3")  # 注入:硬改成 v3
        return out
    allok &= _run("U1-注入", U1, bad_adopt, expect_pass=False)

    print("U2 快照沒填 wide_cost、v3 只有 wide → 可採用")
    allok &= _run("U2", U2, expect_pass=True)

    print("U3 六道未過 → BLOCKED,不是 NOT_YET")
    allok &= _run("U3", U3, expect_pass=True)
    allok &= _run("U3-注入(把 BLOCKED 併成 NOT_YET)", U3, True, expect_pass=False)

    print("U4 verdict 不存在 → NOT_YET")
    allok &= _run("U4", U4, expect_pass=True)

    print("U5 v3 pass 但某口徑 null 且快照該投影有值 → CONTRADICTION")
    allok &= _run("U5", U5, expect_pass=True)
    allok &= _run("U5-注入(歸成 NOT_YET)", U5, True, expect_pass=False)

    print("U6 七桶缺一 → 不採用")
    allok &= _run("U6", U6, expect_pass=True)

    print("U7 key 在 holdout → 永不採用")
    allok &= _run("U7", U7, expect_pass=True)

    print("U8 ledger 記為 v3 但這次不合格 → CONTRADICTION 且 reason 含「已發布過」")
    allok &= _run("U8", U8, expect_pass=True)
    allok &= _run("U8-注入(靜靜回退 v2,不記 ledger)", U8, True, expect_pass=False)

    print("U9 真實回歸:2021H1|玉山|OCI —— 可採 v3(只切 wide),wide_cost 維持缺失")
    allok &= _run("U9", U9, expect_pass=True)
    allok &= _run("U9-注入(憑空把 wide_cost 也算進 projections)", U9, True, expect_pass=False)

    print(f"\n{'全部通過' if allok else '有失敗'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
