#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/migrate_syn.py — B1: 把今天的隱性分類決定顯性化。

讀 buckets.SYN / GROUP_SYN / GENERIC(**只讀,不改**),
逐條建立 reference,寫 taxonomy/rules.json。

**B1 產出 0 條 CONFIRMED**(鐵則 1、5)。
所有 rule 都是 PROVISIONAL,等待使用者在 B1.5 透過 ratify() 批准。

執行方式:
    python3 core/migrate_syn.py
    python3 -m core.migrate_syn
"""
import hashlib
import json
import os
import subprocess
import sys
import datetime

# 確保從 project root 可以 import
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import buckets
import rules as rules_mod
import config
import synonyms
import facts

from core.decisions import (
    PROVISIONAL, CONFIRMED,
    make_reference, make_rule, make_derivation,
)

# ── 常數 ──────────────────────────────────────────────────────────

NOW = datetime.datetime.utcnow().isoformat() + "Z"

BATCH3_NO_EVIDENCE = {"政府債券", "貨幣交換", "外匯換匯合約"}

# arithmetic 證據(逐條從 buckets.py 原始碼註解抄成可重跑的斷言)
# key = (原名), value = (等式描述, recheck 字串, 出處)
ARITHMETIC_EVIDENCE = {
    # key = 原名, value = (等式描述, recheck 運算式, 出處格)
    #
    # ⚠️ recheck **必須是回傳真值的運算式**(協定見 core/recheck.py)。
    #    早期版本寫成 exec("...assert...") —— eval 起來回傳 None,
    #    於是驗算明明通過卻被 stale_confirmations 判成失敗。2026-07-28 改掉。
    "CMO": (
        "富邦明細表 p154: CMO+RMBS=61,332,697=附註資產證券化商品",
        "__import__('core.recheck', fromlist=['x']).names_sum_matches('202404_富邦_個體|AC', ['CMO', 'RMBS'], '資產證券化商品')",
        "202404_富邦_個體|AC",
    ),
    "RMBS": (
        "富邦明細表 p154: CMO+RMBS=61,332,697=附註資產證券化商品",
        "__import__('core.recheck', fromlist=['x']).names_sum_matches('202404_富邦_個體|AC', ['CMO', 'RMBS'], '資產證券化商品')",
        "202404_富邦_個體|AC",
    ),
    # 兆豐這格附註逐項成本、明細表逐項公允,要挑成本欄才比得動(prefer_cost)。
    "定存單": (
        "兆豐 202404 OCI: 銀行定存單+定期存單-可轉讓=15,396,926=附註定存單(取得成本口徑對齊)",
        "__import__('core.recheck', fromlist=['x']).names_sum_matches('202404_兆豐_個體|OCI', ['銀行定存單', '定期存單-可轉讓'], '定存單', prefer_cost=True)",
        "202404_兆豐_個體|OCI",
    ),
    "定期存單-可轉讓": (
        "兆豐 202404 OCI: 銀行定存單+定期存單-可轉讓=15,396,926=附註定存單(取得成本口徑對齊)",
        "__import__('core.recheck', fromlist=['x']).names_sum_matches('202404_兆豐_個體|OCI', ['銀行定存單', '定期存單-可轉讓'], '定存單', prefer_cost=True)",
        "202404_兆豐_個體|OCI",
    ),
    "換匯": (
        "中信明細表「衍生金融工具」段8列相加=78,086,700=附註「衍生金融資產」(202404 Trading p31/p147)",
        "__import__('core.recheck', fromlist=['x']).group_sum_matches('202404_中信_個體|Trading', '衍生金融工具', '衍生金融資產')",
        "202404_中信_個體|Trading",
    ),
    "商品交換": (
        "中信明細表「衍生金融工具」段8列相加=78,086,700=附註「衍生金融資產」(202404 Trading p31/p147)",
        "__import__('core.recheck', fromlist=['x']).group_sum_matches('202404_中信_個體|Trading', '衍生金融工具', '衍生金融資產')",
        "202404_中信_個體|Trading",
    ),
}

# GROUP_SYN arithmetic evidence (中信衍生金融工具段)
GROUP_SYN_ARITHMETIC = {
    # 同上,recheck 必須是回傳真值的運算式。
    "衍生金融工具": (
        "中信 202504 Trading: 衍生金融工具段7列相加=56,768,874=附註衍生金融資產",
        "__import__('core.recheck', fromlist=['x']).group_sum_matches('202504_中信_個體|Trading', '衍生金融工具', '衍生金融資產')",
        "202504_中信_個體|Trading",
    ),
}

# Human evidence commits (逐條裁示的 commit)
HUMAN_COMMITS = {
    "國外機構發行債券": {
        "commit": "3d7552e3",
        "message": "decide(v3): 國外機構發行債券 → 公債;人審佇列清空",
        "detail": "commit 3d7552e3: 使用者裁示 — 券號 US9128282A70/US91282CAV37 (CUSIP 912828/91282C = 美國財政部公債)",
    },
    "不動產投資信託受益證券": {
        "commit": "166934fe",
        "message": "feat(v4-T4): 兆豐 REIT 裁示為資產基礎",
        "detail": "commit 166934fe: 使用者裁示 — 名字直譯 REIT,BUCKET_RULES 資產基礎條明列 REITs",
    },
    # 基金受益憑證 (d6ab905): message says 收錄基金受益憑證 but commit diff shows
    # it was added with a rules.propose() reference in the comment → batch 1 (rules evidence)
    # so NOT a human commit for this entry
}

# ── 工具函數 ─────────────────────────────────────────────────────────


def _bucket_rules_revision() -> str:
    return hashlib.sha256(config.BUCKET_RULES.encode("utf-8")).hexdigest()


def _git_log_S(search_str: str) -> list:
    """git log -S 搜尋,回傳 [(short_hash, message)] 清單。"""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-S{search_str}", "--", "buckets.py"],
            capture_output=True, text=True, cwd=_PROJ,
        )
        lines = result.stdout.strip().splitlines()
        return [(line[:7], line[8:]) for line in lines if line]
    except Exception:
        return []


def _count_syn_changed(commit_hash: str) -> int:
    """Count how many SYN entries were added/changed in a commit."""
    try:
        result = subprocess.run(
            ["git", "show", commit_hash, "--", "buckets.py"],
            capture_output=True, text=True, cwd=_PROJ,
        )
        added_lines = [l for l in result.stdout.splitlines()
                       if l.startswith("+") and not l.startswith("+++")
                       and (":" in l) and ("→" not in l) and ("#" not in l)]
        return len(added_lines)
    except Exception:
        return 0


def _is_bulk_commit(commit_hash: str, msg: str) -> bool:
    """判斷是否為批量抄列 commit(一次塞 ≥5 條)。"""
    n = _count_syn_changed(commit_hash)
    if n >= 5:
        return True
    # Also check message pattern
    bulk_patterns = [
        "抄列", "→",  # copy patterns
    ]
    is_progress_msg = any(p in msg for p in ["抄列", "→ 36 格", "→ 34 格",
                                              "→ 31 格", "→ 29 格", "→ 22 格",
                                              "→ 19 格", "→ 17 格", "→ 14 格",
                                              "→ 11 格", "→ 10 格"])
    return is_progress_msg


def _is_human_commit(commit_hash: str, msg: str, name: str) -> bool:
    """判斷是否符合「逐條裁示 commit」的判準(§B1.1)。

    判準:
    - commit 訊息或 diff 指名了這個名字與它的依據;且
    - commit 在 buckets.py 動到的 SYN 條目數 ≤ 2,或訊息是 decide()/人審決定/使用者裁示

    批量抄列 commit(一次塞 ≥5 條)一律不標 human。
    """
    if _is_bulk_commit(commit_hash, msg):
        return False
    # Check if message explicitly names this entry
    explicit_keywords = ["decide(", "人審決定", "使用者裁示", "人工裁示", "裁示"]
    has_explicit = any(k in msg for k in explicit_keywords)
    return has_explicit


# ── 核心遷移邏輯 ──────────────────────────────────────────────────────


def _make_rule_references(name: str, norm_name: str, bucket: str,
                          cells: dict) -> list:
    """為一個 SYN 條目收集所有可用證據。"""
    refs = []

    # ① rule 證據
    proposed_bucket, reason = rules_mod.propose(norm_name)
    if proposed_bucket == bucket:
        recheck = f"rules.propose({norm_name!r})[0] == {bucket!r}"
        refs.append(make_reference(
            kind="rule",
            detail=reason,
            at=NOW,
            recheck=recheck,
        ))

    # ② arithmetic 證據
    if norm_name in ARITHMETIC_EVIDENCE:
        eq_desc, recheck_code, source = ARITHMETIC_EVIDENCE[norm_name]
        # Use multiline recheck as a compact assertion string for storage
        # Wrap in a single exec-able form
        compact_recheck = recheck_code
        refs.append(make_reference(
            kind="arithmetic",
            detail=f"{eq_desc}  [{source}]",
            at=NOW,
            recheck=compact_recheck,
        ))

    # ③ synonym 證據 (from facts)
    for cell_key, recs in cells.items():
        cands = synonyms.candidates(recs)
        for v, a, b in cands:
            kind, why = synonyms.classify(a, b)
            if kind == synonyms.COVERED:
                # Both names known and same bucket
                an = buckets.norm(a)
                bn = buckets.norm(b)
                if an == norm_name or bn == norm_name:
                    other = b if an == norm_name else a
                    refs.append(make_reference(
                        kind="synonym",
                        detail=f"金額={v:,}  {a}={b}  桶={why}  [{cell_key}]",
                        at=NOW,
                        recheck=f"buckets.bucket({{'name': {name!r}}}) == {bucket!r}",
                    ))

    # ④ human 證據(git log -S)
    if name in HUMAN_COMMITS:
        hc = HUMAN_COMMITS[name]
        refs.append(make_reference(
            kind="human",
            detail=hc["detail"],
            at=NOW,
            recheck=None,  # human evidence is one-time, not re-runnable
        ))
    else:
        # Also try git log -S with both literal form and DERIVATIVE/VALUATION_ADJ form
        search_strs = [f'"{name}": "{bucket}"']
        if bucket in ("衍生", "評價調整"):
            const = "DERIVATIVE" if bucket == "衍生" else "VALUATION_ADJ"
            search_strs.append(f'"{name}": {const}')

        for search_str in search_strs:
            commits = _git_log_S(search_str)
            for h, msg in commits:
                if _is_human_commit(h, msg, name):
                    refs.append(make_reference(
                        kind="human",
                        detail=f"commit {h}: {msg}",
                        at=NOW,
                        recheck=None,
                    ))
                    break  # one human commit per name is enough
            if any(r["kind"] == "human" for r in refs):
                break

    return refs


def migrate(cells=None) -> dict:
    """主遷移函數。回傳 {rules: [...], derivations: [], worklist: {...}}。

    **產出 0 條 CONFIRMED。**
    """
    if cells is None:
        cells = facts.load()

    all_rules = []
    batch1_rule_ids = []
    batch2_rules = []
    batch3_rules = []

    # ── SYN 遷移 ─────────────────────────────────────────────────
    for name, bucket in buckets.SYN.items():
        norm_name = buckets.norm(name)
        rule_id = f"tax:{norm_name}"
        refs = _make_rule_references(name, norm_name, bucket, cells)

        # 無法收集到任何證據的條目 → 明確標為「無證據」:references 留空 list,
        # 不假裝有一條 kind="rule" 卻 recheck=None 的可重驗證據(那是說謊)。
        if not refs:
            in_batch3 = True
        else:
            in_batch3 = norm_name in {buckets.norm(n) for n in BATCH3_NO_EVIDENCE}

        rule = make_rule(
            rule_id=rule_id,
            scope="name",
            mapping=bucket,
            state=PROVISIONAL,  # B1 全部 PROVISIONAL
            references=refs,
        )

        # Annotate batch for worklist
        proposed_bucket, _ = rules_mod.propose(norm_name)
        if proposed_bucket == bucket:
            # Batch 1: has rule evidence
            batch1_rule_ids.append(rule_id)
            rule["_worklist_batch"] = 1
        elif norm_name in {buckets.norm(n) for n in BATCH3_NO_EVIDENCE}:
            # Batch 3: no mechanical evidence
            batch3_rules.append(rule)
            rule["_worklist_batch"] = 3
        else:
            # Batch 2: arithmetic/synonym/human
            batch2_rules.append(rule)
            rule["_worklist_batch"] = 2

        all_rules.append(rule)

    # ── GROUP_SYN 遷移 ────────────────────────────────────────────
    for name, bucket in buckets.GROUP_SYN.items():
        norm_name = buckets.norm(name)
        rule_id = f"tax:group:{norm_name}"
        refs = []

        # Rule evidence
        proposed_bucket, reason = rules_mod.propose(norm_name)
        if proposed_bucket == bucket:
            refs.append(make_reference(
                kind="rule",
                detail=reason,
                at=NOW,
                recheck=f"rules.propose({norm_name!r})[0] == {bucket!r}",
            ))

        # Arithmetic evidence for 衍生金融工具
        if norm_name in GROUP_SYN_ARITHMETIC:
            eq_desc, recheck_code, source = GROUP_SYN_ARITHMETIC[norm_name]
            compact_recheck = recheck_code
            refs.append(make_reference(
                kind="arithmetic",
                detail=f"{eq_desc}  [{source}]",
                at=NOW,
                recheck=compact_recheck,
            ))

        if not refs:
            refs = [make_reference(
                kind="rule",
                detail=f"段落規則:GROUP_SYN 中的 {name!r} → {bucket!r}",
                at=NOW,
                recheck=None,
            )]

        rule = make_rule(
            rule_id=rule_id,
            scope="group",
            mapping=bucket,
            state=PROVISIONAL,
            references=refs,
        )
        has_recheck = any(r["recheck"] for r in refs)
        rule["_worklist_batch"] = 1 if has_recheck else 2
        if has_recheck:
            # scope=="group" 且靠可重驗 rule 證據成立 → 真的進第 1 批,
            # 因此也要進 applies_to(F1:批次歸屬修正,原本漏掉這行)
            batch1_rule_ids.append(rule_id)
        all_rules.append(rule)

    # ── GENERIC 遷移 ──────────────────────────────────────────────
    for name in sorted(buckets.GENERIC):
        norm_name = buckets.norm(name)
        rule_id = f"tax:generic:{norm_name}"

        # GENERIC rules: scope="generic", no mapping (they're context-dependent)
        # The bucket is determined by group context, not the name alone
        # As per plan: 'scope="generic" 的布林規則,不帶桶'
        # But SYN has a mapping for them (e.g., 其他 → 其他)
        # Per plan_phaseB §3.4: GENERIC → scope="generic", 不帶桶
        #
        # F2(brief_phaseB_B1fix_ratify §2.3/§F2.1): 這不是 rules.propose() 推得出來的
        # 機械證據,是「這個名字是通稱」的判斷。kind="rule" 配 recheck=None 會讓
        # M3 變成恆真閘門(看起來能重驗,實際上沒有東西可跑)。改用既有的 "group"
        # kind 誠實標記「這是待人工確認的判斷,靠所在段落的 GROUP_SYN 決定」。
        refs = [make_reference(
            kind="group",
            detail=(
                "『其他』是通稱,不自帶會計意義 —— 桶由所在段落的 GROUP_SYN 決定"
                "(BUCKET_RULES「其他:表上真的印著『其他』的列」),非機械可重驗,"
                "待人工確認"
            ),
            at=NOW,
            recheck=None,
        )]

        rule = make_rule(
            rule_id=rule_id,
            scope="generic",
            mapping=None,  # generic 規則不帶桶(plan_phaseB §3.4)
            state=PROVISIONAL,
            references=refs,
        )
        # F1: GENERIC 的 predicate(propose(name)[0]==mapping)對 mapping=None 不成立,
        # 不得進 batch1_rule_ids / applies_to。移到第 2 批,逐條 ratify。
        rule["_worklist_batch"] = 2
        batch2_rules.append(rule)
        all_rules.append(rule)

    return {
        "rules": all_rules,
        "derivations": [],  # B1 不填 derivation,B1.5 才批准
        "batch1_rule_ids": batch1_rule_ids,
        "batch2_rules": batch2_rules,
        "batch3_rules": batch3_rules,
    }


def _build_derivation_proposal(batch1_rule_ids: list) -> dict:
    """建立第 1 批的 Derivation 提案(approved_by/at 留空)。"""
    revision = _bucket_rules_revision()
    predicate = (
        "所有 rule_id 在 applies_to 裡的 rule,rules.propose(norm(name))[0] == mapping，"
        "且 rules.audit(config.BUCKET_RULES) 回傳空清單(無夾帶詞)"
    )
    return make_derivation(
        derivation_id="deriv:BUCKET_RULES-keyword-v1",
        description=(
            "rules.propose(norm(name)) 的桶 == taxonomy 的桶,"
            "且 rules.audit(BUCKET_RULES) 無夾帶詞"
        ),
        predicate=predicate,
        bucket_rules_revision=revision,
        applies_to=sorted(batch1_rule_ids),
        approved_by=None,  # B1.5 填
        approved_at=None,  # B1.5 填
        references=[],  # B1.5 附 human reference
    )


def write_outputs(result: dict, taxonomy_dir: str = "taxonomy",
                  out_dir: str = "out", allow_overwrite: bool = False) -> None:
    """把遷移結果寫到檔案系統。

    寫入前檢查:若既有 taxonomy_dir 已有人工批准過的狀態(任何 CONFIRMED rule,
    或非空 derivations.json),預設拒絕覆寫 —— 重跑遷移不得無聲清掉批准
    (§B1.5 之後,見 brief_phaseB_G §2.6)。要覆寫必須明確傳
    allow_overwrite=True,且先自行備份 taxonomy_dir。
    """
    existing_rules_path = os.path.join(taxonomy_dir, "rules.json")
    existing_deriv_path = os.path.join(taxonomy_dir, "derivations.json")

    if not allow_overwrite:
        existing_confirmed = 0
        if os.path.exists(existing_rules_path):
            with open(existing_rules_path, encoding="utf-8") as f:
                existing_rules = json.load(f)
            existing_confirmed = sum(1 for r in existing_rules if r.get("state") == "CONFIRMED")

        existing_derivations = []
        if os.path.exists(existing_deriv_path):
            with open(existing_deriv_path, encoding="utf-8") as f:
                existing_derivations = json.load(f)

        if existing_confirmed > 0 or existing_derivations:
            raise RuntimeError(
                f"偵測到 {existing_confirmed} 條已批准的 rule / "
                f"{len(existing_derivations)} 條 derivation。"
                f"重跑遷移會覆寫人工批准。若確定要重來,先備份 {taxonomy_dir!r} "
                f"再用 allow_overwrite=True(或 --force)。"
            )

    os.makedirs(taxonomy_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    rules_output = result["rules"]
    derivations_output = result["derivations"]  # Always []

    # Remove internal _worklist_batch key before writing
    rules_clean = []
    for r in rules_output:
        rc = {k: v for k, v in r.items() if not k.startswith("_")}
        rules_clean.append(rc)

    # Write taxonomy/rules.json
    rules_path = os.path.join(taxonomy_dir, "rules.json")
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules_clean, f, ensure_ascii=False, indent=2)
    print(f"Written: {rules_path} ({len(rules_clean)} rules)")

    # Write taxonomy/derivations.json (empty [])
    deriv_path = os.path.join(taxonomy_dir, "derivations.json")
    with open(deriv_path, "w", encoding="utf-8") as f:
        json.dump(derivations_output, f, ensure_ascii=False, indent=2)
    print(f"Written: {deriv_path} (empty)")

    # Build and write ratify_worklist.md
    worklist_path = os.path.join(out_dir, "ratify_worklist.md")
    worklist_md = _build_worklist(result)
    with open(worklist_path, "w", encoding="utf-8") as f:
        f.write(worklist_md)
    print(f"Written: {worklist_path}")


def _build_worklist(result: dict) -> str:
    """Build the ratify_worklist.md content."""
    rules = result["rules"]
    batch1_ids = set(result["batch1_rule_ids"])
    batch3_names = BATCH3_NO_EVIDENCE

    batch1 = [r for r in rules if r.get("_worklist_batch") == 1 and r["scope"] == "name"]
    batch2 = [r for r in rules if r.get("_worklist_batch") == 2 and r["scope"] == "name"]
    batch3 = [r for r in rules if r.get("_worklist_batch") == 3]
    group_rules = [r for r in rules if r["scope"] == "group"]
    generic_rules = [r for r in rules if r["scope"] == "generic"]

    revision = _bucket_rules_revision()
    deriv = _build_derivation_proposal(result["batch1_rule_ids"])

    batch1_total = len(batch1) + len(group_rules)
    batch2_total = len(batch2) + len(generic_rules)

    lines = [
        "# 批准工單 (ratify_worklist.md) — B1 產出",
        "",
        f"> 產出時間: {NOW}",
        f"> **B1 全部產出 PROVISIONAL** (0 條 CONFIRMED) —— 批准是 B1.5 的事",
        "",
        "---",
        "",
        f"## 第 1 批 —— 可重驗 rule 證據 ({len(batch1)} 條 SYN + {len(group_rules)} 條 GROUP_SYN = {batch1_total})",
        "",
        "每條由 `rules.propose(norm(name))` 獨立算出相同的桶 → 批准一條 Derivation 即可。",
        "",
        "| rule_id | 原名 | 桶 | 命中關鍵字 | recheck |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(batch1, key=lambda x: x["rule_id"]):
        rule_refs = [ref for ref in r["references"] if ref["kind"] == "rule"]
        keyword = rule_refs[0]["detail"] if rule_refs else "(無)"
        recheck = rule_refs[0]["recheck"] if rule_refs else "(無)"
        name = r["rule_id"].replace("tax:", "")
        lines.append(f"| `{r['rule_id']}` | {name} | {r['mapping']} | {keyword} | `{recheck}` |")

    # Also include group rules in batch 1
    if group_rules:
        lines.extend(["", "### GROUP_SYN 規則 (scope=group)", ""])
        lines.append("| rule_id | 段落名 | 桶 | 證據 |")
        lines.append("|---|---|---|---|")
        for r in sorted(group_rules, key=lambda x: x["rule_id"]):
            name = r["rule_id"].replace("tax:group:", "")
            evidence = "; ".join(f"{ref['kind']}: {ref['detail'][:60]}" for ref in r["references"])
            lines.append(f"| `{r['rule_id']}` | {name} | {r['mapping']} | {evidence} |")

    # Derivation proposal
    lines.extend([
        "",
        "### 待批准的 Derivation 提案 (第 1 批 → 走 (b) 路徑)",
        "",
        "```json",
        json.dumps(deriv, ensure_ascii=False, indent=2),
        "```",
        "",
        "---",
        "",
        f"## 第 2 批 —— arithmetic/synonym/human 證據 + GENERIC 通稱判斷 ({batch2_total} 條)",
        "",
        "逐條看,證據是硬的,走 (a) 路徑。",
        "",
        "| rule_id | 原名 | 桶 | 證據類型 | 證據說明 |",
        "|---|---|---|---|---|",
    ])
    for r in sorted(batch2, key=lambda x: x["rule_id"]):
        name = r["rule_id"].replace("tax:", "")
        for ref in r["references"]:
            if ref["kind"] in ("arithmetic", "synonym", "human"):
                lines.append(
                    f"| `{r['rule_id']}` | {name} | {r['mapping']} | {ref['kind']} | {ref['detail'][:80]} |"
                )

    # GENERIC rules — 移到第 2 批(§2.2:predicate 對 mapping=None 不成立,
    # 不進 applies_to,逐條 ratify)
    if generic_rules:
        lines.extend(["", "### GENERIC 規則 (scope=generic,逐條 ratify,通稱判斷)", ""])
        lines.append("| rule_id | 名字 | 說明 |")
        lines.append("|---|---|---|")
        for r in sorted(generic_rules, key=lambda x: x["rule_id"]):
            name = r["rule_id"].replace("tax:generic:", "")
            evidence = r["references"][0]["detail"] if r["references"] else "(無)"
            lines.append(f"| `{r['rule_id']}` | {name} | {evidence} |")

    lines.extend([
        "",
        "---",
        "",
        f"## 第 3 批 —— 無任何可重驗機械證據 ({len(batch3)} 條)",
        "",
        "> ⚠️ 這些條目 `rules.propose()` 提不出來,也沒有 arithmetic/synonym 配對。",
        "> **逐條問人**,問不出來就停在 PROVISIONAL。",
        "",
        "| rule_id | 原名 | 桶 | 目前狀態 |",
        "|---|---|---|---|",
    ])
    for r in sorted(batch3, key=lambda x: x["rule_id"]):
        name = r["rule_id"].replace("tax:", "")
        lines.append(f"| `{r['rule_id']}` | {name} | {r['mapping']} | PROVISIONAL (待人工裁示) |")

    lines.extend([
        "",
        "---",
        "",
        "## 統計",
        "",
        f"- 第 1 批 (rule 可重驗,進 applies_to): {len(batch1)} 條 SYN + {len(group_rules)} 條 GROUP_SYN = {batch1_total} 條",
        f"- 第 2 批 (arithmetic/synonym/human + GENERIC 通稱判斷,逐條 ratify,不進 applies_to): "
        f"{len(batch2)} 條 SYN + {len(generic_rules)} 條 GENERIC = {batch2_total} 條",
        f"- 第 3 批 (無機械證據): {len(batch3)} 條",
        f"- 合計: {len(rules)} 條",
        f"- CONFIRMED: 0 條 (依定義,B1.5 才批准)",
        f"- PROVISIONAL: {len(rules)} 條",
        f"- BUCKET_RULES revision: `{revision}`",
    ])

    return "\n".join(lines) + "\n"


def main():
    """B1 遷移主程式。"""
    import argparse
    parser = argparse.ArgumentParser(description="B1 SYN migration")
    parser.add_argument("--taxonomy-dir", default="taxonomy")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                         help="覆寫既有已批准的 taxonomy_dir(先自行備份!)")
    args = parser.parse_args()

    print("B1 migrate_syn: loading facts...")
    cells = facts.load()
    print(f"  Loaded {len(cells)} cells")

    print("Running migration...")
    result = migrate(cells)

    rules_all = result["rules"]
    confirmed_count = sum(1 for r in rules_all if r["state"] == CONFIRMED)
    provisional_count = sum(1 for r in rules_all if r["state"] == PROVISIONAL)

    print(f"\nMigration result:")
    print(f"  Total rules: {len(rules_all)}")
    print(f"  CONFIRMED: {confirmed_count}  (must be 0!)")
    print(f"  PROVISIONAL: {provisional_count}")
    print(f"  Batch 1 (rule): {len(result['batch1_rule_ids'])}")
    print(f"  Batch 2 (arithmetic/synonym/human): {len(result['batch2_rules'])}")
    print(f"  Batch 3 (no evidence): {len(result['batch3_rules'])}")

    if confirmed_count != 0:
        print("ERROR: B1 produced CONFIRMED rules — this violates 鐵則 1!", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        write_outputs(result, args.taxonomy_dir, args.out_dir, allow_overwrite=args.force)
    else:
        print("\n[dry-run] Not writing files.")
        print("\nSample rules:")
        for r in result["rules"][:3]:
            print(f"  {r['rule_id']}: {r['state']} refs={[x['kind'] for x in r['references']]}")


if __name__ == "__main__":
    main()
