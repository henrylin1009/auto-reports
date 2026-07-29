# -*- coding: utf-8 -*-
"""C3-a:把 `fill.cmd_submit` 的判斷與路由搬到這裡。**兩個函式,職責分開**:

    classify_outcome(...)  純判斷,不寫任何檔案。回傳 {outcome, message, ...}。
    apply_outcome(...)     把 classify_outcome 的結論落地(寫 facts/ / blocked/ /
                            rejected/ / pending)。

`fill.py` 保留原地繼續能跑 —— 本檔是**平行**的第二個實作,靠
`test_ingest_equiv.py` 的 E5 閘門證明兩者等價(見 docs/brief_C3a_ingest.md)。

A1(預設 `use_policy=False`):行為與 `fill.cmd_submit` 逐字相同 ——
`_taxonomy_gap()` 有料才 BLOCKED,其餘一律 level+1 擴頁。

A2(`use_policy=True`):改用 `core.expand_policy.may_expand()` /
`consumes_budget()` 決定要不要擴頁 / 消耗預算。**這是本檔唯一的行為改變**,
判準一律呼叫 `core.expand_policy`,不在這裡另寫一份觸發判斷(I3)。

⚠️ §1.2:`transcribe.verify()` 的回傳鍵是嵌了頁碼的顯示字串,不准字串比對推
「哪一道失敗」。`_structured_checks()` 直接呼叫個別 `check_*` 函式組出結構化
結果,並且與 `verify()` 的 pass/fail 結論同進同出(I2,見 `consistent_with_verify`)。

── B2:兩道閘門(`plan_phaseB.md` §4)──────────────────────────────────

`expand_policy.TRIGGERS` = {source, check_identity, check_anchor, check_col_totals}
正好就是 **Gate 1(存檔閘門)**;`expand_policy.NEVER` = {check_buckets, check_cross}
正好就是 **Gate 2(發布閘門)**。兩道閘門的邊界本來就寫在 `core/expand_policy.py`
裡,B2 沒有另外發明分界,只是把「Gate 1 過了就寫進 facts/,不管分不分得出桶」
這件事接上:

    `use_policy=True` 且 `may_expand()` 判定「不擴頁」(= Gate 1 全過、
    只有 Gate 2 訊號失敗)→ 新出口 **FILED**:
        寫進 facts/(跟 PASS 一樣)
        用 `core.decisions.decide()` 對每一列產生 Decision,寫進 decisions/
        非 CONFIRMED 的列進 review/queue.jsonl
        **不擴頁、不消耗重試預算、不丟棄 raw facts**(I1)

FILED 與 PASS 的差別只在於 Gate 2 是否全過;兩者都會走同一段「寫 facts +
建 Decision」邏輯(`_apply_filed_common`),PASS 只是 Gate 2 也一起過了的特例。
"""
import datetime

import buckets
import facts
import transcribe
from core import decision_store, decisions as decisions_mod, expand_policy

#: 結構化檢查名 —— 給 `core.expand_policy` 用的訊號集合(I3 的唯一來源仍是
#: `expand_policy.TRIGGERS`/`NEVER`,這裡只是「怎麼把 rec 轉成失敗訊號」)。
_CHECK_NAMES = ("check_identity", "check_anchor", "check_buckets", "check_col_totals")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")


def _key(doc, cls):
    return f"{doc}|{cls}"


def _load_rules_by_name(taxonomy_dir="taxonomy"):
    """taxonomy/rules.json → `core.decisions.decide()` 要吃的 `rules_by_name`
    形狀(照抄 `test_decide_equiv.py._load_rules_by_name`,B1 就已經定案的
    key 慣例:name scope 用裸的 norm_name,group/generic 各自加前綴)。"""
    import json
    import os
    path = os.path.join(taxonomy_dir, "rules.json")
    if not os.path.exists(path):
        return {}
    all_rules = json.load(open(path, encoding="utf-8"))
    rules_by_name = {}
    for r in all_rules:
        rule_id = r["rule_id"]
        if r["scope"] == "name":
            rules_by_name[rule_id.replace("tax:", "", 1)] = r
        elif r["scope"] == "group":
            rules_by_name[f"group:{rule_id.replace('tax:group:', '', 1)}"] = r
        elif r["scope"] == "generic":
            rules_by_name[f"generic:{rule_id.replace('tax:generic:', '', 1)}"] = r
    return rules_by_name


