# -*- coding: utf-8 -*-
"""core/ratify.py — B1.5 的工具:把「批准」這個人工動作寫成可審的 IO 函數。

**本模組不得被本工單(brief_phaseB_B1fix_ratify)呼叫去批准任何東西。**
真實 `taxonomy/` 在本單全程唯讀 —— 這裡只提供工具,測試一律用 tmp taxonomy_dir。

Ring 分層:`core/decisions.py` 是零 IO 的純函數模型層,`ratify_rule()` /
`ratify_derivation()` 要讀寫 `taxonomy/`,所以跟 `core/migrate_syn.py` 同一層,
不寫進 `decisions.py`。

`ratify()` 是**唯一**能產生 CONFIRMED 的入口 —— `migrate_syn.py` 與
`core.decisions.decide()` 都不准、也沒有路徑產生 CONFIRMED。
"""
import hashlib
import json
import os

import config
import rules as rules_mod
import buckets as buckets_mod

from core.decisions import (
    CONFIRMED, PROVISIONAL,
    make_reference, validate_rule, stale_confirmations,
)


def _bucket_rules_revision() -> str:
    """批准當下現算的 BUCKET_RULES revision。**不准沿用提案檔裡的舊值**(R9)。"""
    return hashlib.sha256(config.BUCKET_RULES.encode("utf-8")).hexdigest()


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _rules_path(taxonomy_dir):
    return os.path.join(taxonomy_dir, "rules.json")


def _derivations_path(taxonomy_dir):
    return os.path.join(taxonomy_dir, "derivations.json")


def _run_recheck(recheck: str) -> bool:
    """跑一條 rule reference 的 recheck 字串,回傳是否成立。

    格式跟 core/migrate_syn.py / core/decisions.stale_confirmations 一致:
    - 一般 rule/synonym reference:`eval(recheck, ns)`
    - arithmetic reference:`exec("exec(code_string)")` 的形式,用 exec 執行
      並以「沒有 raise」代表成立(assert 失敗會 raise AssertionError)
    """
    ns = {"rules": rules_mod, "buckets": buckets_mod}
    if recheck.startswith("exec("):
        import ast
        code = ast.literal_eval(recheck[5:-1])
        try:
            exec(code, dict(ns))  # noqa: S102
            return True
        except Exception:
            return False
    try:
        return bool(eval(recheck, ns))  # noqa: S307
    except Exception:
        return False


def new_rule(scope, norm_name, mapping, taxonomy_dir="taxonomy") -> str:
    """B4 (a) 第一步:review queue 冒出一個 taxonomy 從沒見過的名字/群組,
    人工決定收錄。**只建 PROVISIONAL**——CONFIRMED 一律只能經 `ratify_rule()`,
    不因為呼叫端是 B4 就破例(鐵則 2,§2.5)。呼叫端接著自己叫 `ratify_rule()`
    把它升級,兩步分開是為了讓「建了什麼」與「誰批准了它」各自留痕。

    **idempotent,但只在 mapping 相同時才是「什麼都沒變」**:`rule_id` 已存在
    且 mapping 跟這次要收錄的一致 → 直接回傳,不重複新增。**若已存在但 mapping
    不同 → raise,不准靜靜沿用舊值。**

    這條防的是一個真實踩到的坑:review 佇列裡的名字可能剛好對到 taxonomy 裡
    早就有的 rule(例如某個名字本來就是 PROVISIONAL,只是還沒被批准)。
    如果這裡靜靜跳過、讓呼叫端接著 `ratify_rule()` 把舊 mapping 升成
    CONFIRMED,使用者在表單填的桶名會被無聲丟掉,而使用者會誤以為自己
    確認的是自己填的那個桶——這比報錯危險得多。

    `norm_name` 呼叫端要先 `buckets.norm()` 過;本函式不做正規化,
    因為正規化規則只有一份(`buckets.norm`),不在這裡另抄一份。
    """
    if scope not in ("name", "group", "generic"):
        raise ValueError(f"new_rule: scope 必須是 name/group/generic,收到 {scope!r}")
    rule_id = {"name": f"tax:{norm_name}",
              "group": f"tax:group:{norm_name}",
              "generic": f"tax:generic:{norm_name}"}[scope]
    want_mapping = mapping if scope != "generic" else None

    rules_path = _rules_path(taxonomy_dir)
    rules = _load_json(rules_path)
    for r in rules:
        if r["rule_id"] == rule_id:
            if r["mapping"] != want_mapping:
                raise ValueError(
                    f"new_rule: {rule_id!r} 在 taxonomy 裡已存在,mapping 是 "
                    f"{r['mapping']!r},與這次要收錄的 {want_mapping!r} 不同——"
                    f"不准靜靜沿用舊值蓋掉使用者的輸入。若要修改既有 rule 的 "
                    f"mapping,那是另一個動作,不是『收錄成新科目』。")
            return rule_id

    from core.decisions import make_rule
    rule = make_rule(rule_id=rule_id, scope=scope,
                     mapping=(mapping if scope != "generic" else None),
                     state=PROVISIONAL, references=[])
    rules.append(rule)
    _write_json(rules_path, rules)
    return rule_id


