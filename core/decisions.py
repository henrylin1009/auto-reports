# -*- coding: utf-8 -*-
"""Decision 資料模型。occurrence-level、有狀態、有依據。

**`facts/` 是原始層,分類永遠不得改寫它。** 本模組只產生指回 facts 的決定,
任何「把桶寫回 facts」的函式都不准出現在這裡。

**零 IO**:不 import pypdfium2 / requests / locate / build / bridge。
"""
import hashlib
import datetime

# ── 狀態 ──────────────────────────────────────────────────────────
CONFIRMED    = "CONFIRMED"
PROVISIONAL  = "PROVISIONAL"
UNCLASSIFIED = "UNCLASSIFIED"

REFERENCE_KINDS = ("human", "rule", "synonym", "arithmetic", "prior_year", "group")
RULE_SCOPES     = ("name", "group", "generic", "column")
OCC_SCOPES      = ("row", "column", "record")


# ── 定位與指紋 ───────────────────────────────────────────────────────


def locator(cell_key, source_page, row_index) -> dict:
    """人類可讀的定位。**不是 key** —— 不得用來比對或綁定(鐵則 4)。"""
    return {
        "cell_key": cell_key,
        "source_page": source_page,
        "row_index": row_index,
    }


def record_fp(rec) -> str:
    """sha256(source_kind, total_col, printed_total, printed_totals)。

    **不含 source_page**:擴頁重抄後頁碼會變,含進去等於每次重抄都變成新 record。
    **不含 rows**:多抄到一列是「同一份 record 的更完整版本」,不是另一份。

    ⚠️ 實測是樣本,不是保證:今天 0 格同格同頁多份 record,
    但那只是現況樣本(plan_phaseB §2.2)。
    """
    printed_totals = rec.get("printed_totals") or {}
    # Sort for determinism
    pt_sorted = sorted(printed_totals.items())
    payload = repr((
        rec["source_kind"],
        rec["total_col"],
        rec["printed_total"],
        pt_sorted,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def row_fp(row, total_col) -> str:
    """sha256(norm(name), group, cols[total_col])。"""
    import sys
    import os
    # norm() is in buckets.py (判斷層). We replicate its logic here to stay zero-IO
    # and avoid importing judgement-layer code into the model layer.
    # Spec: remove spaces + unify full-width brackets.
    def _norm(s):
        return (s.replace(" ", "").replace("\u3000", "")
                 .replace("\uff08", "(").replace("\uff09", ")"))

    name_norm = _norm(row["name"])
    group = row.get("group") or ""
    amount = row["cols"].get(total_col)
    payload = repr((name_norm, group, amount))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def occurrence(cell_key, rec, scope, ordinal=None, row=None) -> dict:
    """{cell_key, record_fp, scope, ordinal, row_fp}。scope != "row" 時 row_fp 為 None。"""
    if scope not in OCC_SCOPES:
        raise ValueError(f"occurrence scope must be one of {OCC_SCOPES}, got {scope!r}")
    rfp = record_fp(rec)
    rfp2 = row_fp(row, rec["total_col"]) if (scope == "row" and row is not None) else None
    return {
        "cell_key": cell_key,
        "record_fp": rfp,
        "scope": scope,
        "ordinal": ordinal,
        "row_fp": rfp2,
    }


# ── 型別建構子 ───────────────────────────────────────────────────────


def make_reference(kind, detail, at, recheck=None) -> dict:
    """建立 Reference 物件。

    kind: 見 REFERENCE_KINDS
    detail: 人:ratify 記錄 id;規則:命中的關鍵字;同義詞:配對金額與對造名;算術:等式
    at: ISO 時間字串
    recheck: str|None —— 可機械重跑的驗算式
    """
    if kind not in REFERENCE_KINDS:
        raise ValueError(f"reference kind must be one of {REFERENCE_KINDS}, got {kind!r}")
    return {
        "kind": kind,
        "detail": detail,
        "at": at,
        "recheck": recheck,
    }


def make_rule(rule_id, scope, mapping, state, references,
              derivation_id=None, approved_by=None, approved_at=None) -> dict:
    """建立 TaxonomyRule 物件。

    欄位照 plan_phaseB §2.3。**一個欄位都不准加減。**
    """
    if scope not in RULE_SCOPES:
        raise ValueError(f"rule scope must be one of {RULE_SCOPES}, got {scope!r}")
    if state not in (CONFIRMED, PROVISIONAL):
        raise ValueError(f"rule state must be CONFIRMED or PROVISIONAL, got {state!r}")
    return {
        "rule_id": rule_id,
        "scope": scope,
        "mapping": mapping,
        "state": state,
        "references": list(references),
        "derivation_id": derivation_id,
        "approved_by": approved_by,
        "approved_at": approved_at,
    }


def make_decision(occ, loc, name, group, mapping, state,
                  taxonomy_ref=None, references=(), at=None, by=None) -> dict:
    """建立 Decision 物件(occurrence-level)。

    欄位照 plan_phaseB §2.3。**一個欄位都不准加減。**
    """
    if state not in (CONFIRMED, PROVISIONAL, UNCLASSIFIED):
        raise ValueError(f"decision state must be one of (CONFIRMED, PROVISIONAL, UNCLASSIFIED), "
                         f"got {state!r}")
    return {
        "occurrence": occ,
        "locator": loc,
        "name": name,
        "group": group,
        "mapping": mapping,
        "state": state,
        "taxonomy_ref": taxonomy_ref,
        "references": list(references),
        "at": at,
        "by": by,
    }


def make_derivation(derivation_id, description, predicate,
                    bucket_rules_revision, applies_to,
                    approved_by, approved_at, references) -> dict:
    """建立 Derivation 物件。

    欄位照 plan_phaseB §3.3。**一個欄位都不准加減。**
    批准是 B1.5 的事;B1 只建立提案(approved_by/at 可為 None)。
    """
    return {
        "derivation_id": derivation_id,
        "description": description,
        "predicate": predicate,
        "bucket_rules_revision": bucket_rules_revision,
        "applies_to": list(applies_to),
        "approved_by": approved_by,
        "approved_at": approved_at,
        "references": list(references),
    }


# ── 不變式檢查(純函數) ─────────────────────────────────────────────


def validate_rule(rule) -> list:
    """I3b:state==CONFIRMED 的 rule 必須有 ≥1 條 kind=="human" 的 reference。"""
    errors = []
    if rule["state"] == CONFIRMED:
        human_refs = [r for r in rule.get("references", []) if r["kind"] == "human"]
        if not human_refs:
            errors.append(
                f"I3b VIOLATION: CONFIRMED rule {rule['rule_id']!r} has no human reference"
            )
    return errors


def validate_decision(decision, rules_by_id) -> list:
    """I2 + I3a。
      I2  mapping is None ⟺ state == UNCLASSIFIED
      I3a state==CONFIRMED ⇒ taxonomy_ref 非空,且它指到的 rule.state == CONFIRMED
          **不要求 decision 自己帶 human reference**(鐵則 3)
    """
    errors = []
    mapping = decision["mapping"]
    state = decision["state"]

    # I2: mapping is None ⟺ state == UNCLASSIFIED
    if mapping is None and state != UNCLASSIFIED:
        errors.append(
            f"I2 VIOLATION: mapping is None but state is {state!r} (must be UNCLASSIFIED)"
        )
    if mapping is not None and state == UNCLASSIFIED:
        errors.append(
            f"I2 VIOLATION: mapping is {mapping!r} but state is UNCLASSIFIED (mapping must be None)"
        )

    # I3a: CONFIRMED occurrence must reference a CONFIRMED taxonomy rule
    if state == CONFIRMED:
        taxonomy_ref = decision.get("taxonomy_ref")
        if not taxonomy_ref:
            errors.append(
                "I3a VIOLATION: CONFIRMED decision has no taxonomy_ref"
            )
        else:
            # Extract rule_id from taxonomy_ref (format: "rule_id@version" or just "rule_id")
            ref_rule_id = taxonomy_ref.split("@")[0] if "@" in taxonomy_ref else taxonomy_ref
            rule = rules_by_id.get(ref_rule_id)
            if rule is None:
                errors.append(
                    f"I3a VIOLATION: taxonomy_ref {taxonomy_ref!r} not found in rules_by_id"
                )
            elif rule["state"] != CONFIRMED:
                errors.append(
                    f"I3a VIOLATION: CONFIRMED decision references rule {ref_rule_id!r} "
                    f"which is {rule['state']!r} not CONFIRMED"
                )
    return errors


def decide(row, group, rules_by_name, propose_fn) -> dict:
    """唯一的狀態表(plan_phaseB §2.5),**不准另寫分支**:

        命中 CONFIRMED rule           → CONFIRMED,taxonomy_ref 指向它
        命中 PROVISIONAL rule         → PROVISIONAL,taxonomy_ref 指向它
        taxonomy 沒有但 propose 提得出 → PROVISIONAL,自帶 reference
        提不出候選                     → UNCLASSIFIED,mapping = None

    **本函數沒有任何一條路徑可以自己造出 CONFIRMED。** 它只能「轉述」
    一條已經被人批准過的 rule(鐵則 2)。

    decide() 不得憑機器推論產生 CONFIRMED,
    但可引用已 ratify 的 CONFIRMED rule 產生 CONFIRMED occurrence decision。
    """
    # norm: same logic as buckets.norm (zero-IO, no import)
    def _norm(s):
        return (s.replace(" ", "").replace("\u3000", "")
                 .replace("\uff08", "(").replace("\uff09", ")"))

    # \u26a0\ufe0f \u8907\u88fd\u81ea buckets._FOOTNOTE / buckets._strip_footnote(zero-IO,\u4e0d import
    # buckets \u662f\u523b\u610f\u7684,\u898b\u4e0a\u9762 `_norm` \u7684\u540c\u4e00\u500b\u7406\u7531)\u2014\u2014 **\u5169\u908a\u8981\u624b\u52d5\u540c\u6b65**,\u9019\u6b63\u662f
    # \u9019\u6574\u652f\u300c\u5e73\u884c\u5be6\u4f5c\u300d\u7684\u98a8\u96aa\u672c\u8eab,\u4e0d\u662f\u9019\u88e1\u6253\u7b97\u89e3\u6c7a\u7684\u4e8b(\u5b83\u6c92\u6709\u4efb\u4f55\u4f7f\u7528\u8005
    # \u53ef\u9054\u7684\u547c\u53eb\u7aef,\u898b 2026-08-12 test_decide_equiv.py \u7684\u8abf\u67e5\u8a18\u9304)\u3002
    # 2026-08-12 \u88dc:\u539f\u672c\u6c92\u6709\u9019\u4e00\u6b65,taxonomy \u67e5\u4e0d\u5230\u5c31\u76f4\u63a5\u5224 UNCLASSIFIED,
    # \u800c buckets.bucket() \u6703\u5728\u67e5\u4e0d\u5230\u6642\u525d\u4e00\u6b21\u8a3b\u8173\u8a18\u865f\u91cd\u67e5 \u2014\u2014 6 \u5217\u300c\u570b\u5916\u6a5f\u69cb
    # \u767c\u884c\u50b5\u5238\uff08\u8a3b\u4e00\uff09\u300d\u300c\u8ca8\u5e63\u4ea4\u63db -\u300d\u9019\u985e\u6f0f\u5224\u90fd\u662f\u9019\u500b\u7f3a\u53e3,\u4e0d\u662f taxonomy
    # \u6f0f\u6536\u8cc7\u6599\u3002
    import re as _re
    _FOOTNOTE = _re.compile(r"\((?:\u9644\u8a3b|\u8a3b)[^)]*\)$|[-\uff0d\u2014]\s*\u8a3b?$")

    def _strip_footnote(n):
        prev = None
        while prev != n:
            prev, n = n, _FOOTNOTE.sub("", n).strip()
        return n

    name = row["name"]
    name_norm = _norm(name)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Replicates buckets.bucket() logic exactly:
    # - For GENERIC names (like 其他, 其他(註)): check GROUP_SYN (group rule) FIRST.
    #   If group matches → use group bucket. Otherwise fall through to name (SYN) lookup.
    # - For non-GENERIC names: look up by normalized name directly.
    #
    # IMPORTANT: scope="generic" rules have mapping=None (they're boolean markers).
    # They are SKIPPED here — the actual bucket comes from scope="group" or scope="name".

    # 查一次(原名 or 剝過註腳的名字)。抽成函式是因為 buckets.bucket() 對
    # 「剝完註腳的新名字」要重跑**同一套** GENERIC/group/name 判斷,兩份邏輯
    # 分開寫等於又製造一次漂移(這次調查的兩個 bug 都是這樣長出來的)。
    def _lookup(nm):
        generic_rule_key = f"generic:{nm}"
        is_generic = (rules_by_name.get(generic_rule_key) is not None)
        if is_generic:
            # GENERIC name: try group lookup first (matches GROUP_SYN priority)
            group_norm = _norm(group or "")
            if group_norm:
                r = rules_by_name.get(f"group:{group_norm}")
                if r is not None:
                    return r
            # If no group match, fall through to name lookup below
            r = rules_by_name.get(nm)
            if r and r.get("scope") == "name":
                return r
            return None
        # Non-GENERIC: direct name lookup **only** — 不退回查段落。
        #
        # 2026-08-12 修:這裡原本有一段「查不到名字就退回查 group」的 fallback,
        # 違反 buckets.bucket() 檔頭明文的規則(「段落不准覆蓋具名科目,否則
        # 衍生段裡的『政府公債』會被整段吃掉」)。test_decide_equiv.py 抓到它
        # 已經在真實資料裡產生一筆誤判:「期貨交易保證金－自有資金」段落是
        # 「強制透過損益按公允價值衡量之金融資產」底下的衍生工具小節,名字
        # 本身其實是保證金/現金性質的科目,被這段 fallback 誤歸進「衍生」桶
        # (buckets.bucket() 對同一列正確回 None,判不準,等人審)。
        # 拿掉 fallback 之後行為與 buckets.bucket() 完全一致:查不到名字就是
        # 查不到,不准用段落去猜。
        return rules_by_name.get(nm)

    rule = _lookup(name_norm)
    if rule is None:
        name_norm2 = _strip_footnote(name_norm)
        if name_norm2 != name_norm:
            rule = _lookup(name_norm2)

    if rule is not None:
        # Found in taxonomy — skip scope=generic rules (they have mapping=None)
        if rule.get("scope") == "generic":
            # Generic marker — no mapping assignment; treat as not found
            rule = None

    if rule is not None:
        # Found in taxonomy
        state = rule["state"]  # Either CONFIRMED or PROVISIONAL
        mapping = rule["mapping"]
        taxonomy_ref = rule["rule_id"]
        return make_decision(
            occ=None,  # caller fills in occurrence
            loc=None,  # caller fills in locator
            name=name,
            group=group,
            mapping=mapping,
            state=state,
            taxonomy_ref=taxonomy_ref,
            references=[],
            at=now,
            by="decide",
        )

    # Not in taxonomy: try propose_fn
    proposed_bucket, reason = propose_fn(name_norm)
    if proposed_bucket is not None:
        ref = make_reference(
            kind="rule",
            detail=reason,
            at=now,
            recheck=f"rules.propose({name_norm!r})[0] == {proposed_bucket!r}",
        )
        return make_decision(
            occ=None,
            loc=None,
            name=name,
            group=group,
            mapping=proposed_bucket,
            state=PROVISIONAL,
            taxonomy_ref=None,
            references=[ref],
            at=now,
            by="decide",
        )

    # Cannot classify
    return make_decision(
        occ=None,
        loc=None,
        name=name,
        group=group,
        mapping=None,
        state=UNCLASSIFIED,
        taxonomy_ref=None,
        references=[],
        at=now,
        by="decide",
    )


# ── 降級(鐵則 5,純函數) ────────────────────────────────────────────


def stale_confirmations(rules, derivations, bucket_rules_text) -> list:
    """回傳 [(rule_id, 降級原因)]。任一款成立就要降回 PROVISIONAL:

      ① derivation.bucket_rules_revision != sha256(bucket_rules_text)
      ② 該 rule 自己的 recheck 跑起來不成立
      ③ rule_id 不在 derivation.applies_to 裡

    **降級要大聲報錯並列出是哪幾條、因為哪一款,不准靜靜降級。**
    ① 是使用者 2026-07-28 加的:BUCKET_RULES 一改,整批批准的依據就變了 ——
    不是逐條 recheck 過了就算數,人當初看的是那一版散文。
    """
    import hashlib
    current_revision = hashlib.sha256(bucket_rules_text.encode("utf-8")).hexdigest()
    deriv_by_id = {d["derivation_id"]: d for d in derivations}

    stale = []
    for rule in rules:
        if rule["state"] != CONFIRMED:
            continue
        deriv_id = rule.get("derivation_id")
        if deriv_id is None:
            continue
        deriv = deriv_by_id.get(deriv_id)
        if deriv is None:
            stale.append((rule["rule_id"], f"③ derivation {deriv_id!r} not found"))
            continue

        # ① Check bucket_rules_revision
        if deriv["bucket_rules_revision"] != current_revision:
            stale.append((
                rule["rule_id"],
                f"① bucket_rules_revision mismatch: derivation has "
                f"{deriv['bucket_rules_revision']!r}, current is {current_revision!r}"
            ))
            continue  # No need to check further if revision mismatch

        # ③ Check rule_id in applies_to
        if rule["rule_id"] not in deriv["applies_to"]:
            stale.append((
                rule["rule_id"],
                f"③ rule_id {rule['rule_id']!r} not in derivation.applies_to"
            ))
            continue

        # ② Check recheck
        for ref in rule.get("references", []):
            recheck = ref.get("recheck")
            if recheck is None:
                continue
            try:
                # Evaluate recheck in a safe namespace with rules imported
                import rules as rules_mod
                import buckets as buckets_mod
                ns = {"rules": rules_mod, "buckets": buckets_mod}
                result = eval(recheck, ns)  # noqa: S307
                if not result:
                    stale.append((
                        rule["rule_id"],
                        f"② recheck failed: {recheck!r} evaluated to {result!r}"
                    ))
                    break
            except Exception as e:
                stale.append((
                    rule["rule_id"],
                    f"② recheck error: {recheck!r} raised {e!r}"
                ))
                break

    if stale:
        lines = [f"  {rule_id}: {reason}" for rule_id, reason in stale]
        import sys
        print(
            f"[decisions.stale_confirmations] DOWNGRADE REQUIRED for {len(stale)} rule(s):\n"
            + "\n".join(lines),
            file=sys.stderr,
        )

    return stale


def apply_downgrade(rules, stale) -> dict:
    """回傳降級後的 rules。**不改輸入**。

    stale: [(rule_id, reason)] — output of stale_confirmations()
    Returns: dict mapping rule_id → upgraded rule dict (with state=PROVISIONAL)
    """
    stale_ids = {rule_id for rule_id, _ in stale}
    result = {}
    for rule in rules:
        if rule["rule_id"] in stale_ids:
            downgraded = dict(rule)
            downgraded["state"] = PROVISIONAL
            result[rule["rule_id"]] = downgraded
        else:
            result[rule["rule_id"]] = dict(rule)
    return result


# ── 重綁協定(純函數) ──────────────────────────────────────────────


def rebind(old_decisions, new_cell_records) -> dict:
    """重抄後把舊 Decision 綁到新 record。五步(plan_phaseB §2.2):

      1. 用 record_fp 找對應的舊 record;找不到 → 全部視為新 occurrence
      2. 在該 record 內用 row_fp 綁定;綁上的沿用舊 mapping 與 state
      3. 綁不上的舊 occurrence → 標 superseded,**不刪**
      4. 綁不上的新 occurrence → 建新 Decision
      5. **絕不用 ordinal 硬對**

    ⚠️ row_fp 碰撞要 **raise**,不准靜靜覆蓋。今天實測 0 筆碰撞,
    但那是樣本結果不是保證。

    Parameters:
        old_decisions: list of decision dicts (from decisions/*.json)
        new_cell_records: list of record dicts (newly transcribed)

    Returns:
        dict with keys:
            "bound": list of decisions (old decisions re-bound to new records)
            "superseded": list of decisions (old occurrences that couldn't be bound)
            "new": list of {"record_fp": ..., "row_fp": ..., "row": ...}
                   (new occurrences that need fresh Decisions)
    """
    import datetime
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Build lookup: record_fp → [old_decision]
    old_by_rfp = {}
    for dec in old_decisions:
        occ = dec.get("occurrence") or {}
        rfp = occ.get("record_fp")
        if rfp:
            old_by_rfp.setdefault(rfp, []).append(dec)

    bound = []
    superseded_decisions = []
    new_occurrences = []

    for rec in new_cell_records:
        rfp = record_fp(rec)
        old_for_rec = old_by_rfp.get(rfp, [])

        if not old_for_rec:
            # Step 1: no matching old record → all new occurrences
            for row in rec.get("rows", []):
                rfp2 = row_fp(row, rec["total_col"])
                new_occurrences.append({
                    "record_fp": rfp,
                    "row_fp": rfp2,
                    "row": row,
                    "rec": rec,
                })
            continue

        # Build lookup: row_fp → old_decision (within this record)
        # Step 1 + 2: use row_fp to rebind
        old_by_rfp2 = {}
        for dec in old_for_rec:
            occ = dec.get("occurrence") or {}
            rfp2 = occ.get("row_fp")
            if rfp2:
                if rfp2 in old_by_rfp2:
                    raise ValueError(
                        f"rebind: row_fp collision detected for {rfp2!r} in record {rfp!r}. "
                        "This should not happen with current data. "
                        "Collision must be resolved with ordinal disambiguation (not implemented yet)."
                    )
                old_by_rfp2[rfp2] = dec

        matched_old_rfp2s = set()
        for row in rec.get("rows", []):
            rfp2 = row_fp(row, rec["total_col"])
            if rfp2 in old_by_rfp2:
                # Step 2: bind
                old_dec = old_by_rfp2[rfp2]
                rebound = dict(old_dec)
                matched_old_rfp2s.add(rfp2)
                bound.append(rebound)
            else:
                # Step 4: new occurrence
                new_occurrences.append({
                    "record_fp": rfp,
                    "row_fp": rfp2,
                    "row": row,
                    "rec": rec,
                })

        # Step 3: mark unmatched old occurrences as superseded (don't delete)
        for rfp2, dec in old_by_rfp2.items():
            if rfp2 not in matched_old_rfp2s:
                sup = dict(dec)
                sup["superseded"] = True
                sup["superseded_at"] = now
                superseded_decisions.append(sup)

    # Any old decisions whose record_fp had no match in new records
    matched_rfps = {record_fp(rec) for rec in new_cell_records}
    for rfp, decs in old_by_rfp.items():
        if rfp not in matched_rfps:
            for dec in decs:
                sup = dict(dec)
                sup["superseded"] = True
                sup["superseded_at"] = now
                superseded_decisions.append(sup)

    return {
        "bound": bound,
        "superseded": superseded_decisions,
        "new": new_occurrences,
    }