def _decide_row(key, rec, row, idx, rules_by_name):
    """對單一列跑 `decisions.decide()`,補上 occurrence 與 locator。"""
    import rules as rules_mod
    dec = decisions_mod.decide(row, row.get("group"), rules_by_name, rules_mod.propose)
    dec["occurrence"] = decisions_mod.occurrence(key, rec, "row", ordinal=idx, row=row)
    dec["locator"] = decisions_mod.locator(key, rec["source_page"], idx)
    return dec


def _decide_rows(key, recs, taxonomy_dir="taxonomy"):
    """對這一批 record 的每一列跑 `decide()`,回傳 Decision 清單。"""
    rules_by_name = _load_rules_by_name(taxonomy_dir)
    out = []
    for rec in recs:
        for idx, row in enumerate(rec["rows"]):
            out.append(_decide_row(key, rec, row, idx, rules_by_name))
    return out


def backfill_decisions(cells, decisions_dir=None, taxonomy_dir="taxonomy", review_path=None):
    """對**還沒有 decisions/ 紀錄**的既有 facts 格,補算一次 Decision + review 佇列。

    B2 上線前就已經在 `facts/` 裡的格子(今天是全部 36 格)從沒被 `apply_outcome`
    處理過,`decisions/` 裡沒有它們的紀錄——不是因為它們特別,只是因為 B2/ingest
    這套機制在它們被抄錄的當下還不存在。這支把缺口補上,讓 `core/jobs.py` 的
    `decide` 步驟與 `core/workbench.py` 的 Review 頁對它們有意義。

    **只補沒有的,不重算已有的**——已經有 decisions 紀錄的格,可能經過 B2 的
    supersede/rebind 流程,這支不准覆蓋掉那段歷史。要更新既有格的 Decision,
    走 ingest 正常流程(重抄 + apply_outcome),不是這支。

    回傳補了幾格。
    """
    existing = decision_store.load(decisions_dir)
    dcells = dict(existing)
    review_entries = []
    filled = 0
    for key, recs in cells.items():
        if key in existing:
            continue
        decs = _decide_rows(key, recs, taxonomy_dir)
        dcells[key] = decs
        review_entries += [{"cell_key": key, "decision": d} for d in decs
                           if d.get("state") != decisions_mod.CONFIRMED]
        filled += 1
    if filled:
        decision_store.save(dcells, decisions_dir)
        decision_store.append_review(review_entries, review_path)
    return filled


