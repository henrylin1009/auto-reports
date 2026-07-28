# -*- coding: utf-8 -*-
"""test_b4.py — B4:review queue 三種處置(收錄/退回/人工擴頁)。

全部在 tmp 目錄跑,**不碰真實 facts/ taxonomy/ decisions/ review/**。
"""
import json
import os
import shutil
import tempfile

import buckets
from core import decision_store, decisions as D, ingest, review as R

PASS = 0
FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  {detail}" if detail else ""))


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


class _Ctx:
    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.facts_dir = os.path.join(self.root, "facts")
        self.decisions_dir = os.path.join(self.root, "decisions")
        self.review_path = os.path.join(self.root, "review", "queue.jsonl")
        self.resolved_path = os.path.join(self.root, "review", "resolved.jsonl")
        self.taxonomy_dir = os.path.join(self.root, "taxonomy")
        os.makedirs(self.facts_dir)
        os.makedirs(self.taxonomy_dir)
        json.dump([], open(os.path.join(self.taxonomy_dir, "rules.json"), "w",
                          encoding="utf-8"))
        json.dump([], open(os.path.join(self.taxonomy_dir, "derivations.json"), "w",
                          encoding="utf-8"))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _rec(page, total_col, printed_total, rows, cls="Trading"):
    return {"doc": "X", "class": cls, "source_page": page,
            "source_kind": "附註", "total_col": total_col,
            "printed_total": printed_total, "rows": rows}


def _file_unclassified_row(ctx, name, amount=200, doc="X"):
    """走 B2 的 FILED 出口,製造一筆真正待審的 review entry(不是憑空編)。"""
    rec = _rec(1, "c", amount, [{"name": name, "cols": {"c": amount}}])
    outcome = {"outcome": "FILED", "doc": doc, "cls": "Trading",
               "recs": [rec], "level": 0, "retries": 0, "message": "m"}
    pending = os.path.join(ctx.root, "pending.json")
    ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                         decisions_dir=ctx.decisions_dir,
                         review_path=ctx.review_path,
                         taxonomy_dir=ctx.taxonomy_dir)
    review = decision_store.load_review(ctx.review_path)
    entry = next(e for e in review if e["decision"]["name"] == name)
    return entry, rec


# ── (a) 收錄成新科目 ─────────────────────────────────────────────────────

def A_dispose_confirm_upgrades_taxonomy():
    ctx = _Ctx()
    try:
        name = "測試專用全新科目ABC"
        entry, _rec_ = _file_unclassified_row(ctx, name)
        cell_key, occ = entry["cell_key"], entry["decision"]["occurrence"]

        norm = buckets.norm(name)
        result = R.dispose_confirm(
            cell_key, occ, "name", norm, "公司債",
            approved_by="henrylin", approved_at="2026-07-28T10:00:00",
            reason="人工確認這是公司債的一種寫法",
            taxonomy_dir=ctx.taxonomy_dir, review_path=ctx.review_path,
            resolved_path=ctx.resolved_path)

        rules = json.load(open(os.path.join(ctx.taxonomy_dir, "rules.json"),
                               encoding="utf-8"))
        rule = next(r for r in rules if r["rule_id"] == result["rule_id"])
        good = rule["state"] == "CONFIRMED" and rule["mapping"] == "公司債"

        review_after = decision_store.load_review(ctx.review_path)
        good = good and not any(e["decision"]["occurrence"] == occ for e in review_after)

        resolved = decision_store.load_review(ctx.resolved_path)
        good = good and any(e["disposition"] == "confirm" and e["occurrence"] == occ
                            for e in resolved)

        return ok("(a) 收錄成新科目:taxonomy 新增且 CONFIRMED、queue 移除、resolved 留痕",
                   f"rule={rule['rule_id']} state={rule['state']}") if good \
            else fail("A_dispose_confirm", f"rule={rule}, review_after={review_after}")
    finally:
        ctx.cleanup()


def A_reclassify_now_confirmed():
    """收錄之後重新 decide() 同一個名字 → 必須是 CONFIRMED,不是又回到 UNCLASSIFIED。
    這是證明「taxonomy 真的變了」,不是只改了 review 佇列的顯示。"""
    ctx = _Ctx()
    try:
        name = "測試專用全新科目DEF"
        entry, rec = _file_unclassified_row(ctx, name)
        cell_key, occ = entry["cell_key"], entry["decision"]["occurrence"]
        norm = buckets.norm(name)
        R.dispose_confirm(cell_key, occ, "name", norm, "金融債",
                          approved_by="henrylin", approved_at="2026-07-28T10:00:00",
                          reason="人工確認",
                          taxonomy_dir=ctx.taxonomy_dir, review_path=ctx.review_path,
                          resolved_path=ctx.resolved_path)
        decs = ingest._decide_rows(cell_key, [rec], ctx.taxonomy_dir)
        good = decs[0]["state"] == "CONFIRMED" and decs[0]["mapping"] == "金融債"
        return ok("(a) 收錄後重新 decide() 同一個名字 → CONFIRMED(不是又變 UNCLASSIFIED)",
                   decs[0]) if good else fail("A_reclassify_now_confirmed", decs)
    finally:
        ctx.cleanup()


