# -*- coding: utf-8 -*-
"""core.contracts 的 round-trip / oracle 一致 / 注入測試(C0.5)。"""
import copy

import facts
from core import contracts


def P1():
    """round-trip:dump_cell(parse_cell(x)) == x 對 36 格全數成立。"""
    cells = facts.load()
    bad = []
    for key, raw in cells.items():
        cell = contracts.parse_cell(key, raw)
        got = contracts.dump_cell(cell)
        if got != raw:
            bad.append(key)
    ok = not bad
    print(f"  {'✓' if ok else '✗'} P1 round-trip:{len(cells)} 格,不一致 {len(bad)}:{bad}")
    return ok


def P2():
    """core.contracts.validate 與 facts.validate 對 36 格結果逐條一致。"""
    cells = facts.load()
    a = contracts.validate(cells)
    b = facts.validate(cells)
    ok = a == b
    print(f"  {'✓' if ok else '✗'} P2 oracle 一致:contracts={len(a)} facts={len(b)}")
    return ok


def P3():
    """缺必要欄位 → raise。拿掉 printed_total → 必須紅。"""
    cells = facts.load()
    key, raw = next(iter(cells.items()))
    bad = copy.deepcopy(raw)
    del bad[0]["printed_total"]
    try:
        contracts.parse_cell(key, bad)
        print("  ✗ P3(必須紅):拿掉 printed_total 卻沒 raise")
        return False
    except ValueError as e:
        print(f"  ✓ P3(注入 → 紅):{e}")
        return True


def P4():
    """型別錯誤 → raise。cols 的值放字串 → 必須紅。"""
    cells = facts.load()
    key, raw = next(iter(cells.items()))
    bad = copy.deepcopy(raw)
    first_col = next(iter(bad[0]["rows"][0]["cols"]))
    bad[0]["rows"][0]["cols"][first_col] = "not-an-int"
    try:
        contracts.parse_cell(key, bad)
        print("  ✗ P4(必須紅):cols 值放字串卻沒 raise")
        return False
    except ValueError as e:
        print(f"  ✓ P4(注入 → 紅):{e}")
        return True


def P5():
    """分類未知的列必須存得進去(鐵則 3)。"""
    raw = [{
        "doc": "TESTDOC", "class": "OCI", "source_page": 1, "source_kind": "附註",
        "total_col": "col", "printed_total": 100,
        "rows": [{"name": "某個不存在的科目名", "cols": {"col": 100}}],
    }]
    try:
        cell = contracts.parse_cell("TESTDOC|OCI", raw)
        ok = len(cell.records[0].rows) == 1
        print(f"  ✓ P5:分類未知的列（buckets.bucket 回 None）成功存進 contracts")
        return ok
    except Exception as e:
        print(f"  ✗ P5(必須綠卻紅):{e}")
        return False


def main():
    print("P1 round-trip")
    ok = P1()
    print("P2 與 facts.validate 逐條一致")
    ok &= P2()
    print("P3 缺欄注入")
    ok &= P3()
    print("P4 型別注入")
    ok &= P4()
    print("P5 分類未知必須存得進去(鐵則 3)")
    ok &= P5()
    print(f"\n{'全部通過' if ok else '有失敗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
