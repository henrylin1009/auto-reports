# -*- coding: utf-8 -*-
"""yields 存取器 —— period 格式與「靜靜回空」那個洞。

原本 interest() 只認 period 全是數字的紀錄,capital / fair_value 的
"2025-12-31" 全被濾掉 → 回空 dict、不報錯,下游整根軸留白卻沒人知道。
"""
import pytest

import yields


def test_year_三種格式():
    assert yields._year("2025-12-31") == 2025      # capital / fair_value
    assert yields._year("2025") == 2025            # pnl / interest
    assert yields._year("113") == 2024             # equity 的民國年
    assert yields._year(2025) == 2025


def test_year_認不出來的回None不亂猜():
    for bad in (None, "", "當期", "—", "20"):
        assert yields._year(bad) is None


@pytest.mark.parametrize("kind,field", [
    ("interest", "securities"), ("pnl", "net_income"),
    ("capital", "cet1"), ("fair_value", "period"),
])
def test_每個section都撿得到格子(kind, field):
    d = yields.interest(kind=kind, field=field)
    assert len(d) >= 20, f"{kind} 只撿到 {len(d)} 格"
    assert {y for y, _ in d} >= {2021, 2022, 2023, 2024, 2025}


def test_撿不到就拋錯不是回空dict(tmp_path, monkeypatch):
    """注入一份 period 認不得的資料,確認閘門真的會擋。"""
    import json
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"capital": {"202504_5841_AI3": [
        {"period": "當期", "basis_norm": "個體", "cet1": 1, "rwa": 2}]}}),
        encoding="utf-8")
    with pytest.raises(ValueError, match="一格都沒撿到"):
        yields.interest(path=str(p), kind="capital", field="cet1")


def test_沒有這個section要說清楚():
    with pytest.raises(KeyError, match="沒有 section"):
        yields.interest(kind="不存在的表")


def test_軸三_2025_RWA除CET1():
    """§12.8 驗收:兆豐缺,其餘四家對得上報告(報告用揭露的 cet1_pct 反推)。"""
    cap = yields.interest(kind="capital", field="cet1")
    got = {b: cap[(2025, b)]["rwa"] / cap[(2025, b)]["cet1"]
           for b in yields.ORDER if (2025, b) in cap}
    assert (2025, "兆豐") not in cap                 # §12.6 陷阱 8
    for b, want in {"中信": 8.39, "國泰": 7.89, "富邦": 8.29, "玉山": 8.34}.items():
        assert got[b] == pytest.approx(want, abs=0.01)