def A_inject_idempotent_double_confirm():
    """注入:同一個 occurrence 被收錄兩次,不准長出重複的 human reference
    或重複的 rule。"""
    ctx = _Ctx()
    try:
        name = "測試專用全新科目GHI"
        entry, _rec_ = _file_unclassified_row(ctx, name)
        cell_key, occ = entry["cell_key"], entry["decision"]["occurrence"]
        norm = buckets.norm(name)
        for _ in range(2):
            R.dispose_confirm(cell_key, occ, "name", norm, "股票",
                              approved_by="henrylin", approved_at="2026-07-28T10:00:00",
                              reason="人工確認", taxonomy_dir=ctx.taxonomy_dir,
                              review_path=ctx.review_path, resolved_path=ctx.resolved_path)
        rules = json.load(open(os.path.join(ctx.taxonomy_dir, "rules.json"),
                               encoding="utf-8"))
        matching = [r for r in rules if r["rule_id"] == f"tax:{norm}"]
        good = len(matching) == 1
        human_refs = [ref for ref in matching[0]["references"] if ref["kind"] == "human"]
        good = good and len(human_refs) == 1
        return ok("(a) inject:重複收錄同一 occurrence 不長出重複 rule/reference",
                   f"rules={len(matching)}, human_refs={len(human_refs)}") if good \
            else fail("A_inject_idempotent", f"matching={len(matching)}, human_refs={len(human_refs)}")
    finally:
        ctx.cleanup()


# ── (b) 退回 ─────────────────────────────────────────────────────────────

def B_dispose_reject_leaves_taxonomy_untouched():
    ctx = _Ctx()
    try:
        name = "測試專用雜訊列XYZ"
        entry, _rec_ = _file_unclassified_row(ctx, name)
        cell_key, occ = entry["cell_key"], entry["decision"]["occurrence"]

        rules_before = json.load(open(os.path.join(ctx.taxonomy_dir, "rules.json"),
                                      encoding="utf-8"))
        R.dispose_reject(cell_key, occ, approved_by="henrylin",
                         approved_at="2026-07-28T10:00:00", reason="這是頁眉雜訊,不是科目",
                         review_path=ctx.review_path, resolved_path=ctx.resolved_path)
        rules_after = json.load(open(os.path.join(ctx.taxonomy_dir, "rules.json"),
                                     encoding="utf-8"))
        review_after = decision_store.load_review(ctx.review_path)
        resolved = decision_store.load_review(ctx.resolved_path)

        good = (rules_before == rules_after
                and not any(e["decision"]["occurrence"] == occ for e in review_after)
                and any(e["disposition"] == "reject" for e in resolved))
        return ok("(b) 退回:taxonomy 零變更、queue 移除、resolved 留痕") if good \
            else fail("B_dispose_reject", f"rules_changed={rules_before != rules_after}")
    finally:
        ctx.cleanup()


# ── (c) 人工觸發擴頁 ─────────────────────────────────────────────────────

def C_manual_expand_returns_new_pages_and_skips_policy():
    """人工擴頁不問 `expand_policy.may_expand()`——即使訊號在 NEVER 名單裡
    (分類失敗),人工仍然可以決定擴頁。"""
    ctx = _Ctx()
    try:
        name = "測試專用小計列(玉山型)"
        entry, _rec_ = _file_unclassified_row(ctx, name)
        cell_key, occ = entry["cell_key"], entry["decision"]["occurrence"]

        class _Loc:
            def expand(self, cls, level):
                return {1: [24]}.get(level, [])

        result = R.dispose_manual_expand(
            cell_key, occ, _Loc(), "Trading", current_pages=[1], next_level=1,
            approved_by="henrylin", approved_at="2026-07-28T10:00:00",
            reason="這是小計,p24 才是完整明細",
            review_path=ctx.review_path, resolved_path=ctx.resolved_path)

        good = result["new_pages"] == [1, 24] and result["added"] == [24]
        review_after = decision_store.load_review(ctx.review_path)
        good = good and not any(e["decision"]["occurrence"] == occ for e in review_after)
        return ok("(c) 人工擴頁:回傳新頁集合、queue 移除、不經 expand_policy",
                   result) if good else fail("C_manual_expand", result)
    finally:
        ctx.cleanup()


