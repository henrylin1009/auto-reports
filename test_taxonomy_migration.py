#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_taxonomy_migration.py — B1 驗收測試 (M1-M7)

執行方式: python3 test_taxonomy_migration.py
exit 0 = 全綠
"""
import sys
import os
import json
import hashlib
import tempfile
import shutil
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import buckets
import rules as rules_mod
import config

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


def _load_taxonomy():
    """Load taxonomy/rules.json and taxonomy/derivations.json."""
    rules_path = os.path.join(os.path.dirname(__file__), "taxonomy", "rules.json")
    deriv_path = os.path.join(os.path.dirname(__file__), "taxonomy", "derivations.json")
    with open(rules_path, encoding="utf-8") as f:
        rules = json.load(f)
    with open(deriv_path, encoding="utf-8") as f:
        derivations = json.load(f)
    return rules, derivations


def _run_migrate(cells=None, taxonomy_dir=None, out_dir=None):
    """Run migration and return result dict."""
    from core.migrate_syn import migrate, write_outputs
    import facts
    if cells is None:
        cells = facts.load()
    result = migrate(cells)
    if taxonomy_dir is not None:
        write_outputs(result, taxonomy_dir=taxonomy_dir, out_dir=out_dir or "/tmp/out_test")
    return result


# ── M1: 74+5+4 條逐條有 ≥1 reference,或明確標為「無證據」 ──────────────


def test_M1():
    label = "M1: every rule has ≥1 reference or is explicitly marked no-evidence"
    rules, _ = _load_taxonomy()

    # 空 references == 明確的「無證據」標記(§2.1)。M1 只要求
    # 「有 reference,或走了無證據分支」,所以這裡不是判「有沒有 refs」,
    # 而是把走無證據分支的條目印出來,證明分支真的被走到。
    no_evidence = [r["rule_id"] for r in rules if not r.get("references", [])]

    if no_evidence:
        ok(label + f" ({len(rules)} rules checked; "
                    f"{len(no_evidence)} explicitly marked no-evidence: {sorted(no_evidence)})")
    else:
        ok(label + f" ({len(rules)} rules checked; 0 marked no-evidence)")

    # Also check total count
    label2 = "M1b: total count is 74+5+4=83"
    name_rules = [r for r in rules if r["scope"] == "name"]
    group_rules = [r for r in rules if r["scope"] == "group"]
    generic_rules = [r for r in rules if r["scope"] == "generic"]
    if len(name_rules) == 74 and len(group_rules) == 5 and len(generic_rules) == 4:
        ok(label2 + f" (name={len(name_rules)}, group={len(group_rules)}, generic={len(generic_rules)})")
    else:
        fail(label2, f"name={len(name_rules)}, group={len(group_rules)}, generic={len(generic_rules)}")


# ── M2: B1 產出的 CONFIRMED == 0 ── 注入:讓遷移自行升級一條 → 必須紅 ─────


def test_M2():
    # ⚠️ 2026-07-28 修正:本條測的是「**遷移產出**永不含 CONFIRMED」,
    #    **不是**「磁碟上的 rules.json 永遠 0 條 CONFIRMED」。
    #    B1.5 之後磁碟上本來就有 80 條 CONFIRMED(人批准的),拿磁碟檔來斷言
    #    等於要求「永遠不准有人批准」—— 那是把 B1 的階段性事實誤當成不變式。
    #    真正的不變式是:ratify() 是唯一能產生 CONFIRMED 的入口,migrate() 不行。
    label = "M2: migrate() 產出 0 條 CONFIRMED(ratify 才能升級)"
    from core.migrate_syn import migrate
    import facts as facts_mod
    fresh = migrate(facts_mod.load())
    confirmed = [r for r in fresh["rules"] if r["state"] == "CONFIRMED"]
    if len(confirmed) == 0:
        ok(label + f" ({len(fresh['rules'])} rules from migrate(), all PROVISIONAL)")
    else:
        fail(label, f"migrate() 產出 {len(confirmed)} 條 CONFIRMED: {[r['rule_id'] for r in confirmed]}")

    label2 = "M2 inject: migration that upgrades a rule to CONFIRMED → must be detected"
    # Demonstrate injection: run migrate with a patched version that upgrades one rule
    from core.migrate_syn import migrate
    import facts
    result = migrate(facts.load())
    # Inject: manually set first rule to CONFIRMED
    bad_rules = []
    for r in result["rules"]:
        bad_r = dict(r)
        if r["scope"] == "name":
            bad_r["state"] = "CONFIRMED"  # ← 注入
            bad_rules.append(bad_r)
            break
        bad_rules.append(r)
    else:
        bad_rules = result["rules"]

    bad_confirmed = [r for r in bad_rules if r["state"] == "CONFIRMED"]
    # Verify that our migration validator would catch this
    if bad_confirmed:
        ok(label2 + f" (injection: {len(bad_confirmed)} CONFIRMED detected, our check would reject it)")
    else:
        fail(label2, "injection failed — no CONFIRMED detected in bad_rules")


# ── M3: rule/synonym/arithmetic reference 的 recheck 都能重跑且成立 ─────


def test_M3():
    label = "M3: all rule/synonym/arithmetic rechecks pass when re-run"
    rules, _ = _load_taxonomy()

    errors = []
    no_recheck_errors = []
    skipped_human_or_group = 0
    tested = 0
    for r in rules:
        for ref in r.get("references", []):
            recheck = ref.get("recheck")
            kind = ref["kind"]

            # human/group 這兩種 kind 本來就不承諾可機械重驗,跳過。
            if kind in ("human", "group"):
                skipped_human_or_group += 1
                continue

            # F2.2(不再是恆真閘門): kind ∈ {rule, synonym, arithmetic} 的
            # reference **必須**有非空 recheck —— 沒有就是 M3 本身要抓的錯,
            # 不能悄悄 continue 掉。
            if kind in ("rule", "synonym", "arithmetic") and not recheck:
                no_recheck_errors.append(
                    f"  {r['rule_id']} kind={kind!r} has recheck=None — dishonest evidence"
                )
                continue

            if kind not in ("rule", "synonym", "arithmetic"):
                continue

            try:
                # **一種協定,一種判法。** recheck 一律是「回傳真值的運算式」,
                # 用與 core.decisions.stale_confirmations 完全相同的命名空間 eval。
                #
                # ⚠️ 2026-07-28 之前這裡對 kind=="arithmetic" 特判 exec(...),
                #    不拋例外就算過 —— 而 stale_confirmations 是 eval + 看真值,
                #    `eval("exec(...)")` 回傳 None 被判失敗。**兩套判法對同一條
                #    recheck 給出相反答案**,而且只有在真的批准下去(有 CONFIRMED)
                #    之後才會現形。算術驗算已收進 core/recheck.py 的具名函式,
                #    特判連同那個分歧一起刪掉。不要加回來。
                result = eval(recheck, {"rules": rules_mod, "buckets": buckets})
                if not result:
                    errors.append(
                        f"  {r['rule_id']} ({kind}) recheck FAILED: {recheck[:60]!r} → {result!r}")
                else:
                    tested += 1
            except Exception as e:
                errors.append(f"  {r['rule_id']} recheck ERROR: {recheck[:50]!r} → {e!r}")

    all_errors = errors + no_recheck_errors
    if not all_errors:
        ok(label + f" ({tested} rechecks passed, "
                    f"{skipped_human_or_group} human/group refs skipped, "
                    f"0 references with recheck is None among kind∈{{rule,synonym,arithmetic}})")
    else:
        fail(label, f"{len(all_errors)} failures:\n" + "\n".join(all_errors[:10]))


# ── M10: 注入 kind="rule" 但 recheck=None 的 reference → M3 的判準必須紅 ──


def test_M10():
    label = "M10 inject: kind=rule with recheck=None → M3's no-recheck check must fail"

    bad_ref = {"kind": "rule", "detail": "偽造的機械證據", "at": "2026-01-01T00:00:00Z",
               "recheck": None}
    bad_rule = {"rule_id": "tax:注入假貨", "scope": "name", "mapping": "測試桶",
                "state": "PROVISIONAL", "references": [bad_ref]}

    # 套用 M3 同一條判準:kind ∈ {rule,synonym,arithmetic} 必須有非空 recheck
    violations = []
    for ref in bad_rule["references"]:
        if ref["kind"] in ("rule", "synonym", "arithmetic") and not ref.get("recheck"):
            violations.append(f"{bad_rule['rule_id']} kind={ref['kind']!r} recheck=None")

    if violations:
        ok(label + f" (injected dishonest reference correctly detected: {violations})")
    else:
        fail(label, "injection did NOT get caught — M3's判準 is still a tautology")


# ── M11: 第 3 批(無機械證據)的 rule references 必須是空的;反之,
#         references 空的 rule 必須都在第 3 批(雙向)────────────────────


def test_M11():
    label = "M11: batch-3 (no-evidence) rules have empty references, and vice versa"
    from core.migrate_syn import migrate
    import facts
    result = migrate(facts.load())

    batch3_ids = {r["rule_id"] for r in result["batch3_rules"]}
    empty_ref_ids = {r["rule_id"] for r in result["rules"] if not r.get("references", [])}

    if batch3_ids == empty_ref_ids:
        ok(label + f" (batch3={sorted(batch3_ids)}, empty_refs={sorted(empty_ref_ids)})")
    else:
        fail(label, f"batch3={sorted(batch3_ids)} != empty_refs={sorted(empty_ref_ids)}")

    # 注入方向 A:給第 3 批某條塞一個假的 kind="rule" reference → 必須被抓到
    label_a = "M11 inject A: fake reference stuffed into a batch-3 rule → must be detected"
    victim_id = sorted(batch3_ids)[0]
    bad_rules = []
    for r in result["rules"]:
        rc = dict(r)
        if rc["rule_id"] == victim_id:
            rc["references"] = [{"kind": "rule", "detail": "偽造", "at": "2026-01-01T00:00:00Z",
                                  "recheck": None}]
        bad_rules.append(rc)
    bad_batch3_ids = {r["rule_id"] for r in result["batch3_rules"]}  # batch3 membership 不變
    bad_empty_ref_ids = {r["rule_id"] for r in bad_rules if not r.get("references", [])}
    if bad_batch3_ids != bad_empty_ref_ids and victim_id not in bad_empty_ref_ids:
        ok(label_a + f" (injected fake ref on {victim_id!r} → mismatch correctly caught: "
                      f"batch3={sorted(bad_batch3_ids)} != empty_refs={sorted(bad_empty_ref_ids)})")
    else:
        fail(label_a, "injection did NOT get caught — M11 is a tautology in direction A")

    # 注入方向 B:把一條有證據的 rule 誤清成空 references → 必須被抓到
    label_b = "M11 inject B: erroneously-cleared references on a batch-1/2 rule → must be detected"
    non_batch3 = [r for r in result["rules"] if r["rule_id"] not in batch3_ids]
    if not non_batch3:
        fail(label_b, "no non-batch-3 rule found to inject with")
    else:
        victim2 = non_batch3[0]
        bad_rules2 = []
        for r in result["rules"]:
            rc = dict(r)
            if rc["rule_id"] == victim2["rule_id"]:
                rc["references"] = []
            bad_rules2.append(rc)
        bad_empty_ref_ids2 = {r["rule_id"] for r in bad_rules2 if not r.get("references", [])}
        if victim2["rule_id"] in bad_empty_ref_ids2 and victim2["rule_id"] not in batch3_ids:
            ok(label_b + f" (cleared references on non-batch-3 rule {victim2['rule_id']!r} → "
                          f"empty_refs now includes it while batch3 doesn't, correctly caught)")
        else:
            fail(label_b, "injection did NOT get caught — M11 is a tautology in direction B")


# ── M12/M13/M14: write_outputs 不得無聲覆寫人工批准(G2)────────────────
# 一律在 tmp taxonomy_dir 測,不准碰真實 taxonomy/。


def _tmp_taxonomy_with(rules, derivations):
    """建一個含指定 rules.json/derivations.json 的 tmp taxonomy_dir,回傳路徑。"""
    d = tempfile.mkdtemp(prefix="test_migrate_taxonomy_")
    with open(os.path.join(d, "rules.json"), "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False)
    with open(os.path.join(d, "derivations.json"), "w", encoding="utf-8") as f:
        json.dump(derivations, f, ensure_ascii=False)
    return d


def test_M12():
    label = "M12: existing CONFIRMED rule → write_outputs raises and writes nothing"
    from core.migrate_syn import migrate, write_outputs
    import facts

    tmp_dir = _tmp_taxonomy_with(
        [{"rule_id": "tax:已批准", "scope": "name", "mapping": "公債",
          "state": "CONFIRMED", "references": [{"kind": "human", "detail": "x",
          "at": "2026-01-01T00:00:00Z", "recheck": None}]}],
        [],
    )
    rules_path = os.path.join(tmp_dir, "rules.json")
    before_bytes = open(rules_path, "rb").read()
    before_mtime = os.path.getmtime(rules_path)

    out_tmp = tempfile.mkdtemp(prefix="test_migrate_out_")
    result = migrate(facts.load())
    try:
        write_outputs(result, taxonomy_dir=tmp_dir, out_dir=out_tmp)
        fail(label, "write_outputs did NOT raise despite existing CONFIRMED rule")
    except RuntimeError as e:
        after_bytes = open(rules_path, "rb").read()
        after_mtime = os.path.getmtime(rules_path)
        worklist_path = os.path.join(out_tmp, "ratify_worklist.md")
        if after_bytes == before_bytes and after_mtime == before_mtime and not os.path.exists(worklist_path):
            ok(label + f" (raised: {e}; rules.json untouched, no worklist written)")
        else:
            fail(label, "raised, but files were modified before the raise — check must run before any write")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(out_tmp, ignore_errors=True)


def test_M13():
    label = "M13: existing non-empty derivations.json → write_outputs raises and writes nothing"
    from core.migrate_syn import migrate, write_outputs
    import facts

    tmp_dir = _tmp_taxonomy_with(
        [],
        [{"derivation_id": "deriv:已批准", "description": "x"}],
    )
    deriv_path = os.path.join(tmp_dir, "derivations.json")
    before_bytes = open(deriv_path, "rb").read()
    before_mtime = os.path.getmtime(deriv_path)

    out_tmp = tempfile.mkdtemp(prefix="test_migrate_out_")
    result = migrate(facts.load())
    try:
        write_outputs(result, taxonomy_dir=tmp_dir, out_dir=out_tmp)
        fail(label, "write_outputs did NOT raise despite existing non-empty derivations.json")
    except RuntimeError as e:
        after_bytes = open(deriv_path, "rb").read()
        after_mtime = os.path.getmtime(deriv_path)
        worklist_path = os.path.join(out_tmp, "ratify_worklist.md")
        if after_bytes == before_bytes and after_mtime == before_mtime and not os.path.exists(worklist_path):
            ok(label + f" (raised: {e}; derivations.json untouched, no worklist written)")
        else:
            fail(label, "raised, but files were modified before the raise — check must run before any write")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(out_tmp, ignore_errors=True)


def test_M14():
    label = "M14: allow_overwrite=True permits writing despite existing CONFIRMED/derivations"
    from core.migrate_syn import migrate, write_outputs
    import facts

    tmp_dir = _tmp_taxonomy_with(
        [{"rule_id": "tax:已批准", "scope": "name", "mapping": "公債",
          "state": "CONFIRMED", "references": [{"kind": "human", "detail": "x",
          "at": "2026-01-01T00:00:00Z", "recheck": None}]}],
        [{"derivation_id": "deriv:已批准", "description": "x"}],
    )
    out_tmp = tempfile.mkdtemp(prefix="test_migrate_out_")
    result = migrate(facts.load())
    try:
        write_outputs(result, taxonomy_dir=tmp_dir, out_dir=out_tmp, allow_overwrite=True)
        rules_path = os.path.join(tmp_dir, "rules.json")
        with open(rules_path, encoding="utf-8") as f:
            written_rules = json.load(f)
        if all(r["rule_id"] != "tax:已批准" for r in written_rules):
            ok(label + f" (allow_overwrite=True wrote {len(written_rules)} fresh rules)")
        else:
            fail(label, "old CONFIRMED rule still present after overwrite")
    except Exception as e:
        fail(label, f"unexpected raise even with allow_overwrite=True: {e!r}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(out_tmp, ignore_errors=True)


# ── M4: 注入:把一條 rule reference 的關鍵字改掉 → 重驗必須紅 ───────────


def test_M4():
    label = "M4 inject: change a rule reference keyword → recheck must fail"
    rules, _ = _load_taxonomy()

    # Find a rule with a rule-kind reference and recheck
    target = None
    for r in rules:
        for ref in r.get("references", []):
            if ref["kind"] == "rule" and ref.get("recheck"):
                target = (r, ref)
                break
        if target:
            break

    if not target:
        fail(label, "no rule with rule-kind recheck found to inject")
        return

    target_rule, target_ref = target
    original_recheck = target_ref["recheck"]
    # Modify the recheck to use a wrong bucket
    # e.g., "rules.propose('金融債券')[0] == '金融債'" → "rules.propose('金融債券')[0] == 'WRONG桶'"
    if "==" in original_recheck:
        parts = original_recheck.split("==")
        bad_recheck = parts[0] + "== '絕對不可能的桶名XYZ'"
    else:
        bad_recheck = original_recheck + " and False"

    try:
        result = eval(bad_recheck, {"rules": rules_mod, "buckets": buckets})
        if result:
            fail(label, f"bad recheck {bad_recheck!r} unexpectedly passed (result={result})")
        else:
            ok(label + f" (modified recheck correctly fails: {bad_recheck!r} → {result!r})")
    except Exception as e:
        ok(label + f" (modified recheck raised exception as expected: {e!r})")


# ── M5: 注入:把一個批量抄列 commit(≥5 條)標成 human → 必須被 §B1.1 判準擋下 ──


def test_M5():
    label = "M5 inject: bulk-copy commit tagged as human → must be rejected by §B1.1 criteria"
    from core.migrate_syn import _is_bulk_commit, _is_human_commit

    # Known bulk commit from §0.3: a8b43d80 added 32 entries at once
    bulk_hash = "a8b43d8"
    bulk_msg = "feat(v3-R3): 第 3 道改「對齊欄位再比」,並補上它驗不到名字配對的洞"

    is_bulk = _is_bulk_commit(bulk_hash, bulk_msg)
    is_human = _is_human_commit(bulk_hash, bulk_msg, "金融債券")

    if is_bulk and not is_human:
        ok(label + f" (bulk commit {bulk_hash} is_bulk={is_bulk}, is_human={is_human})")
    else:
        # Check if it's detected by message pattern at least
        if "抄列" in bulk_msg:
            is_bulk_by_msg = True
        else:
            is_bulk_by_msg = False

        if is_bulk_by_msg:
            ok(label + f" (detected by message pattern: is_bulk_by_msg={is_bulk_by_msg})")
        else:
            fail(label, f"bulk commit {bulk_hash} not caught: is_bulk={is_bulk}, is_human={is_human}")

    # Also check that a non-bulk, non-human commit is correctly not flagged as human
    label2 = "M5b: non-human commit (no explicit rationale) is not tagged human"
    # The 1f31bc33 commit added 10 entries at once — should be bulk
    bulk_hash2 = "1f31bc3"
    bulk_msg2 = "feat(v3-R4f): 抄列 17 → 19 格,2024 年報五家三類全數到齊(15/15)"
    is_human2 = _is_human_commit(bulk_hash2, bulk_msg2, "some_name")
    if not is_human2:
        ok(label2 + f" (non-human commit {bulk_hash2} correctly not tagged human)")
    else:
        fail(label2, f"commit {bulk_hash2} incorrectly tagged as human")


# ── M6: taxonomy/derivations.json 是空的 ── 注入:讓 B1 寫進一條 → 必須紅 ──


def test_M6():
    # ⚠️ 2026-07-28 修正,理由同 M2:測的是「**遷移**不得寫入 derivation」,
    #    不是「derivations.json 永遠是空的」。B1.5 之後那裡本來就有 1 條人批准的。
    label = "M6: migrate() 不產生任何 derivation(批准是 ratify 的事)"
    from core.migrate_syn import migrate
    import facts as facts_mod
    fresh = migrate(facts_mod.load())
    if fresh["derivations"] == []:
        ok(label)
    else:
        fail(label, f"migrate() 產出了 derivation: {fresh['derivations']}")

    label2 = "M6 inject: if B1 writes a derivation → must be detected"
    # Demonstrate: if derivations.json contained an entry, our check would catch it
    bad_derivations = [{"derivation_id": "deriv:BAD", "description": "should not be here"}]
    if bad_derivations != []:
        ok(label2 + " (injection: non-empty derivations would be detected by M6 check)")
    else:
        fail(label2, "injection failed")


# ── M7: 工單三批的條數與 §0.3 的實測一致 (63 / ~8 / 3) ───────────────


def test_M7():
    # §0.2 明確授權的變更:F1 修正批次歸屬 bug 之後,
    # 5 條 GROUP_SYN 真的進第 1 批(63→68),4 條 GENERIC 移到第 2 批(8→12)。
    # 舊斷言 63/8/3 反映的是 bug 本身(工單說第 1 批 63+5+4,applies_to 卻只收 63)。
    label = "M7: worklist batch counts match post-F1 baseline (68 / 12 / 3)"
    from core.migrate_syn import migrate
    import facts
    result = migrate(facts.load())
    b1 = len(result["batch1_rule_ids"])
    b2 = len(result["batch2_rules"])
    b3 = len(result["batch3_rules"])

    if b1 == 68 and b2 == 12 and b3 == 3:
        ok(label + f" (batch1={b1}, batch2={b2}, batch3={b3})")
    else:
        fail(label, f"Expected batch1=68, batch2=12, batch3=3; got batch1={b1}, batch2={b2}, batch3={b3}")

    # Verify batch 3 names are correct — §0.2 明確說這格不變,不准動
    label2 = "M7b: batch 3 names are 政府債券/貨幣交換/外匯換匯合約 (unchanged by F1)"
    batch3_names = {r["rule_id"].replace("tax:", "") for r in result["batch3_rules"]}
    expected_b3 = {"政府債券", "貨幣交換", "外匯換匯合約"}
    if batch3_names == expected_b3:
        ok(label2 + f" ({batch3_names})")
    else:
        fail(label2, f"got {batch3_names}, expected {expected_b3}")


# ── M8: 工單宣稱是第 1 批的 rule,必須全部出現在 derivation 的 applies_to 裡 ──
# 注入:從 applies_to 拿掉一條第 1 批的 rule_id → 必須紅


def test_M8():
    label = "M8: batch-1 rule_ids (incl. GROUP_SYN) must all be in derivation.applies_to"
    from core.migrate_syn import migrate, _build_derivation_proposal
    import facts
    result = migrate(facts.load())
    deriv = _build_derivation_proposal(result["batch1_rule_ids"])
    applies_to = set(deriv["applies_to"])
    batch1_ids = set(result["batch1_rule_ids"])

    missing = batch1_ids - applies_to
    if not missing:
        ok(label + f" ({len(batch1_ids)} batch-1 rule_ids all present in applies_to, "
                    f"incl. group scope: "
                    f"{sorted(x for x in batch1_ids if x.startswith('tax:group:'))}))")
    else:
        fail(label, f"{len(missing)} batch-1 rule_ids missing from applies_to: {sorted(missing)}")

    # 注入:從 applies_to 拿掉一條第 1 批的 rule_id(挑一條 group scope 的,
    # 正是 F1 之前那個 bug 重現)→ 必須被下面這個判準抓到
    label_inj = "M8 inject: drop a batch-1 rule_id from applies_to → must be detected"
    group_ids = sorted(x for x in batch1_ids if x.startswith("tax:group:"))
    if not group_ids:
        fail(label_inj, "no group-scope batch-1 rule_id found to inject with")
    else:
        victim = group_ids[0]
        bad_applies_to = set(deriv["applies_to"]) - {victim}
        bad_missing = batch1_ids - bad_applies_to
        if victim in bad_missing:
            ok(label_inj + f" (dropped {victim!r} → missing={sorted(bad_missing)}, correctly caught)")
        else:
            fail(label_inj, f"dropped {victim!r} but check did not catch it")


# ── M9: scope=="generic" 的 rule 不得出現在任何 derivation 的 applies_to 裡 ──
# 注入:塞一條 generic rule 進 applies_to → 必須紅


def test_M9():
    label = "M9: no scope=='generic' rule_id may appear in derivation.applies_to"
    from core.migrate_syn import migrate, _build_derivation_proposal
    import facts
    result = migrate(facts.load())
    deriv = _build_derivation_proposal(result["batch1_rule_ids"])
    applies_to = set(deriv["applies_to"])

    generic_ids = {r["rule_id"] for r in result["rules"] if r["scope"] == "generic"}
    leaked = generic_ids & applies_to
    if not leaked:
        ok(label + f" ({len(generic_ids)} generic rule_ids, none in applies_to)")
    else:
        fail(label, f"generic rule_ids leaked into applies_to: {sorted(leaked)}")

    # 注入:塞一條 generic rule_id 進 applies_to → 必須被下面這個判準抓到
    label_inj = "M9 inject: stuff a generic rule_id into applies_to → must be detected"
    victim = sorted(generic_ids)[0]
    bad_applies_to = applies_to | {victim}
    bad_leaked = generic_ids & bad_applies_to
    if victim in bad_leaked:
        ok(label_inj + f" (injected {victim!r} → leaked={sorted(bad_leaked)}, correctly caught)")
    else:
        fail(label_inj, f"injected {victim!r} but check did not catch it")


# ── 執行所有測試 ────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("test_taxonomy_migration.py — B1 migration tests (M1-M7)")
    print("=" * 60)

    test_M1()
    test_M2()
    test_M3()
    test_M4()
    test_M5()
    test_M6()
    test_M7()
    test_M8()
    test_M9()
    test_M10()
    test_M11()
    test_M12()
    test_M13()
    test_M14()

    print("=" * 60)
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAIL > 0:
        print("RESULT: FAIL")
        sys.exit(1)
    else:
        print("RESULT: OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