def _supersede_old(key, old_recs, facts_dir):
    """把被覆寫的舊 record 移進 `facts/_superseded/{doc}__{cls}__{n}.json`,
    **不刪**——`plan_phaseB.md` §4.3 的覆寫保護,不得因分類未知或重抄而丟失
    raw facts。`n` 遞增避開既有檔,同一格重抄多次每次都留一份歷史。"""
    import json
    import os
    doc, cls = key.split("|", 1)
    sup_dir = os.path.join(facts_dir, "_superseded")
    os.makedirs(sup_dir, exist_ok=True)
    n = 0
    while os.path.exists(os.path.join(sup_dir, f"{doc}__{cls}__{n}.json")):
        n += 1
    path = os.path.join(sup_dir, f"{doc}__{cls}__{n}.json")
    json.dump(old_recs, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    return path


def _write_facts_and_decisions(key, recs, retries, level, facts_dir=None,
                                decisions_dir=None, review_path=None,
                                taxonomy_dir="taxonomy", via="claude-code"):
    """B2 核心:寫 facts/(含覆寫保護 + 重綁)+ decisions/ + review 佇列。

    PASS 與 FILED **共用這段**——兩者差別只在 Gate 2(分類/互對)是否全過,
    落地邏輯完全相同。回傳 {"decisions": [...], "review_added": int}。
    """
    orig_facts_dir = facts.DIR
    if facts_dir is not None:
        facts.DIR = facts_dir
    try:
        cells = facts.load()
        old_recs = cells.get(key)
        for r in recs:
            # `via` 是**誰抄的**,不是裝飾:人工(claude-code)與自動(gemini/claude-p)
            # 混在 facts/ 裡卻分不開,之後就沒辦法回答「模型抄的那批品質如何」。
            r["_by"] = {"at": _now(), "retries": retries, "level": level,
                        "via": via}

        if old_recs:
            # 重抄覆寫:先存歷史,再用 record_fp/row_fp 五步協定重綁(§2.2)。
            _supersede_old(key, old_recs, facts.DIR)
            old_decisions = decision_store.load(decisions_dir).get(key, [])
            rb = decisions_mod.rebind(old_decisions, recs)
            final_decisions = list(rb["bound"]) + list(rb["superseded"])
            rules_by_name = _load_rules_by_name(taxonomy_dir)
            for item in rb["new"]:
                row, rec = item["row"], item["rec"]
                idx = rec["rows"].index(row)
                final_decisions.append(_decide_row(key, rec, row, idx, rules_by_name))
        else:
            final_decisions = _decide_rows(key, recs, taxonomy_dir)

        cells[key] = recs
        facts.save(cells)
    finally:
        facts.DIR = orig_facts_dir

    dcells = decision_store.load(decisions_dir)
    dcells[key] = final_decisions
    decision_store.save(dcells, decisions_dir)

    # 非 CONFIRMED(且非 superseded 的歷史紀錄)才需要人審。
    review_entries = [{"cell_key": key, "decision": dec} for dec in final_decisions
                       if dec.get("state") != decisions_mod.CONFIRMED
                       and not dec.get("superseded")]
    added = decision_store.append_review(review_entries, review_path)
    return {"decisions": final_decisions, "review_added": added}


def _taxonomy_gap(recs, loc):
    """搬自 `fill._taxonomy_gap`(平行實作,不是 import)。行為逐字相同 ——
    見 fill.py 內同名函式的完整說明,這裡不重複貼落落長的註解。"""
    import rules

    unknown = {row["name"] for rec in recs for row in rec["rows"]
               if buckets.bucket(row) is None}
    if not unknown:
        return None

    props = []
    for name in sorted(unknown):
        if buckets.pending({"name": name}):
            return None
        b, why = rules.propose(buckets.norm(name))
        if b is None:
            return None
        props.append({"name": name, "bucket": b, "why": why})

    saved = dict(buckets._SYN_N)
    try:
        buckets._SYN_N.update({buckets.norm(p["name"]): p["bucket"] for p in props})
        ok, _ = transcribe.verify(recs, loc)
    finally:
        buckets._SYN_N.clear()
        buckets._SYN_N.update(saved)
    return props if ok else None


def _structured_checks(recs, loc, pages):
    """對每份 record 個別呼叫 check_* 函式,組出結構化的 {檢查名: 訊息 or None}
    清單,以及匯總出的失敗檢查名集合(給 A2 的 `expand_policy` 用)。

    §1.2:`source` 不是 `transcribe` 裡的既有檢查 —— 它是 ingest 自己判的:
    `source_page` 在不在這一輪的候選頁集合內。"""
    per_rec = []
    failed = set()
    for rec in recs:
        entry = {
            "source_page": rec["source_page"],
            "source": (None if rec["source_page"] in pages
                       else f"來源頁 p{rec['source_page']} 不在候選頁集合 {pages} 內"),
            "check_identity": transcribe.check_identity(rec),
            "check_anchor": transcribe.check_anchor(rec, loc),
            "check_buckets": transcribe.check_buckets(rec, buckets),
            "check_col_totals": (transcribe.check_col_totals(rec)
                                  if rec.get("printed_totals") else None),
        }
        per_rec.append(entry)
        for name in ("source",) + _CHECK_NAMES:
            if entry[name]:
                failed.add(name)
    cross = transcribe.check_cross(recs, buckets) if len(recs) >= 2 else None
    if _is_hard(cross):
        failed.add("check_cross")
    return per_rec, cross, failed


def _is_hard(v):
    """跟 `transcribe.verify()` 判「算不算失敗」用同一套排除規則 ——
    NA_* 與 PARTIAL 開頭都不算硬失敗。"""
    if not v:
        return False
    if v in (transcribe.NA_SINGLE, transcribe.NA_BASIS, transcribe.NA_NO_COL_TOTAL):
        return False
    return not v.startswith(transcribe.PARTIAL)


def consistent_with_verify(recs, loc, pages):
    """I2:結構化檢查結果的 pass/fail 結論,與 `transcribe.verify()` 的結論
    必須同進同出。回傳 (structured_ok, verify_ok) 給呼叫端自己斷言相等。
    **不含 `source`**——`verify()` 本來就不測 source,不能拿它來比。"""
    per_rec, cross, _failed = _structured_checks(recs, loc, pages)
    structured_hard = any(_is_hard(e[name]) for e in per_rec for name in _CHECK_NAMES)
    structured_hard = structured_hard or _is_hard(cross)
    verify_ok, _res = transcribe.verify(recs, loc)
    return (not structured_hard), verify_ok


def classify_outcome(doc, cls, recs, loc, level, pages, retries, max_level,
                      use_policy=False):
    """純判斷,不寫任何檔案。回傳 dict,至少含 `outcome` 與 `message`。

    `use_policy=False`(A1):完全複刻 `fill.cmd_submit`——`_taxonomy_gap()` 有料
    才 BLOCKED,其餘一律 level+1 擴頁,直到 `max_level` 或擴不出新頁才 REJECT。

    `use_policy=True`(A2):`_taxonomy_gap()` 仍然優先(BLOCKED 判準不變),
    其餘失敗改問 `core.expand_policy.may_expand()`——不在白名單裡的失敗
    (⑤ 分桶、③ 混合訊號)一律不擴頁、不消耗預算,直接進 REJECT(交人審)。
    """
    key = _key(doc, cls)
    ok, reason, res, problems = False, "抄不出來(records 為空)", {}, None
    if recs:
        problems = facts.validate({key: recs})
        if problems:
            reason = "; ".join(problems)
        else:
            ok, res = transcribe.verify(recs, loc)
            if not ok:
                reason = "; ".join(f"{k}:{v}" for k, v in res.items() if v)

    if ok:
        return {"outcome": "PASS", "doc": doc, "cls": cls, "recs": recs,
                "level": level, "retries": retries, "res": res,
                "message": f"PASS      已歸檔進 facts/{doc}.json({cls})。"}

    gap = _taxonomy_gap(recs, loc) if recs and not problems else None
    if gap:
        return {"outcome": "BLOCKED", "doc": doc, "cls": cls, "reason": reason,
                "level": level, "gap": gap, "retries": retries, "data": None,
                "message": (
                    "BLOCKED   這格卡在**分類表缺口**,不是你抄錯 —— "
                    "擴頁修不好這種失敗,所以不擴了。")}

    failed_names = None
    why = None
    if use_policy and recs and not problems:
        _per_rec, _cross, failed_names = _structured_checks(recs, loc, pages)
        may, why = expand_policy.may_expand(failed_names)
        consumes = expand_policy.consumes_budget(failed_names)
    else:
        may, consumes = True, True

    if not may:
        # B2:`may_expand` 判「不擴頁」精確等於「Gate 1(TRIGGERS)全過、
        # 只有 Gate 2(NEVER:分類/互對)訊號失敗」——這正是 B2 要接的東西:
        # Gate 1 過了就寫 facts/,不因分類未知而丟棄、不擴頁、不消耗預算(I1)。
        return {"outcome": "FILED", "doc": doc, "cls": cls, "recs": recs,
                "level": level, "retries": retries, "why": why,
                "failed_checks": sorted(failed_names) if failed_names else [],
                "message": (f"FILED     Gate 1(來源/算術)通過,Gate 2(分類/互對)"
                            f"未過 —— 已歸檔進 facts/{doc}.json({cls}),"
                            f"進 review 佇列,不擴頁不消耗預算。")}

    new_level = level + 1
    more = loc.expand(cls, new_level) if new_level <= max_level else []
    new_pages = sorted(set(pages) | set(more))

    if new_level > max_level or not more or new_pages == pages:
        return {"outcome": "REJECT", "doc": doc, "cls": cls, "reason": reason,
                "level": new_level - 1, "retries": retries, "why": why,
                "message": (f"REJECT    擴張到上限仍對不上,"
                            f"已進 work/rejected/{doc}__{cls}.json。")}

    new_retries = retries + (1 if consumes else 0)
    added = sorted(set(new_pages) - set(pages))
    return {"outcome": "RETRY", "doc": doc, "cls": cls, "reason": reason,
            "level": new_level, "pages": new_pages, "retries": new_retries,
            "added": added, "why": why,
            "message": f"RETRY     沒過:{reason}"}


def apply_outcome(outcome, data, pending_path, facts_dir=None, work_dir="work",
                  decisions_dir=None, review_path=None, taxonomy_dir="taxonomy",
                  via="claude-code"):
    """把 `classify_outcome` 的結論落地。**呼叫端負責決定要不要呼叫這個
    函式**——測試只驗 `classify_outcome` 時完全不必碰檔案系統。

    `facts_dir`/`decisions_dir`/`review_path` 給測試用(tmp 路徑);省略時
    走各模組預設路徑。
    """
    import glob
    import json
    import os

    work_dir = work_dir
    rejected_dir = f"{work_dir}/rejected"
    blocked_dir = f"{work_dir}/blocked"
    proposals = f"{work_dir}/proposals.jsonl"

    kind = outcome["outcome"]
    doc, cls = outcome["doc"], outcome["cls"]

    if kind in ("PASS", "FILED"):
        # B2:PASS(Gate1+Gate2 全過)與 FILED(只過 Gate1)共用同一段落地邏輯——
        # 見 `_write_facts_and_decisions`。差別只在印出來的訊息不同。
        result = _write_facts_and_decisions(
            _key(doc, cls), outcome["recs"], outcome["retries"], outcome["level"],
            facts_dir=facts_dir, decisions_dir=decisions_dir,
            review_path=review_path, taxonomy_dir=taxonomy_dir, via=via)
        if os.path.exists(pending_path):
            os.remove(pending_path)
        print(outcome["message"])
        if kind == "FILED" and result["review_added"]:
            print(f"          {result['review_added']} 筆進 review 佇列(待人審)。")
        print("下一步:python3 fill.py next")
        return

    if kind == "BLOCKED":
        os.makedirs(blocked_dir, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": outcome["reason"],
                   "level": outcome["level"], "proposals": outcome["gap"],
                   "submitted": data},
                  open(f"{blocked_dir}/{doc}__{cls}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        seen = set()
        if os.path.exists(proposals):
            seen = {json.loads(l)["name"] for l in open(proposals, encoding="utf-8")
                    if l.strip()}
        with open(proposals, "a", encoding="utf-8") as f:
            for g in outcome["gap"]:
                if g["name"] not in seen:
                    seen.add(g["name"])
                    f.write(json.dumps({**g, "key": _key(doc, cls), "at": _now()},
                                       ensure_ascii=False) + "\n")
        if os.path.exists(pending_path):
            os.remove(pending_path)
        print(outcome["message"])
        for g in outcome["gap"]:
            print(f"          未收錄:「{g['name']}」→ 建議「{g['bucket']}」({g['why']})")
        print(f"          提案已寫入 {proposals},請使用者審核後收錄進 buckets.SYN,")
        print(f"          再跑 python3 fill.py requeue 把這格放回佇列。")
        print("下一步:python3 fill.py next(先做別格,不要停在這裡)")
        return

    if kind == "REJECT":
        os.makedirs(rejected_dir, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": outcome["reason"],
                   "level": outcome["level"], "submitted": data},
                  open(f"{rejected_dir}/{doc}__{cls}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        if os.path.exists(pending_path):
            os.remove(pending_path)
        print(outcome["message"])
        print(f"          理由:{outcome['reason']}")
        print("下一步:python3 fill.py next")
        return

    if kind == "RETRY":
        json.dump({"doc": doc, "cls": cls, "level": outcome["level"],
                   "pages": outcome["pages"], "retries": outcome["retries"]},
                  open(pending_path, "w", encoding="utf-8"))
        print(outcome["message"])
        print(f"          已擴張加入鄰頁 {outcome['added']}。")
        print("下一步:重讀下面的頁再抄一次,寫回 work/current.json,"
              "再跑 python3 fill.py submit work/current.json(不要跳過,不要回 next)")
        return

    raise ValueError(f"未知 outcome: {kind!r}")