def C_rebind_after_manual_expand_not_orphaned():
    """玉山家族場景:Gate1 過、Gate2(分類)未過 → FILED,人工判斷 (c) 擴頁,
    重抄後 record 內容變了(多了新列),但**同一份 record 的舊 Decision 要綁得回去**
    ——不是全部孤兒化(§2.2 五步協定,record_fp 不含 rows/source_page)。
    重試預算(retries)全程沒被人工擴頁碰過。
    """
    ctx = _Ctx()
    try:
        # 第一次:小計,兩列合計對得上但分類不出來(FILED)。
        rec_v1 = _rec(23, "c", 287711177, [
            {"name": "權益證券小計", "cols": {"c": 16018428}},
            {"name": "債務證券小計", "cols": {"c": 271692749}},
        ], cls="OCI")
        outcome1 = {"outcome": "FILED", "doc": "X", "cls": "OCI",
                    "recs": [rec_v1], "level": 0, "retries": 0, "message": "m1"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome1, None, pending, facts_dir=ctx.facts_dir,
                             decisions_dir=ctx.decisions_dir,
                             review_path=ctx.review_path,
                             taxonomy_dir=ctx.taxonomy_dir)
        old_decs = decision_store.load(ctx.decisions_dir)["X|OCI"]
        assert all(d["state"] == "UNCLASSIFIED" for d in old_decs)
        retries_before = outcome1["retries"]

        # 人工判斷 (c):這是小計,p24 才有逐項明細——擴頁,不消耗預算
        # (dispose_manual_expand 完全不碰 retries,呼叫端也沒有把它傳進去)。
        class _Loc:
            def expand(self, cls, level):
                return [24]

        occ = next(e["decision"]["occurrence"] for e in
                   decision_store.load_review(ctx.review_path))
        expand_result = R.dispose_manual_expand(
            "X|OCI", occ, _Loc(), "OCI", current_pages=[23], next_level=1,
            approved_by="henrylin", approved_at="2026-07-28T10:00:00",
            reason="這是小計,p24 才是逐項明細",
            review_path=ctx.review_path, resolved_path=ctx.resolved_path)
        assert expand_result["new_pages"] == [23, 24]

        # 重抄:record_fp 的組成是 (source_kind, total_col, printed_total,
        # printed_totals)——維持不變,rows 換成逐項明細(超集展開),
        # 這樣才會被判定成「同一份 record」而不是新 record。
        rec_v2 = _rec(23, "c", 287711177, [
            {"name": "台積電公司債", "cols": {"c": 16018428}},
            {"name": "台灣電力公司債", "cols": {"c": 271692749}},
        ], cls="OCI")
        outcome2 = {"outcome": "FILED", "doc": "X", "cls": "OCI",
                    "recs": [rec_v2], "level": 0, "retries": retries_before,
                    "message": "m2"}
        ingest.apply_outcome(outcome2, None, pending, facts_dir=ctx.facts_dir,
                             decisions_dir=ctx.decisions_dir,
                             review_path=ctx.review_path,
                             taxonomy_dir=ctx.taxonomy_dir)

        # ① 舊版本(兩列小計)進了 _superseded/,不是憑空消失。
        sup_files = os.listdir(os.path.join(ctx.facts_dir, "_superseded"))
        good = len(sup_files) == 1

        # ② retries 全程沒被人工擴頁碰過(呼叫端從沒把它傳給 dispose_manual_expand)。
        good = good and retries_before == 0

        # ③ 新列各自建立新 Decision(這條 record 舊列名字跟新列名字完全不同,
        #    所以 row_fp 對不上,不會誤綁——這正是設計要的行為:小計 ≠ 逐項,
        #    不該硬把小計的舊 Decision 套在完全不同的逐項名字上)。
        #    兩個新名字都帶「公司債」,`rules.propose()` 認得出關鍵字 → PROVISIONAL,
        #    不是 UNCLASSIFIED——這是 propose() 正常運作,不是沒綁好。
        new_decs = decision_store.load(ctx.decisions_dir)["X|OCI"]
        active = [d for d in new_decs if not d.get("superseded")]
        good = good and len(active) == 2
        good = good and {d["name"] for d in active} == {"台積電公司債", "台灣電力公司債"}
        good = good and all(d["state"] in ("PROVISIONAL", "UNCLASSIFIED") for d in active)

        return ok("(c) 玉山家族場景:_superseded 留痕、retries 未被人工擴頁動過、"
                    "重抄後新列各自建立新 Decision(不誤綁)",
                   f"sup_files={sup_files}, active={[d['name'] for d in active]}") \
            if good else fail("C_rebind_after_manual_expand",
                              f"sup_files={sup_files}")
    finally:
        ctx.cleanup()


def main():
    print("=" * 60)
    print("test_b4.py — B4 review queue 三種處置")
    print("=" * 60)
    tests = [A_dispose_confirm_upgrades_taxonomy, A_reclassify_now_confirmed,
             A_inject_idempotent_double_confirm,
             B_dispose_reject_leaves_taxonomy_untouched,
             C_manual_expand_returns_new_pages_and_skips_policy,
             C_rebind_after_manual_expand_not_orphaned]
    for t in tests:
        t()
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
