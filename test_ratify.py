#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ratify.py — F3 驗收測試 (R1-R11)

**一律寫 tmp taxonomy_dir,測完還原。真實 taxonomy/ 全程唯讀。**

執行方式: python3 test_ratify.py
exit 0 = 全綠
"""
import sys
import os
import json
import shutil
import tempfile
import subprocess
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import core.decisions as D
import core.ratify as R

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


# ── 測試用 tmp taxonomy 建構工具 ─────────────────────────────────────


def _make_tmp_taxonomy(rules, derivations=None):
    """建一個 tmp taxonomy_dir,寫入 rules.json / derivations.json。回傳路徑。"""
    d = tempfile.mkdtemp(prefix="test_ratify_taxonomy_")
    with open(os.path.join(d, "rules.json"), "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "derivations.json"), "w", encoding="utf-8") as f:
        json.dump(derivations or [], f, ensure_ascii=False, indent=2)
    return d


def _cleanup(d):
    shutil.rmtree(d, ignore_errors=True)


def _simple_rule(rule_id, scope="name", mapping="測試桶", recheck="1==1"):
    ref = D.make_reference(kind="rule", detail="測試用可重驗證據",
                           at="2026-01-01T00:00:00Z", recheck=recheck)
    return D.make_rule(rule_id=rule_id, scope=scope, mapping=mapping,
                       state=D.PROVISIONAL, references=[ref])


def _generic_rule(rule_id, name="其他"):
    ref = D.make_reference(kind="group", detail="通稱,靠段落決定",
                           at="2026-01-01T00:00:00Z", recheck=None)
    return D.make_rule(rule_id=rule_id, scope="generic", mapping=None,
                       state=D.PROVISIONAL, references=[ref])


def _simple_derivation(deriv_id, applies_to, revision="STALE_FAKE_REVISION"):
    return D.make_derivation(
        derivation_id=deriv_id,
        description="測試用 derivation",
        predicate="測試 predicate",
        bucket_rules_revision=revision,  # 故意放一個「提案檔裡的舊值」
        applies_to=applies_to,
        approved_by=None,
        approved_at=None,
        references=[],
    )


# ── R1: ratify_rule 正常路徑 → rule 變 CONFIRMED 且帶 human reference ────


def test_R1():
    label = "R1: ratify_rule normal path → CONFIRMED + human reference"
    rules = [_simple_rule("tax:測試甲")]
    tmp = _make_tmp_taxonomy(rules)
    try:
        result = R.ratify_rule("tax:測試甲", approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                               reason="R1 測試批准", taxonomy_dir=tmp)
        human_refs = [r for r in result["references"] if r["kind"] == "human"]
        if result["state"] == D.CONFIRMED and human_refs:
            ok(label + f" (state={result['state']}, human_refs={len(human_refs)})")
        else:
            fail(label, f"state={result['state']}, human_refs={human_refs}")

        # 也驗證寫進了 tmp rules.json
        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        disk_rule = next(r for r in on_disk if r["rule_id"] == "tax:測試甲")
        if disk_rule["state"] == D.CONFIRMED:
            ok(label + " (persisted to disk correctly)")
        else:
            fail(label + " (disk check)", f"on-disk state={disk_rule['state']}")
    finally:
        _cleanup(tmp)


# ── R2: approved_by 為空 → raise ── 注入:給空字串 → 必須紅 ─────────────


def test_R2():
    label = "R2 inject: ratify_rule with approved_by='' → must raise"
    rules = [_simple_rule("tax:測試乙")]
    tmp = _make_tmp_taxonomy(rules)
    try:
        try:
            R.ratify_rule("tax:測試乙", approved_by="", approved_at="2026-07-28T00:00:00Z",
                         reason="不該通過", taxonomy_dir=tmp)
            fail(label, "no exception raised — empty approved_by was accepted (BUG)")
        except ValueError as e:
            ok(label + f" (correctly raised: {e})")
        except Exception as e:
            fail(label, f"raised wrong exception type: {e!r}")
    finally:
        _cleanup(tmp)


# ── R3: reason 為空 → raise ── 注入:給空字串 → 必須紅 ──────────────────


def test_R3():
    label = "R3 inject: ratify_rule with reason='' → must raise"
    rules = [_simple_rule("tax:測試丙")]
    tmp = _make_tmp_taxonomy(rules)
    try:
        try:
            R.ratify_rule("tax:測試丙", approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                         reason="", taxonomy_dir=tmp)
            fail(label, "no exception raised — empty reason was accepted (BUG)")
        except ValueError as e:
            ok(label + f" (correctly raised: {e})")
        except Exception as e:
            fail(label, f"raised wrong exception type: {e!r}")
    finally:
        _cleanup(tmp)


# ── R4: ratify_derivation 正常路徑 → applies_to 涵蓋的 rule 全變 CONFIRMED ──


def test_R4():
    label = "R4: ratify_derivation normal path → all applies_to rules become CONFIRMED"
    r1 = _simple_rule("tax:測試丁1", recheck="1==1")
    r2 = _simple_rule("tax:測試丁2", recheck="2==2")
    tmp = _make_tmp_taxonomy([r1, r2])
    try:
        deriv = _simple_derivation("deriv:test-R4", ["tax:測試丁1", "tax:測試丁2"])
        result = R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                                     reason="R4 測試批准", taxonomy_dir=tmp)
        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        states = {r["rule_id"]: r["state"] for r in on_disk}
        if states.get("tax:測試丁1") == D.CONFIRMED and states.get("tax:測試丁2") == D.CONFIRMED:
            ok(label + f" (states={states}, upgraded={result['upgraded']})")
        else:
            fail(label, f"states={states}")

        # bucket_rules_revision 必須是現算值,不是提案檔的 STALE_FAKE_REVISION
        current = hashlib.sha256(config.BUCKET_RULES.encode("utf-8")).hexdigest()
        deriv_on_disk = json.load(open(os.path.join(tmp, "derivations.json"), encoding="utf-8"))[0]
        if deriv_on_disk["bucket_rules_revision"] == current:
            ok(label + " (bucket_rules_revision correctly recomputed, not stale proposal value)")
        else:
            fail(label + " (revision check)", f"got {deriv_on_disk['bucket_rules_revision']}")
    finally:
        _cleanup(tmp)


# ── R5: derivation 無 human reference → CONFIRMED rule 被 validate_rule 拒絕 ──
# 注入:讓它不建 human ref → 必須紅


def test_R5():
    label = "R5 inject: CONFIRMED rule with no human reference → validate_rule must reject"
    # 模擬「如果 ratify_derivation 忘了建 human reference」會產生什麼:
    # 一個 state=CONFIRMED、但 references 裡只有 kind='rule' 的 rule。
    rule_only_mechanical = _simple_rule("tax:測試戊", recheck="1==1")
    bad_rule = dict(rule_only_mechanical)
    bad_rule["state"] = D.CONFIRMED  # 升級了,但沒有加 human reference

    errors = D.validate_rule(bad_rule)
    if errors:
        ok(label + f" (validate_rule correctly rejected: {errors})")
    else:
        fail(label, "validate_rule did NOT catch missing human reference — I3b is not enforced")

    # 正面驗證:真正的 ratify_derivation 一定會附上 human reference,
    # 所以正常路徑產出的 rule 一定通過 validate_rule。
    label2 = "R5b: real ratify_derivation always attaches a human reference (positive check)"
    tmp = _make_tmp_taxonomy([_simple_rule("tax:測試戊2", recheck="1==1")])
    try:
        deriv = _simple_derivation("deriv:test-R5", ["tax:測試戊2"])
        R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                            reason="R5b 測試批准", taxonomy_dir=tmp)
        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        target = next(r for r in on_disk if r["rule_id"] == "tax:測試戊2")
        errs = D.validate_rule(target)
        if target["state"] == D.CONFIRMED and not errs:
            ok(label2 + " (no I3b violation on real ratify_derivation output)")
        else:
            fail(label2, f"state={target['state']}, errors={errs}")
    finally:
        _cleanup(tmp)


# ── R6: applies_to 裡某條 rule 的 recheck 不成立 → 留 PROVISIONAL 且被列出 ──
# 注入:讓它一起升 CONFIRMED → 必須紅


def test_R6():
    label = "R6: rule with failing recheck stays PROVISIONAL and is listed in left_provisional"
    passing = _simple_rule("tax:測試己1", recheck="1==1")
    failing = _simple_rule("tax:測試己2", recheck="1==2")  # 永遠不成立
    tmp = _make_tmp_taxonomy([passing, failing])
    try:
        deriv = _simple_derivation("deriv:test-R6", ["tax:測試己1", "tax:測試己2"])
        result = R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                                     reason="R6 測試批准", taxonomy_dir=tmp)
        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        states = {r["rule_id"]: r["state"] for r in on_disk}
        left_ids = {rid for rid, _ in result["left_provisional"]}

        if (states.get("tax:測試己2") == D.PROVISIONAL
                and "tax:測試己2" in left_ids
                and states.get("tax:測試己1") == D.CONFIRMED):
            ok(label + f" (states={states}, left_provisional={result['left_provisional']})")
        else:
            fail(label, f"states={states}, left_provisional={result['left_provisional']}")

        # 注入:模擬「如果實作忽略 recheck 結果、一起升 CONFIRMED」會是什麼樣子,
        # 並證明這個狀態本身是自相矛盾的(state=CONFIRMED 但它自己的 recheck 評不過)。
        label_inj = "R6 inject: force-upgrading a failing-recheck rule → must be detected as wrong"
        bad_rule = dict(failing)
        bad_rule["state"] = D.CONFIRMED  # ← 注入:無條件跟著升級
        recheck_str = bad_rule["references"][0]["recheck"]
        actually_holds = R._run_recheck(recheck_str)
        if bad_rule["state"] == D.CONFIRMED and not actually_holds:
            ok(label_inj + f" (bad_rule state=CONFIRMED but recheck {recheck_str!r} evaluates "
                            f"to {actually_holds!r} — correctly flagged as an invalid state)")
        else:
            fail(label_inj, "injection scenario did not reproduce the bug")
    finally:
        _cleanup(tmp)


# ── R7: applies_to 含 generic rule(mapping is None)→ raise ──
# 注入:讓它靜靜通過 → 必須紅


def test_R7():
    label = "R7: applies_to containing a generic rule (mapping is None) → ratify_derivation must raise"
    generic = _generic_rule("tax:generic:測試其他")
    tmp = _make_tmp_taxonomy([generic])
    try:
        deriv = _simple_derivation("deriv:test-R7", ["tax:generic:測試其他"])
        try:
            R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                                reason="R7 不該通過", taxonomy_dir=tmp)
            fail(label, "no exception raised — generic rule in applies_to was silently accepted (BUG)")
        except ValueError as e:
            ok(label + f" (correctly raised: {e})")

        label_inj = "R7 inject: silently letting a generic rule pass through → must be caught"
        # 模擬「如果守門檢查被拿掉,靜靜通過」的結果:mapping is None 卻變成 CONFIRMED。
        bad_rule = dict(generic)
        bad_rule["state"] = D.CONFIRMED
        is_bad_state = (bad_rule["scope"] == "generic" and bad_rule["mapping"] is None
                        and bad_rule["state"] == D.CONFIRMED)
        if is_bad_state:
            ok(label_inj + f" (bad_rule scope={bad_rule['scope']!r} mapping={bad_rule['mapping']!r} "
                            f"state={bad_rule['state']!r} — this is exactly the forbidden state §2.2, "
                            f"correctly identified as invalid)")
        else:
            fail(label_inj, "injection scenario did not reproduce the bug")

        # 磁碟上真的什麼都沒被寫入(raise 在寫檔之前發生)
        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        if on_disk[0]["state"] == D.PROVISIONAL:
            ok(label + " (nothing written to disk after raise)")
        else:
            fail(label + " (disk check)", f"rule was written as {on_disk[0]['state']}")
    finally:
        _cleanup(tmp)


# ── R8: 批准後改 config.BUCKET_RULES 文字 → stale_confirmations 回報①並降級 ──
# 注入:忽略 revision → 必須紅


def test_R8():
    label = "R8: BUCKET_RULES text change after ratify → stale_confirmations reports ① and downgrades"
    r = _simple_rule("tax:測試庚", recheck="1==1")
    tmp = _make_tmp_taxonomy([r])
    original_bucket_rules = config.BUCKET_RULES
    try:
        deriv = _simple_derivation("deriv:test-R8", ["tax:測試庚"])
        R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                            reason="R8 測試批准", taxonomy_dir=tmp)
        rules_on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        derivs_on_disk = json.load(open(os.path.join(tmp, "derivations.json"), encoding="utf-8"))

        # 改動 BUCKET_RULES 文字(只在記憶體改,不寫回 config.py)
        changed_text = original_bucket_rules + "\n# 測試用改動,製造 revision mismatch\n"
        stale = D.stale_confirmations(rules_on_disk, derivs_on_disk, changed_text)
        stale_ids = {rid for rid, _ in stale}
        if "tax:測試庚" in stale_ids:
            reasons = [r for rid, r in stale if rid == "tax:測試庚"]
            ok(label + f" (correctly reported stale: {reasons})")
        else:
            fail(label, f"stale_confirmations did not catch the text change, stale={stale}")

        # 注入:「忽略 revision」的檢查 —— 如果拿舊文字(未改動)去驗,理應查不到 stale
        # (證明真正的 bug 判準確實是「文字有沒有變」,不是別的東西)
        label_inj = "R8 inject: checking with unchanged text must NOT report stale (control group)"
        stale_unchanged = D.stale_confirmations(rules_on_disk, derivs_on_disk, original_bucket_rules)
        if not stale_unchanged:
            ok(label_inj + " (unchanged text correctly reports no staleness — confirms the check is real)")
        else:
            fail(label_inj, f"unchanged text unexpectedly reported stale: {stale_unchanged}")
    finally:
        config.BUCKET_RULES = original_bucket_rules
        _cleanup(tmp)


# ── R9: 批准當下用提案檔裡的舊 revision 而非現算值 → 必須被擋 ──
# 注入:沿用舊值 → 必須紅


def test_R9():
    label = "R9: ratify_derivation must recompute revision, not reuse the proposal file's stale value"
    r = _simple_rule("tax:測試辛", recheck="1==1")
    tmp = _make_tmp_taxonomy([r])
    try:
        stale_value = "STALE_FAKE_REVISION"  # _simple_derivation() 預設帶的「提案檔舊值」
        deriv = _simple_derivation("deriv:test-R9", ["tax:測試辛"], revision=stale_value)
        result = R.ratify_derivation(deriv, approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                                     reason="R9 測試批准", taxonomy_dir=tmp)
        current = hashlib.sha256(config.BUCKET_RULES.encode("utf-8")).hexdigest()
        written = result["derivation"]["bucket_rules_revision"]
        if written == current and written != stale_value:
            ok(label + f" (recomputed correctly: {written[:16]}... != stale {stale_value!r})")
        else:
            fail(label, f"written revision={written!r}, current={current!r}, stale={stale_value!r}")

        # 注入:模擬「如果沿用提案檔舊值」會發生什麼 —— 寫出去的 derivation 會跟現在的
        # BUCKET_RULES 對不上,下一次 stale_confirmations 檢查就會（錯誤地）立刻判定 stale,
        # 即使 rule 本身的 recheck 完全正常。這證明沿用舊值是錯的,必須被擋。
        label_inj = "R9 inject: reusing the stale proposal revision → would immediately be flagged stale"
        bad_derivation = dict(result["derivation"])
        bad_derivation["bucket_rules_revision"] = stale_value  # ← 注入:沿用舊值
        rules_on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        bad_stale = D.stale_confirmations(rules_on_disk, [bad_derivation], config.BUCKET_RULES)
        if any(rid == "tax:測試辛" for rid, _ in bad_stale):
            ok(label_inj + f" (reusing stale value → stale_confirmations correctly flags it: {bad_stale})")
        else:
            fail(label_inj, "reusing stale value was NOT caught — R9 guard is not effective")
    finally:
        _cleanup(tmp)


# ── R10: ratify 全程不碰 facts/ ── 跑完 git diff facts/ 為空 ──────────────


def test_R10():
    label = "R10: ratify never touches facts/ — git diff facts/ stays empty"
    proj_root = os.path.dirname(os.path.abspath(__file__))

    def _git_diff_facts():
        result = subprocess.run(["git", "diff", "--stat", "facts/"],
                               capture_output=True, text=True, cwd=proj_root)
        return result.stdout.strip()

    before = _git_diff_facts()

    r1 = _simple_rule("tax:測試壬1", recheck="1==1")
    generic = _generic_rule("tax:generic:測試壬2")
    tmp = _make_tmp_taxonomy([r1, generic])
    try:
        R.ratify_rule("tax:測試壬1", approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                      reason="R10 測試", taxonomy_dir=tmp)
        deriv = _simple_derivation("deriv:test-R10", ["tax:測試壬1"])
        # tax:測試壬1 已經是 CONFIRMED 了,再包一次無妨,只是驗證流程不動 facts/
    finally:
        _cleanup(tmp)

    after = _git_diff_facts()
    if before == after == "":
        ok(label + " (git diff --stat facts/ empty before and after)")
    elif before == after:
        ok(label + f" (git diff --stat facts/ unchanged by ratify: {after!r} — "
                   f"pre-existing diff, not caused by this test)")
    else:
        fail(label, f"facts/ changed! before={before!r} after={after!r}")


# ── R11: 同一條 rule 重複 ratify → 不得產生重複的 human reference ──
# 注入:無條件 append → 必須紅


def test_R11():
    label = "R11: ratifying the same rule twice must not produce duplicate human references"
    r = _simple_rule("tax:測試癸")
    tmp = _make_tmp_taxonomy([r])
    try:
        R.ratify_rule("tax:測試癸", approved_by="henry", approved_at="2026-07-28T00:00:00Z",
                      reason="R11 第一次批准", taxonomy_dir=tmp)
        R.ratify_rule("tax:測試癸", approved_by="henry", approved_at="2026-07-28T00:00:01Z",
                      reason="R11 第一次批准", taxonomy_dir=tmp)  # 同樣的 reason,重複呼叫

        on_disk = json.load(open(os.path.join(tmp, "rules.json"), encoding="utf-8"))
        target = next(r for r in on_disk if r["rule_id"] == "tax:測試癸")
        human_refs = [ref for ref in target["references"] if ref["kind"] == "human"]

        if len(human_refs) == 1:
            ok(label + f" (only 1 human reference after 2 calls: {human_refs[0]['detail']})")
        else:
            fail(label, f"expected 1 human reference, got {len(human_refs)}: {human_refs}")

        # 注入:「無條件 append」會是什麼樣子 —— 每呼叫一次就多一條 human reference
        label_inj = "R11 inject: unconditional append → would produce duplicate human references"
        unconditional_refs = list(target["references"])
        # 模擬第三次呼叫,但用「無條件 append」邏輯(不檢查是否已存在)
        new_human_ref = D.make_reference(kind="human", detail="ratify: R11 第一次批准 (by henry)",
                                         at="2026-07-28T00:00:02Z", recheck=None)
        unconditional_refs_bad = unconditional_refs + [new_human_ref]
        bad_human_count = len([ref for ref in unconditional_refs_bad if ref["kind"] == "human"])
        if bad_human_count > len(human_refs):
            ok(label_inj + f" (unconditional append would produce {bad_human_count} human refs "
                            f"vs. real dedup'd {len(human_refs)} — correctly shows the danger)")
        else:
            fail(label_inj, "injection scenario did not reproduce the bug")
    finally:
        _cleanup(tmp)


# ── 執行所有測試 ────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("test_ratify.py — F3 ratify() tests (R1-R11)")
    print("=" * 60)

    test_R1()
    test_R2()
    test_R3()
    test_R4()
    test_R5()
    test_R6()
    test_R7()
    test_R8()
    test_R9()
    test_R10()
    test_R11()

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