def ratify_rule(rule_id, approved_by, approved_at, reason,
                taxonomy_dir="taxonomy") -> dict:
    """路徑 (a):逐條批准一條 taxonomy rule。

    寫入 taxonomy/rules.json:該 rule 加一條 kind=="human" 的 reference
    (detail 記 reason),state 升為 CONFIRMED,approved_by/at 填入。

    **只吃人工輸入。** approved_by / reason 為空 → raise,不准給預設值。
    """
    if not approved_by:
        raise ValueError("ratify_rule: approved_by must not be empty — 只吃人工輸入,不給預設值")
    if not reason:
        raise ValueError("ratify_rule: reason must not be empty — 只吃人工輸入,不給預設值")
    if not approved_at:
        raise ValueError("ratify_rule: approved_at must not be empty — 只吃人工輸入,不給預設值")

    rules_path = _rules_path(taxonomy_dir)
    rules = _load_json(rules_path)

    target = None
    for r in rules:
        if r["rule_id"] == rule_id:
            target = r
            break
    if target is None:
        raise ValueError(f"ratify_rule: rule_id {rule_id!r} not found in {rules_path}")

    # R11: 同一條 rule 重複 ratify 不得產生重複的 human reference —— 若已有一條
    # detail/approved_by/reason 完全一致的 human reference,視為已批准,不再 append。
    existing_human = [
        ref for ref in target.get("references", [])
        if ref["kind"] == "human" and ref.get("detail") == f"ratify: {reason} (by {approved_by})"
    ]
    if not existing_human:
        human_ref = make_reference(
            kind="human",
            detail=f"ratify: {reason} (by {approved_by})",
            at=approved_at,
            recheck=None,
        )
        target["references"] = list(target.get("references", [])) + [human_ref]

    target["state"] = CONFIRMED
    target["approved_by"] = approved_by
    target["approved_at"] = approved_at

    # I3b: CONFIRMED 沒有 human reference 要被 validate_rule 擋下
    errors = validate_rule(target)
    if errors:
        raise ValueError(f"ratify_rule: I3b violation for {rule_id!r}: {errors}")

    _write_json(rules_path, rules)
    return target


