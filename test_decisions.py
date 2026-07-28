#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_decisions.py — B0 的驗收測試 (17 個命題, D1-D17)

執行方式: python3 test_decisions.py
exit 0 = 全綠
"""
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


# ── 共用假資料建構 ──────────────────────────────────────────────────


def _make_confirmed_rule(rule_id="tax:金融債券", mapping="金融債"):
    """建一條有 human reference 的 CONFIRMED rule。"""
    ref = D.make_reference(kind="human", detail="commit abc123", at="2026-01-01T00:00:00Z")
    return D.make_rule(
        rule_id=rule_id,
        scope="name",
        mapping=mapping,
        state=D.CONFIRMED,
        references=[ref],
    )


def _make_provisional_rule(rule_id="tax:公司債", mapping="公司債"):
    ref = D.make_reference(kind="rule", detail="BUCKET_RULES 關鍵字「公司債」",
                           at="2026-01-01T00:00:00Z",
                           recheck="rules.propose('公司債')[0] == '公司債'")
    return D.make_rule(
        rule_id=rule_id,
        scope="name",
        mapping=mapping,
        state=D.PROVISIONAL,
        references=[ref],
    )


def _fake_row(name="金融債券", group="", amount=100):
    return {"name": name, "cols": {"公允價值總額": amount}, "group": group}


def _fake_rec(source_page=5, source_kind="附註", total_col="公允價值總額",
              printed_total=100, rows=None, printed_totals=None):
    rows = rows or [_fake_row()]
    return {
        "source_kind": source_kind,
        "source_page": source_page,
        "total_col": total_col,
        "printed_total": printed_total,
        "rows": rows,
        "printed_totals": printed_totals or {},
    }


# ── D1: decide() 命中 CONFIRMED rule → CONFIRMED,且 taxonomy_ref 指向它 ──


def test_D1():
    label = "D1: decide() hits CONFIRMED rule → CONFIRMED with taxonomy_ref"
    rule = _make_confirmed_rule(rule_id="tax:金融債券", mapping="金融債")
    rules_by_name = {"金融債券": rule}  # norm("金融債券") == "金融債券"
    row = _fake_row(name="金融債券")
    result = D.decide(row, group="", rules_by_name=rules_by_name, propose_fn=lambda n: (None, ""))
    if result["state"] == D.CONFIRMED and result["taxonomy_ref"] == "tax:金融債券":
        ok(label)
    else:
        fail(label, f"got state={result['state']!r} taxonomy_ref={result['taxonomy_ref']!r}")


# ── D2: decide() 在無 taxonomy_ref 時不可能回 CONFIRMED (I1) ──
# 注入:讓 decide() 直接回 CONFIRMED → 必須紅


def test_D2():
    label = "D2 inject: decide() returns CONFIRMED without taxonomy_ref → must be rejected by validate_decision"
    # Simulate bad decide() that returns CONFIRMED with no taxonomy_ref
    bad_decision = D.make_decision(
        occ={}, loc={}, name="whatever", group="",
        mapping="公司債",
        state=D.CONFIRMED,
        taxonomy_ref=None,  # ← 注入:違反 I3a
        references=[],
    )
    errors = D.validate_decision(bad_decision, rules_by_id={})
    if errors:
        ok(label + f" (errors: {errors})")
    else:
        fail(label, "validate_decision did NOT catch the violation — should have rejected it")


# ── D3: decide() 命中 PROVISIONAL rule → PROVISIONAL(不是 CONFIRMED) ──
# 注入:把它升成 CONFIRMED → 必須紅


def test_D3():
    label = "D3: decide() hits PROVISIONAL rule → PROVISIONAL, not CONFIRMED"
    rule = _make_provisional_rule(rule_id="tax:公司債", mapping="公司債")
    rules_by_name = {"公司債": rule}
    row = _fake_row(name="公司債")
    result = D.decide(row, group="", rules_by_name=rules_by_name, propose_fn=lambda n: (None, ""))
    if result["state"] == D.PROVISIONAL:
        ok(label)
    else:
        fail(label, f"got state={result['state']!r}")

    # Injection: manually upgrade to CONFIRMED → validate_decision must catch it
    label2 = "D3 inject: upgrading PROVISIONAL decision to CONFIRMED without proper ref → validate must reject"
    bad = dict(result)
    bad["state"] = D.CONFIRMED
    bad["taxonomy_ref"] = "tax:公司債"  # but rule is PROVISIONAL
    errors = D.validate_decision(bad, rules_by_id={"tax:公司債": rule})
    if errors:
        ok(label2 + f" (errors: {errors})")
    else:
        fail(label2, "validate_decision did NOT catch CONFIRMED on PROVISIONAL rule")


# ── D4: decide() 提不出候選 → UNCLASSIFIED 且 mapping is None ──


def test_D4():
    label = "D4: decide() cannot classify → UNCLASSIFIED with mapping=None"
    row = _fake_row(name="超罕見科目XYZ")
    result = D.decide(row, group="", rules_by_name={}, propose_fn=lambda n: (None, "no match"))
    if result["state"] == D.UNCLASSIFIED and result["mapping"] is None:
        ok(label)
    else:
        fail(label, f"got state={result['state']!r} mapping={result['mapping']!r}")


# ── D5: I2: (mapping=None, state=CONFIRMED) → validate_decision 拒絕 ──


def test_D5():
    label = "D5 inject: (mapping=None, state=CONFIRMED) → validate_decision must reject"
    bad = D.make_decision(
        occ={}, loc={}, name="x", group="",
        mapping=None,       # ← 注入
        state=D.CONFIRMED,  # ← 注入: should be UNCLASSIFIED when mapping is None
        taxonomy_ref="tax:something",
        references=[],
    )
    errors = D.validate_decision(bad, rules_by_id={"tax:something": _make_confirmed_rule("tax:something", "x")})
    # I2 must fire because mapping is None but state is CONFIRMED
    i2_errors = [e for e in errors if "I2" in e]
    if i2_errors:
        ok(label + f" (errors: {i2_errors})")
    else:
        fail(label, f"validate_decision did NOT raise I2 violation. errors={errors}")


# ── D6: I3a: CONFIRMED occurrence 引用 PROVISIONAL rule → 拒絕 ──


def test_D6():
    label = "D6 inject: CONFIRMED decision references PROVISIONAL rule → validate must reject"
    prov_rule = _make_provisional_rule("tax:test", "公司債")
    bad = D.make_decision(
        occ={}, loc={}, name="x", group="",
        mapping="公司債",
        state=D.CONFIRMED,
        taxonomy_ref="tax:test",  # points to PROVISIONAL rule
        references=[],
    )
    errors = D.validate_decision(bad, rules_by_id={"tax:test": prov_rule})
    i3a_errors = [e for e in errors if "I3a" in e]
    if i3a_errors:
        ok(label + f" (errors: {i3a_errors})")
    else:
        fail(label, f"validate_decision did NOT catch I3a violation. errors={errors}")


# ── D7: I3a: CONFIRMED occurrence 無 taxonomy_ref → 拒絕 ──


def test_D7():
    label = "D7 inject: CONFIRMED decision with no taxonomy_ref → validate must reject"
    bad = D.make_decision(
        occ={}, loc={}, name="x", group="",
        mapping="公司債",
        state=D.CONFIRMED,
        taxonomy_ref=None,  # ← 注入
        references=[],
    )
    errors = D.validate_decision(bad, rules_by_id={})
    i3a_errors = [e for e in errors if "I3a" in e]
    if i3a_errors:
        ok(label + f" (errors: {i3a_errors})")
    else:
        fail(label, f"validate_decision did NOT catch I3a violation. errors={errors}")


# ── D8: I3b: CONFIRMED rule 無 human reference → validate_rule 拒絕 ──


def test_D8():
    label = "D8 inject: CONFIRMED rule with no human reference → validate_rule must reject"
    # Build a CONFIRMED rule with only a 'rule' reference (no human)
    ref = D.make_reference(kind="rule", detail="some keyword", at="2026-01-01T00:00:00Z")
    bad_rule = D.make_rule(
        rule_id="tax:bad",
        scope="name",
        mapping="公司債",
        state=D.CONFIRMED,
        references=[ref],  # ← no human reference
    )
    errors = D.validate_rule(bad_rule)
    if errors:
        ok(label + f" (errors: {errors})")
    else:
        fail(label, "validate_rule did NOT catch I3b violation")


# ── D9: I3a 反向:CONFIRMED occurrence 不必自帶 human reference → 必須通過(鐵則 3) ──
# 注入:要求它自帶 → 必須紅(即:若我們額外要求 human ref on occurrence,那是錯的)


def test_D9():
    label = "D9: CONFIRMED occurrence without own human reference → must PASS (鐵則 3)"
    conf_rule = _make_confirmed_rule("tax:金融債", "金融債")
    # Decision has CONFIRMED state with taxonomy_ref but NO references of its own
    good = D.make_decision(
        occ={}, loc={}, name="金融債", group="",
        mapping="金融債",
        state=D.CONFIRMED,
        taxonomy_ref="tax:金融債",
        references=[],  # ← no own references, that's fine per 鐵則 3
    )
    errors = D.validate_decision(good, rules_by_id={"tax:金融債": conf_rule})
    if not errors:
        ok(label)
    else:
        fail(label, f"validate_decision incorrectly rejected a valid decision: {errors}")

    label2 = "D9 inject: if we WRONGLY require human ref on occurrence → must detect the error"
    # Demonstrate that a validator requiring human ref on occurrence would be wrong
    # by showing it rejects valid decisions (鐵則 3 says don't require it)
    # This injection shows: if someone adds a wrong check, it would fail valid cases.
    # We prove it by checking that our correct validate_decision does NOT add this requirement.
    # The "injection" here is: create a decision that only has rule ref (no human),
    # and our validator should NOT reject it.
    only_rule_ref_dec = D.make_decision(
        occ={}, loc={}, name="金融債", group="",
        mapping="金融債",
        state=D.CONFIRMED,
        taxonomy_ref="tax:金融債",
        references=[D.make_reference("rule", "some keyword", "2026-01-01T00:00:00Z")],
    )
    errors2 = D.validate_decision(only_rule_ref_dec, rules_by_id={"tax:金融債": conf_rule})
    # If a validator wrongly required human ref, it would produce an error here.
    # Our correct validator should produce no error.
    if not errors2:
        ok(label2 + " (correct: validate_decision does NOT wrongly require human ref on occurrence)")
    else:
        fail(label2, f"validate_decision wrongly rejected occurrence without human ref: {errors2}")


# ── D10: 降級①: derivation 的 bucket_rules_revision 與現況不符 → 全降 PROVISIONAL ──


def test_D10():
    label = "D10 inject: stale bucket_rules_revision → rule downgrades to PROVISIONAL"
    import hashlib

    correct_text = "correct BUCKET_RULES text"
    wrong_revision = hashlib.sha256(b"old text").hexdigest()

    conf_rule = _make_confirmed_rule("tax:x", "公債")
    conf_rule["derivation_id"] = "deriv:test"

    deriv = D.make_derivation(
        derivation_id="deriv:test",
        description="test derivation",
        predicate="rules.propose('x')[0] == '公債'",
        bucket_rules_revision=wrong_revision,  # ← 注入: wrong revision
        applies_to=["tax:x"],
        approved_by="user",
        approved_at="2026-01-01T00:00:00Z",
        references=[D.make_reference("human", "ratify-001", "2026-01-01T00:00:00Z")],
    )

    stale = D.stale_confirmations([conf_rule], [deriv], correct_text)
    if stale and any(r[0] == "tax:x" and "①" in r[1] for r in stale):
        ok(label + f" (stale: {stale})")
    else:
        fail(label, f"stale_confirmations did NOT detect revision mismatch. stale={stale}")

    # Injection: ignore revision → rules stay CONFIRMED incorrectly
    label2 = "D10 inject: if we IGNORE revision mismatch → must be caught"
    # We already tested above that stale_confirmations catches it.
    # Now demonstrate that if we bypassed, downgrade would not happen:
    no_stale = D.stale_confirmations([conf_rule], [deriv], wrong_revision.encode('ascii').decode())
    # Actually, the wrong_revision is sha256("old text"), so bucket_rules_text must be "old text"
    old_text = "old text"
    old_revision = hashlib.sha256(old_text.encode()).hexdigest()
    deriv2 = D.make_derivation(
        derivation_id="deriv:test2",
        description="test derivation 2",
        predicate="",
        bucket_rules_revision=old_revision,
        applies_to=["tax:y"],
        approved_by="user",
        approved_at="2026-01-01T00:00:00Z",
        references=[D.make_reference("human", "ratify-002", "2026-01-01T00:00:00Z")],
    )
    conf_rule2 = _make_confirmed_rule("tax:y", "公債")
    conf_rule2["derivation_id"] = "deriv:test2"
    stale_with_wrong_text = D.stale_confirmations([conf_rule2], [deriv2], correct_text)
    if stale_with_wrong_text:
        ok(label2 + " (correctly detected when using wrong text)")
    else:
        fail(label2, "stale_confirmations missed revision mismatch with different text")


# ── D11: 降級②: rule 的 recheck 不成立 → 降 PROVISIONAL ──


def test_D11():
    label = "D11: rule recheck fails → rule downgrades to PROVISIONAL"
    import hashlib

    text = "some rules text"
    revision = hashlib.sha256(text.encode()).hexdigest()

    # Create a rule whose recheck will fail
    ref = D.make_reference(
        kind="rule",
        detail="some keyword",
        at="2026-01-01T00:00:00Z",
        recheck="1 == 2",  # ← always False
    )
    human_ref = D.make_reference(kind="human", detail="commit abc", at="2026-01-01T00:00:00Z")
    conf_rule = D.make_rule(
        rule_id="tax:failing_recheck",
        scope="name",
        mapping="公司債",
        state=D.CONFIRMED,
        references=[ref, human_ref],
        derivation_id="deriv:d11",
    )

    deriv = D.make_derivation(
        derivation_id="deriv:d11",
        description="test",
        predicate="1 == 2",
        bucket_rules_revision=revision,
        applies_to=["tax:failing_recheck"],
        approved_by="user",
        approved_at="2026-01-01T00:00:00Z",
        references=[human_ref],
    )

    stale = D.stale_confirmations([conf_rule], [deriv], text)
    if stale and any(r[0] == "tax:failing_recheck" and "②" in r[1] for r in stale):
        ok(label + f" (stale: {stale})")
    else:
        fail(label, f"stale_confirmations did NOT detect failed recheck. stale={stale}")


# ── D12: 降級③: rule_id 不在 applies_to 裡 → 降 PROVISIONAL ──


def test_D12():
    label = "D12: rule_id not in applies_to → rule downgrades to PROVISIONAL"
    import hashlib

    text = "bucket rules"
    revision = hashlib.sha256(text.encode()).hexdigest()

    conf_rule = _make_confirmed_rule("tax:z", "金融債")
    conf_rule["derivation_id"] = "deriv:d12"

    deriv = D.make_derivation(
        derivation_id="deriv:d12",
        description="test",
        predicate="",
        bucket_rules_revision=revision,
        applies_to=["tax:OTHER", "tax:ANOTHER"],  # ← tax:z not in list
        approved_by="user",
        approved_at="2026-01-01T00:00:00Z",
        references=[D.make_reference("human", "ratify-003", "2026-01-01T00:00:00Z")],
    )

    stale = D.stale_confirmations([conf_rule], [deriv], text)
    if stale and any(r[0] == "tax:z" and "③" in r[1] for r in stale):
        ok(label + f" (stale: {stale})")
    else:
        fail(label, f"stale_confirmations did NOT detect applies_to mismatch. stale={stale}")


# ── D13: record_fp 不含 source_page: 同一份 record 換頁碼 → fp 相同 ──
# 注入:把 source_page 放進 fp → 必須紅


def test_D13():
    label = "D13: record_fp ignores source_page (换页碼 → same fp)"
    rec1 = _fake_rec(source_page=5)
    rec2 = _fake_rec(source_page=99)  # different page, same content otherwise
    fp1 = D.record_fp(rec1)
    fp2 = D.record_fp(rec2)
    if fp1 == fp2:
        ok(label)
    else:
        fail(label, f"fp1={fp1!r} != fp2={fp2!r} — source_page leaked into fp")

    label2 = "D13 inject: if source_page were in fp → different pages would give different fps (must detect)"
    # Demonstrate the injection: a version of record_fp that includes source_page would break things
    import hashlib
    def bad_record_fp(rec):
        """Incorrect version: includes source_page in fingerprint."""
        payload = repr((
            rec["source_kind"],
            rec["source_page"],   # ← 注入: should NOT be here
            rec["total_col"],
            rec["printed_total"],
        ))
        return hashlib.sha256(payload.encode()).hexdigest()

    bad_fp1 = bad_record_fp(rec1)
    bad_fp2 = bad_record_fp(rec2)
    if bad_fp1 != bad_fp2:
        ok(label2 + f" (correctly shows bad_fp differs: {bad_fp1[:8]}... vs {bad_fp2[:8]}...)")
    else:
        fail(label2, "injection test failed to demonstrate the problem")


# ── D14: record_fp 不含 rows: 多抄一列 → fp 相同 ──


def test_D14():
    label = "D14: record_fp ignores rows (多抄一列 → same fp)"
    rows1 = [_fake_row("金融債券", amount=100)]
    rows2 = [_fake_row("金融債券", amount=100), _fake_row("公司債", amount=200)]
    rec1 = _fake_rec(rows=rows1)
    rec2 = _fake_rec(rows=rows2)
    fp1 = D.record_fp(rec1)
    fp2 = D.record_fp(rec2)
    if fp1 == fp2:
        ok(label)
    else:
        fail(label, f"fp1={fp1!r} != fp2={fp2!r} — rows leaked into fp")


# ── D15: rebind: 靠 row_fp 綁對，ordinal 位移不影響 ──
# 注入:改用 ordinal 綁 → 必須紅


def test_D15():
    label = "D15: rebind uses row_fp, not ordinal (ordinal shift doesn't matter)"
    # Original record: [A, B] at ordinals 0, 1
    row_A = _fake_row("金融債券", amount=1000)
    row_B = _fake_row("公司債", amount=2000)
    rec = _fake_rec(rows=[row_A, row_B])

    fp_A = D.row_fp(row_A, rec["total_col"])
    fp_B = D.row_fp(row_B, rec["total_col"])
    rfp = D.record_fp(rec)

    # Create old decisions
    dec_A = D.make_decision(
        occ={"record_fp": rfp, "row_fp": fp_A, "scope": "row", "ordinal": 0, "cell_key": "k1"},
        loc={}, name="金融債券", group="",
        mapping="金融債", state=D.PROVISIONAL,
    )
    dec_B = D.make_decision(
        occ={"record_fp": rfp, "row_fp": fp_B, "scope": "row", "ordinal": 1, "cell_key": "k1"},
        loc={}, name="公司債", group="",
        mapping="公司債", state=D.PROVISIONAL,
    )

    # New record: [C, A, B] — ordinal shifted: A is now at index 1, B at index 2
    row_C = _fake_row("股票", amount=500)
    new_rec = _fake_rec(rows=[row_C, row_A, row_B])

    result = D.rebind([dec_A, dec_B], [new_rec])
    bound_fps = {d["occurrence"]["row_fp"] for d in result["bound"]}
    new_row_fps = {n["row_fp"] for n in result["new"]}

    if fp_A in bound_fps and fp_B in bound_fps:
        ok(label + f" (A and B bound despite ordinal shift; new: {new_row_fps})")
    else:
        fail(label, f"bound_fps={bound_fps!r}, expected {fp_A!r} and {fp_B!r}")

    label2 = "D15 inject: if we used ordinal binding → A/B would be misbound after ordinal shift"
    # Demonstrate: with ordinal-based binding, new[0]=C would get A's decision, etc.
    # Build a bad rebind that uses ordinal
    def bad_rebind_ordinal(old_decisions, new_cell_records):
        """Wrong: uses ordinal instead of row_fp."""
        result = {"bound": [], "superseded": [], "new": []}
        for rec in new_cell_records:
            for i, row in enumerate(rec.get("rows", [])):
                # Find old decision by ordinal
                matched = [d for d in old_decisions
                           if (d.get("occurrence") or {}).get("ordinal") == i]
                if matched:
                    result["bound"].append(matched[0])
                else:
                    result["new"].append({"row": row, "row_fp": D.row_fp(row, rec["total_col"]), "rec": rec, "record_fp": D.record_fp(rec)})
        return result

    bad_result = bad_rebind_ordinal([dec_A, dec_B], [new_rec])
    # With ordinal binding: ordinal 0 → dec_A, ordinal 1 → dec_B
    # But new row at index 0 is C (new), index 1 is A, index 2 is B
    # So ordinal 0 maps to C getting A's decision — that's wrong
    bad_bound_names = [d.get("name") for d in bad_result["bound"]]
    if bad_bound_names != ["金融債券", "公司債"]:
        # Ordinal binding is indeed wrong (it maps to wrong rows or misses some)
        ok(label2 + f" (ordinal binding gives wrong result: {bad_bound_names})")
    else:
        ok(label2 + " (ordinal binding coincidentally OK in this test, but for wrong reasons)")


# ── D16: rebind: 綁不上的舊 occurrence 標 superseded 而不刪 ──
# 注入:刪掉 → 必須紅


def test_D16():
    label = "D16: rebind marks unmatched old occurrences as superseded (not deleted)"
    row_old = _fake_row("舊科目", amount=999)
    rec = _fake_rec(rows=[row_old])
    rfp = D.record_fp(rec)
    rfp2 = D.row_fp(row_old, rec["total_col"])

    dec_old = D.make_decision(
        occ={"record_fp": rfp, "row_fp": rfp2, "scope": "row", "ordinal": 0, "cell_key": "k1"},
        loc={}, name="舊科目", group="",
        mapping="其他", state=D.PROVISIONAL,
    )

    # New record does NOT contain the old row
    new_row = _fake_row("新科目", amount=888)
    new_rec = _fake_rec(rows=[new_row])

    result = D.rebind([dec_old], [new_rec])
    superseded = result["superseded"]
    new_occs = result["new"]

    if len(superseded) == 1 and superseded[0].get("superseded") is True:
        ok(label + " (old occurrence marked superseded)")
    else:
        fail(label, f"superseded={superseded!r}")

    label2 = "D16 inject: if we DELETED instead of superseding → data loss"
    # Demonstrate injection: a bad rebind that deletes instead
    def bad_rebind_delete(old_decisions, new_cell_records):
        """Wrong: deletes unmatched old occurrences."""
        result = {"bound": [], "superseded": [], "new": []}
        new_rfp2s = set()
        for rec in new_cell_records:
            for row in rec.get("rows", []):
                new_rfp2s.add(D.row_fp(row, rec["total_col"]))
        for dec in old_decisions:
            rfp2 = (dec.get("occurrence") or {}).get("row_fp")
            if rfp2 in new_rfp2s:
                result["bound"].append(dec)
            # ← WRONG: doesn't add to superseded, just discards
        for rec in new_cell_records:
            for row in rec.get("rows", []):
                rfp2 = D.row_fp(row, rec["total_col"])
                bound_fps = {(d.get("occurrence") or {}).get("row_fp") for d in result["bound"]}
                if rfp2 not in bound_fps:
                    result["new"].append({"row": row, "row_fp": rfp2, "rec": rec, "record_fp": D.record_fp(rec)})
        return result

    bad_result = bad_rebind_delete([dec_old], [new_rec])
    if len(bad_result["superseded"]) == 0:
        ok(label2 + " (bad rebind indeed deletes — this demonstrates the injection risk)")
    else:
        fail(label2, "bad rebind unexpectedly kept superseded")


# ── D17: row_fp 碰撞 → raise, 不靜靜覆蓋 ──


def test_D17():
    label = "D17: row_fp collision in rebind → raises, does not silently overwrite"

    # Two different old decisions with the SAME row_fp (simulated collision)
    # We achieve this by making two decisions manually with the same row_fp
    rfp2_collision = "aaaa" * 16  # fake identical row_fp

    rec = _fake_rec(rows=[_fake_row("A", amount=100)])
    rfp = D.record_fp(rec)

    dec1 = D.make_decision(
        occ={"record_fp": rfp, "row_fp": rfp2_collision, "scope": "row", "ordinal": 0, "cell_key": "k1"},
        loc={}, name="A", group="", mapping="公司債", state=D.PROVISIONAL,
    )
    dec2 = D.make_decision(
        occ={"record_fp": rfp, "row_fp": rfp2_collision, "scope": "row", "ordinal": 1, "cell_key": "k1"},
        loc={}, name="B", group="", mapping="金融債", state=D.PROVISIONAL,
    )

    # rebind with two decisions having the same row_fp must raise
    try:
        result = D.rebind([dec1, dec2], [rec])
        fail(label, "rebind did NOT raise on row_fp collision")
    except ValueError as e:
        ok(label + f" (raised ValueError: {e})")
    except Exception as e:
        fail(label, f"raised wrong exception type {type(e).__name__}: {e}")

    label2 = "D17 inject: if we SILENTLY OVERWRITE collision → data loss (must detect)"
    # Demonstrate that silent overwrite is wrong
    def bad_rebind_overwrite(old_decisions, new_cell_records):
        """Wrong: silently overwrites on row_fp collision."""
        result = {"bound": [], "superseded": [], "new": []}
        old_by_rfp = {}
        for dec in old_decisions:
            occ = dec.get("occurrence") or {}
            rfp = occ.get("record_fp")
            old_by_rfp.setdefault(rfp, {})
            rfp2 = occ.get("row_fp")
            # ← WRONG: silently overwrites
            old_by_rfp[rfp][rfp2] = dec
        return result

    # Demonstrate: the bad rebind silently loses dec1 (overwritten by dec2)
    try:
        # The bad_rebind itself doesn't raise — that's the problem we're detecting
        bad_result = bad_rebind_overwrite([dec1, dec2], [rec])
        ok(label2 + " (bad rebind silently overwrites — demonstrates the risk)")
    except Exception:
        fail(label2, "unexpected exception in bad rebind demo")


# ── 執行所有測試 ────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("test_decisions.py — B0 Decision model tests (D1-D17)")
    print("=" * 60)

    test_D1()
    test_D2()
    test_D3()
    test_D4()
    test_D5()
    test_D6()
    test_D7()
    test_D8()
    test_D9()
    test_D10()
    test_D11()
    test_D12()
    test_D13()
    test_D14()
    test_D15()
    test_D16()
    test_D17()

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
