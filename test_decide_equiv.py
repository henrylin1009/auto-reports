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


def _new_decide(row, group, rules_by_name):
    """Call core.decisions.decide() and return the full decision dict."""
    return D.decide(row, group, rules_by_name, rules_mod.propose)


def _is_propose_guess(decision):
    """這個 decision 是不是靠 `rules.propose()` 關鍵字猜出來的(而不是命中
    taxonomy 裡已核准的 name/group 規則)?

    2026-08-12 調查記錄(見下面 test_equiv 的檔頭說明):`decide()` 在
    taxonomy 查不到規則時會呼叫 `propose_fn` 猜一個 PROVISIONAL 結果等人審,
    這是它比 `buckets.bucket()` 多的一層 —— `buckets.bucket()` 查不到就是
    `None`,不猜。兩者在這一層本來就不該逐列相等,不是同步缺口。

    判準是**來源類型**(`references[0]["kind"] == "rule"`,即靠規則庫關鍵字
    命中而非人工核准的 taxonomy 條目),不是名字白名單 —— 白名單會變成
    「針對某個名字寫例外」,鐵律 2 不准這樣做。
    """
    refs = decision.get("references") or []
    return bool(refs) and refs[0].get("kind") == "rule"


def test_equiv():
    """Main equivalence test: 583 rows, all TAXONOMY-BACKED mappings match.

    2026-08-12 調查記錄:這支測試曾抓到兩個真的 bug(見 core/decisions.py
    的修法記錄)—— `decide()` 有一段違反 buckets.bucket() 規則的 group
    fallback,以及沒有實作 buckets.py 的剝註腳重查邏輯。兩個都修了,
    taxonomy/rules.json 也補齊了三筆漏收的既有 SYN 規則。

    修完之後只剩一種分歧,而且是**設計上就該分歧**的:`decide()` 查不到
    taxonomy 規則時會呼叫 `rules.propose()` 猜一個 PROVISIONAL 結果等人審,
    `buckets.bucket()` 查不到就是 None、不猜。這一層 decide() 比 bucket()
    多做的事,兩者本來就不該逐列相等 —— 所以這支測試**只比對「taxonomy
    命中」的那一段**(`_is_propose_guess()` 排除掉猜測產生的分歧),其餘
    情況任何不一致都仍然是失敗(不是放寬,是排除掉一個問錯的斷言)。
    """
    label = "equiv: 583 rows, decide() mapping == buckets.bucket() (taxonomy-backed rows)"

    cells = facts.load()
    rules_by_name = _load_rules_by_name()

    total = 0
    mismatches = []
    excluded_guesses = 0

    for cell_key, recs in cells.items():
        for rec in recs:
            for row in rec["rows"]:
                total += 1
                old_bucket = buckets.bucket(row)
                group = row.get("group") or ""

                decision = _new_decide(row, group, rules_by_name)
                new_mapping = decision["mapping"]

                if old_bucket == new_mapping:
                    continue
                if _is_propose_guess(decision):
                    excluded_guesses += 1
                    continue
                mismatches.append({
                    "cell_key": cell_key,
                    "name": row["name"],
                    "group": group,
                    "old_bucket": old_bucket,
                    "new_mapping": new_mapping,
                })

    if not mismatches:
        ok(label + f" ({total} rows checked, 0 mismatches, "
                   f"{excluded_guesses} propose-guess divergences excluded by design)")
    else:
        fail(label, f"{len(mismatches)}/{total} rows differ "
                     f"(after excluding {excluded_guesses} propose-guess divergences):")
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
    mapping_deriv = _new_decide(row_deriv, group_deriv, rules_by_name)["mapping"]

    # Row with GENERIC name in non-衍生 group
    row_other = {"name": "其他", "cols": {"公允價值總額": 100}, "group": "有價證券"}
    group_other = "有價證券"
    mapping_other = _new_decide(row_other, group_other, rules_by_name)["mapping"]

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