def ratify_derivation(derivation, approved_by, approved_at, reason,
                      taxonomy_dir="taxonomy") -> dict:
    """路徑 (b):批准一條 Derivation,連帶升級它 applies_to 涵蓋的 rule。

    1. derivation.references 必須含 ≥1 條 kind=="human"(I3b 的來源)——
       由本函式依 approved_by/reason 建立,**不准接受呼叫端傳進來的 human ref**
    2. 寫進 taxonomy/derivations.json
    3. 對 applies_to 裡的每一條 rule:recheck 跑起來成立才升 CONFIRMED,
       不成立的留在 PROVISIONAL 並列出來,不准靜靜跳過
    4. 升級後立刻重跑 core.decisions.stale_confirmations(),
       有任何一條 stale 就 raise 並回滾,不准寫出一個當場就該降級的狀態
    """
    if not approved_by:
        raise ValueError("ratify_derivation: approved_by must not be empty")
    if not reason:
        raise ValueError("ratify_derivation: reason must not be empty")
    if not approved_at:
        raise ValueError("ratify_derivation: approved_at must not be empty")

    rules_path = _rules_path(taxonomy_dir)
    deriv_path = _derivations_path(taxonomy_dir)
    rules = _load_json(rules_path)
    derivations = _load_json(deriv_path)

    rules_by_id = {r["rule_id"]: r for r in rules}
    applies_to = list(derivation.get("applies_to", []))

    # generic rule (mapping is None) 出現在 applies_to → raise（§2.2:predicate
    # 對它不成立，這不是「批准成功但留 PROVISIONAL」，是提案本身就是錯的）
    generic_in_applies_to = [
        rid for rid in applies_to
        if rid in rules_by_id and rules_by_id[rid].get("scope") == "generic"
    ]
    if generic_in_applies_to:
        raise ValueError(
            "ratify_derivation: applies_to contains generic-scope rule(s) whose "
            f"mapping is None — predicate does not hold for them: {generic_in_applies_to}"
        )

    unknown = [rid for rid in applies_to if rid not in rules_by_id]
    if unknown:
        raise ValueError(f"ratify_derivation: applies_to references unknown rule_id(s): {unknown}")

    # 批准當下現算的 revision（**不准沿用提案檔裡的舊值**，R9）
    current_revision = _bucket_rules_revision()

    # 不接受呼叫端傳進來的 human reference（不准偽造批准來源）——
    # 本函式自己依 approved_by/reason 建一條，忽略 derivation 裡原本帶的任何東西。
    human_ref = make_reference(
        kind="human",
        detail=f"ratify: {reason} (by {approved_by})",
        at=approved_at,
        recheck=None,
    )

    new_derivation = dict(derivation)
    new_derivation["bucket_rules_revision"] = current_revision
    new_derivation["approved_by"] = approved_by
    new_derivation["approved_at"] = approved_at
    new_derivation["references"] = [human_ref]

    # 3. 逐條升級：recheck 成立才升 CONFIRMED，不成立留 PROVISIONAL 並列出
    upgraded_ids = []
    left_provisional = []
    new_rules = [dict(r) for r in rules]
    new_rules_by_id = {r["rule_id"]: r for r in new_rules}

    for rid in applies_to:
        rule = new_rules_by_id[rid]
        rechecks = [ref.get("recheck") for ref in rule.get("references", []) if ref.get("recheck")]
        if not rechecks:
            left_provisional.append((rid, "no recheck available on this rule"))
            continue
        all_pass = True
        failure_detail = None
        for rc in rechecks:
            if not _run_recheck(rc):
                all_pass = False
                failure_detail = rc
                break
        if not all_pass:
            left_provisional.append((rid, f"recheck failed: {failure_detail!r}"))
            continue

        # 升級：加 human reference(來自本次批准),state → CONFIRMED
        rule["references"] = list(rule.get("references", [])) + [dict(human_ref)]
        rule["state"] = CONFIRMED
        rule["derivation_id"] = new_derivation["derivation_id"]
        rule["approved_by"] = approved_by
        rule["approved_at"] = approved_at

        errors = validate_rule(rule)
        if errors:
            raise ValueError(f"ratify_derivation: I3b violation for {rid!r}: {errors}")

        upgraded_ids.append(rid)

    # 4. 升級後立刻重跑 stale_confirmations，有任何一條 stale 就 raise 並回滾
    #    （不寫檔，new_rules/new_derivation 只在記憶體中，函式一 raise 什麼都沒寫出去）
    new_derivations = [d for d in derivations if d["derivation_id"] != new_derivation["derivation_id"]]
    new_derivations.append(new_derivation)

    stale = stale_confirmations(new_rules, new_derivations, config.BUCKET_RULES)
    if stale:
        raise ValueError(
            "ratify_derivation: aborting — stale_confirmations found "
            f"{len(stale)} rule(s) that would be CONFIRMED-but-stale immediately "
            f"after ratify: {stale}"
        )

    # 全部檢查通過才真的寫檔
    _write_json(rules_path, new_rules)
    _write_json(deriv_path, new_derivations)

    return {
        "derivation": new_derivation,
        "upgraded": upgraded_ids,
        "left_provisional": left_provisional,
    }
