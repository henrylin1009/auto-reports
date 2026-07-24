# -*- coding: utf-8 -*-
"""無 API 回歸:reconcile 統一、total_assets 上界、面板驗證。"""
import json, copy
import extract_v2 as E
from batch_v2 import panel_validate

def det(fair_rows, value_total):
    return {"header": "x", "saw_total_row": True, "table_continues": False,
            "cost_total": None, "value_total": value_total,
            "rows": [{"name": "公司債A", "section": "債務工具", "bucket": "公司債",
                      "cost": None, "fair": f} for f in fair_rows]}

RT, RO, BS_BAD = 126299850, 235150935, 361492785

print("=== reconcile / validate ===")
a = E.validate("Trading", det([RT], RT), BS_BAD, bs_reliable=False)
assert a["_pass"] and a["_anchor_doubt"], a
b = E.validate("Trading", det([RT], RT), BS_BAD, bs_reliable=True)
assert not b["_pass"], b
c = E.validate("Trading", det([100], 100), 100, bs_reliable=True)
assert c["_pass"] and not c["_weak_anchor"], c

print("=== extract_from_note → reconcile ===")
ns = {"subtotals": [{"bucket": "公司債", "amount": RT}], "printed_total": RT}
na = E.extract_from_note("Trading", ns, BS_BAD, bs_reliable=False)
nb = E.extract_from_note("Trading", ns, BS_BAD, bs_reliable=True)
nc = E.extract_from_note("Trading", ns, None, bs_reliable=True)  # 無 BS → fail-loud
assert na["_pass"] and na["_anchor_doubt"]
assert not nb["_pass"]
assert not nc["_pass"], nc

print("=== check_bs_anchors ===")
ok_ov, _ = E.check_bs_anchors({"Trading": 100, "OCI": 100, "AC": 100, "total_assets": 1000})
assert ok_ov is None
bad_ov, note = E.check_bs_anchors({"Trading": BS_BAD, "OCI": RO, "AC": 100, "total_assets": BS_BAD})
assert bad_ov is False and note, (bad_ov, note)

print("=== panel_validate ===")
# 假結果:富邦 Trading 三期,中間那期 fail 但落在帶內 → 應救援
fake = {
    "202102_5836_AI3": {"cls": {"Trading": {"_pass": True, "recon_fair": 72915412, "_source": "note"},
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
    "202104_5836_AI3": {"cls": {"Trading": {"_pass": False, "_cross_ok": False, "_internal_ok": True,
                                            "recon_fair": 98053708, "_source": "detail"},
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
    "202202_5836_AI3": {"cls": {"Trading": {"_pass": True, "recon_fair": 122605853, "_source": "note"},
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
}
notes = panel_validate(fake)
assert any("面板救援" in n for n in notes), notes
assert fake["202104_5836_AI3"]["cls"]["Trading"]["_pass"]
assert fake["202104_5836_AI3"]["cls"]["Trading"]["_panel_rescue"]

# 離群:通過但暴衝 → 待複核
fake2 = {
    "202102_5836_AI3": {"cls": {"Trading": {"_pass": True, "recon_fair": 100},
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
    "202104_5836_AI3": {"cls": {"Trading": {"_pass": True, "recon_fair": 500},  # 5x
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
    "202202_5836_AI3": {"cls": {"Trading": {"_pass": True, "recon_fair": 110},
                                "OCI": {"_pass": True, "recon_fair": 1}, "AC": {"_pass": True, "recon_fair": 1}}},
}
notes2 = panel_validate(fake2)
assert fake2["202104_5836_AI3"]["cls"]["Trading"]["_panel_outlier"]
assert fake2["202104_5836_AI3"]["cls"]["Trading"]["_needs_review"]

print("ALL OK")
