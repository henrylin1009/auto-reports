# -*- coding: utf-8 -*-
"""B4:`review/queue.jsonl` 的三種人工處置(`docs/plan_phaseB.md` §5 B4)。

    (a) dispose_confirm      收錄成新科目 → new_rule() + ratify_rule(),
                             該 rule 轉 CONFIRMED
    (b) dispose_reject       退回(不是科目)→ 標記,不再提示
    (c) dispose_manual_expand 這是小計,頁沒找全 → 人工觸發擴頁

**三者都不經 `core.expand_policy`**——那支只管「自動要不要擴頁」,B4 是人在
review 佇列裡看過之後**主動決定**,擴不擴、擴到哪一級都是人工判斷,
所以 `dispose_manual_expand` 直接呼叫 `loc.expand()`,不問 `may_expand()`。
這正是 `expand_policy.py` 檔頭說的「⑤ 分桶失敗不擴頁」的補償出口:
自動路徑放棄的擴頁機會,由人工在這裡拿回來,**不消耗重試預算**
(重試預算是 `core.ingest` 自動迴圈的概念,人工擴頁完全不碰那個計數器)。

三種處置都會把該筆從 `review/queue.jsonl` 移除、寫進
`review/resolved.jsonl` 留審計紀錄(不是刪掉,是移到別的檔案)。
"""
from core import decision_store, ratify as ratify_mod


def _matches(entry, cell_key, occurrence):
    return (entry.get("cell_key") == cell_key
            and (entry.get("decision") or {}).get("occurrence") == occurrence)


def dispose_confirm(cell_key, occurrence, scope, norm_name, mapping,
                    approved_by, approved_at, reason,
                    taxonomy_dir="taxonomy", review_path=None, resolved_path=None):
    """(a) 收錄成新科目。`scope`/`norm_name`/`mapping` 是人工確認後的最終判斷——
    不是自動從 review entry 的候選欄位抄的(候選只是提示,不是答案)。
    """
    rule_id = ratify_mod.new_rule(scope, norm_name, mapping, taxonomy_dir=taxonomy_dir)
    ratify_mod.ratify_rule(rule_id, approved_by, approved_at, reason,
                          taxonomy_dir=taxonomy_dir)
    removed = decision_store.remove_from_review(
        lambda e: _matches(e, cell_key, occurrence), review_path)
    decision_store.append_resolved(
        [{"disposition": "confirm", "cell_key": cell_key, "occurrence": occurrence,
          "rule_id": rule_id, "approved_by": approved_by, "approved_at": approved_at,
          "reason": reason}], resolved_path)
    return {"rule_id": rule_id, "removed": len(removed)}


def dispose_reject(cell_key, occurrence, approved_by, approved_at, reason,
                   review_path=None, resolved_path=None):
    """(b) 退回:不是一個科目(例如小計、頁眉雜訊),標記後不再提示。
    **不動 taxonomy、不動 facts、不動 decisions**——這一列的 Decision
    仍然是 UNCLASSIFIED,只是不再進入待審佇列反覆打擾人。
    """
    removed = decision_store.remove_from_review(
        lambda e: _matches(e, cell_key, occurrence), review_path)
    decision_store.append_resolved(
        [{"disposition": "reject", "cell_key": cell_key, "occurrence": occurrence,
          "approved_by": approved_by, "approved_at": approved_at, "reason": reason}],
        resolved_path)
    return {"removed": len(removed)}


def dispose_manual_expand(cell_key, occurrence, loc, cls, current_pages, next_level,
                          approved_by, approved_at, reason,
                          review_path=None, resolved_path=None):
    """(c) 人工判斷「這是小計,頁沒找全」→ 人工觸發擴頁。

    回傳新頁集合,交給操作者重讀、重抄、resubmit——**重綁不用在這裡處理**,
    B2 的 `_write_facts_and_decisions` 已經用 record_fp/row_fp 五步協定自動
    重綁(record_fp 不含 source_page,不會因為頁碼變了就孤兒化)。
    """
    more = loc.expand(cls, next_level)
    new_pages = sorted(set(current_pages) | set(more))
    removed = decision_store.remove_from_review(
        lambda e: _matches(e, cell_key, occurrence), review_path)
    decision_store.append_resolved(
        [{"disposition": "manual_expand", "cell_key": cell_key, "occurrence": occurrence,
          "new_pages": new_pages, "approved_by": approved_by, "approved_at": approved_at,
          "reason": reason}], resolved_path)
    return {"new_pages": new_pages,
            "added": sorted(set(new_pages) - set(current_pages)),
            "removed": len(removed)}
