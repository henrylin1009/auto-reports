#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_decide_equiv.py — B1 等價閘門

對 facts/ 的 583 列逐列比對:
    new = core.decisions.decide(row, group, rules_by_name, rules.propose)["mapping"]
    old = buckets.bucket(row)

斷言: 583 列逐列 mapping 相同。

執行方式: python3 test_decide_equiv.py
exit 0 = 全綠
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import facts
import buckets
import rules as rules_mod
from core import decisions as D

PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


def _load_rules_by_name():
    """Load taxonomy/rules.json and build a name→rule lookup for decide()."""
    rules_path = os.path.join(os.path.dirname(__file__), "taxonomy", "rules.json")
    with open(rules_path, encoding="utf-8") as f:
        all_rules = json.load(f)

    # Build lookup: normalized name → rule, and group:normalized_group → rule
    rules_by_name = {}
    for r in all_rules:
        rule_id = r["rule_id"]
        if r["scope"] == "name":
            # key is the normalized name (rule_id = "tax:norm_name")
            norm_name = rule_id.replace("tax:", "", 1)
            rules_by_name[norm_name] = r
        elif r["scope"] == "group":
            # key is "group:norm_group_name" (rule_id = "tax:group:norm_name")
            norm_name = rule_id.replace("tax:group:", "", 1)
            rules_by_name[f"group:{norm_name}"] = r
        elif r["scope"] == "generic":
            # key is "generic:norm_name" for is_generic detection in decide()
            norm_name = rule_id.replace("tax:generic:", "", 1)
            rules_by_name[f"generic:{norm_name}"] = r

    return rules_by_name


def _new_decide_mapping(row, group, rules_by_name):
    """Call core.decisions.decide() and return mapping."""
    result = D.decide(row, group, rules_by_name, rules_mod.propose)
    return result["mapping"]


def test_equiv():
    """Main equivalence test: 583 rows, all mappings match."""
    label = "equiv: 583 rows, decide() mapping == buckets.bucket() for all"

    cells = facts.load()
    rules_by_name = _load_rules_by_name()

    total = 0
    mismatches = []

    for cell_key, recs in cells.items():
        for rec in recs:
            for row in rec["rows"]:
                total += 1
                old_bucket = buckets.bucket(row)
                group = row.get("group") or ""

                new_mapping = _new_decide_mapping(row, group, rules_by_name)

                if old_bucket != new_mapping:
                    mismatches.append({
                        "cell_key": cell_key,
                        "name": row["name"],
                        "group": group,
                        "old_bucket": old_bucket,
                        "new_mapping": new_mapping,
                    })

    if not mismatches:
        ok(label + f" ({total} rows checked, 0 mismatches)")
    else:
        fail(label, f"{len(mismatches)}/{total} rows differ:")
        for m in mismatches[:20]:
            print(f"    [{m['cell_key']}] name={m['name']!r} group={m['group']!r} "
                  f"old={m['old_bucket']!r} new={m['new_mapping']!r}")
        if len(mismatches) > 20:
            print(f"    ... and {len(mismatches) - 20} more")

    return total, len(mismatches)


def test_generic_group_routing():
    """Verify that 其他/其他(註) route via group correctly.

    §B1.7 warns: decide() must pass group so 其他/其他(註) can be split into
    {其他, 衍生} depending on the paragraph.
    """
    label = "generic-group: 其他 in 衍生 group → 衍生; 其他 in non-衍生 group → 其他"
    rules_by_name = _load_rules_by_name()

    # Row with GENERIC name in 衍生 group
    row_deriv = {"name": "其他", "cols": {"公允價值總額": 100}, "group": "衍生金融工具"}
    group_deriv = "衍生金融工具"
    mapping_deriv = _new_decide_mapping(row_deriv, group_deriv, rules_by_name)

    # Row with GENERIC name in non-衍生 group
    row_other = {"name": "其他", "cols": {"公允價值總額": 100}, "group": "有價證券"}
    group_other = "有價證券"
    mapping_other = _new_decide_mapping(row_other, group_other, rules_by_name)

    # Also check with old buckets.bucket()
    old_deriv = buckets.bucket(row_deriv)
    old_other = buckets.bucket(row_other)

    deriv_ok = (mapping_deriv == old_deriv)
    other_ok = (mapping_other == old_other)

    if deriv_ok and other_ok:
        ok(label + f" (deriv: {mapping_deriv!r}={old_deriv!r}, other: {mapping_other!r}={old_other!r})")
    else:
        fail(label, f"deriv: new={mapping_deriv!r} old={old_deriv!r}  "
             f"other: new={mapping_other!r} old={old_other!r}")


def main():
    print("=" * 60)
    print("test_decide_equiv.py — B1 equivalence gate")
    print("=" * 60)

    total, mismatches = test_equiv()
    test_generic_group_routing()

    print("=" * 60)
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    print(f"Equivalence: {total - mismatches}/{total} rows match")
    if FAIL > 0:
        print("RESULT: FAIL")
        sys.exit(1)
    else:
        print("RESULT: OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
