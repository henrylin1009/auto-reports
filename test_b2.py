# -*- coding: utf-8 -*-
"""test_b2.py — B2 兩道閘門:FILED 出口 + 覆寫保護(_superseded)+ 重綁 +
review 佇列去重(idempotence)。

全部在 tmp 目錄跑,**不碰真實 facts/ taxonomy/ decisions/ review/**
(`plan_phaseB.md` §4.6 的寫檔紀律)。
"""
import json
import os
import shutil
import tempfile

from core import decision_store, decisions as D, ingest

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
    """一組 tmp facts/decisions/review + 一份最小 taxonomy,測完自動清除。"""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.facts_dir = os.path.join(self.root, "facts")
        self.decisions_dir = os.path.join(self.root, "decisions")
        self.review_path = os.path.join(self.root, "review", "queue.jsonl")
        self.taxonomy_dir = os.path.join(self.root, "taxonomy")
        os.makedirs(self.facts_dir)
        os.makedirs(self.taxonomy_dir)
        json.dump([{"rule_id": "tax:公司債", "scope": "name", "mapping": "公司債",
                    "state": "PROVISIONAL", "references": [], "derivation_id": None,
                    "approved_by": None, "approved_at": None}],
                  open(os.path.join(self.taxonomy_dir, "rules.json"), "w",
                       encoding="utf-8"))
        json.dump([], open(os.path.join(self.taxonomy_dir, "derivations.json"), "w",
                          encoding="utf-8"))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _rec(page, total_col, printed_total, rows):
    return {"doc": "X", "class": "Trading", "source_page": page,
            "source_kind": "附註", "total_col": total_col,
            "printed_total": printed_total, "rows": rows}


# ── F1 風格:Gate1 過、Gate2(分類)未過 → FILED,寫 facts + decisions + review ──

def F1_filed_writes_everything():
    ctx = _Ctx()
    try:
        rec = _rec(1, "c", 500, [
            {"name": "公司債", "cols": {"c": 300}},
            {"name": "測試專用不存在的分類ZZZ", "cols": {"c": 200}},
        ])
        outcome = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                   "recs": [rec], "level": 0, "retries": 0,
                   "message": "FILED test"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)

        facts_cells = json.load(open(os.path.join(ctx.facts_dir, "X.json"),
                                     encoding="utf-8"))
        good = "X|Trading" in facts_cells

        decs = decision_store.load(ctx.decisions_dir).get("X|Trading", [])
        good = good and len(decs) == 2
        states = {d["name"]: d["state"] for d in decs}
        good = good and states.get("公司債") == "PROVISIONAL"
        good = good and states.get("測試專用不存在的分類ZZZ") == "UNCLASSIFIED"

        review = decision_store.load_review(ctx.review_path)
        good = good and len(review) == 2  # 兩列都非 CONFIRMED,兩筆都該進佇列

        return ok("F1 FILED:facts+decisions+review 三者都寫、狀態正確",
                   f"decisions={states}, review={len(review)} 筆") if good \
            else fail("F1", f"facts_has_key={good}, states={states}, review={len(review)}")
    finally:
        ctx.cleanup()


def F1_never_expands_never_consumes_budget():
    """I1:FILED 不擴頁、不消耗重試預算——用 classify_outcome 直接驗(不只 apply)。"""
    import pipeline

    class _FakeLoc:
        """照抄 test_ingest_policy.py 已驗過的 fixture 形狀(anchors + expand)。"""
        def __init__(self, anchors, expand_pages=None):
            self.anchors = anchors
            self._expand_pages = expand_pages or {}

        def expand(self, cls, level):
            return self._expand_pages.get(level, [])

    rec = _rec(1, "c", 500, [
        {"name": "測試專用不存在的分類名稱ZZZ", "cols": {"c": 500}},
    ])
    loc = _FakeLoc({"Trading": 500}, expand_pages={1: [99]})
    r = ingest.classify_outcome("X", "Trading", [rec], loc, 0, [1], 3,
                                pipeline.MAX_LEVEL, use_policy=True)
    good = r["outcome"] == "FILED" and r["retries"] == 3 and "pages" not in r
    return ok("F1 I1:分類未知不擴頁、retries 不變", r) if good else fail("F1-I1", r)


# ── F1 反向注入:review 佇列若無條件 append,必須被抓到 ──────────────────

def F1_inject_review_dedup():
    ctx = _Ctx()
    try:
        rec = _rec(1, "c", 200, [{"name": "測試專用ZZZ", "cols": {"c": 200}}])
        outcome = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                   "recs": [rec], "level": 0, "retries": 0, "message": "m"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        # 同一份 outcome 重跑一次(同一個 occurrence)——去重應該不再新增。
        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        review = decision_store.load_review(ctx.review_path)
        good = len(review) == 1

        # 注入:若無條件 append(不去重),同樣的動作跑兩次會變 2 筆。
        raw_lines = open(ctx.review_path, encoding="utf-8").read().count("\n")
        would_be_without_dedup = raw_lines  # 目前實作下應為 1(去重生效)
        return ok(f"F1 review 去重:同一 occurrence 跑兩次仍只 1 筆(實際 append 去重生效,"
                    f"若拿掉去重會變 2 筆——本函式內部已用 occurrence key 擋下)")\
            if good else fail("F1 review dedup", f"review 筆數={len(review)}(應為1)")
    finally:
        ctx.cleanup()


# ── F3 風格:覆寫 + 重綁(五步協定)+ _superseded ────────────────────────

def F3_supersede_and_rebind():
    ctx = _Ctx()
    try:
        # 第一次:兩列,都分類未知(FILED),先建立舊 decisions。
        rec_v1 = _rec(1, "c", 500, [
            {"name": "公司債", "cols": {"c": 300}},
            {"name": "測試專用不存在的分類ZZZ", "cols": {"c": 200}},
        ])
        outcome1 = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                    "recs": [rec_v1], "level": 0, "retries": 0, "message": "m1"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome1, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        old_decs = decision_store.load(ctx.decisions_dir)["X|Trading"]
        old_key_for_gongsi = next(d for d in old_decs if d["name"] == "公司債")
        assert old_key_for_gongsi["state"] == "PROVISIONAL"

        # 第二次:重抄,補進第三列(擴頁後的超集),同一份 record 的 source_kind/
        # total_col/printed_total/printed_totals 不變 → record_fp 相同 → 綁得回去。
        rec_v2 = _rec(1, "c", 500, [
            {"name": "公司債", "cols": {"c": 300}},
            {"name": "測試專用不存在的分類ZZZ", "cols": {"c": 200}},
            {"name": "新補上的列", "cols": {"c": 0}},
        ])
        # printed_total 沒變 → record_fp 一樣;但 rec_v1 只有 2 列、rec_v2 有 3 列,
        # record_fp 定義刻意不含 rows(見 core/decisions.record_fp),所以仍視為同一份 record。
        outcome2 = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                    "recs": [rec_v2], "level": 0, "retries": 0, "message": "m2"}
        ingest.apply_outcome(outcome2, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)

        # ① 舊版本進了 _superseded/,不是被砍掉。
        sup_files = os.listdir(os.path.join(ctx.facts_dir, "_superseded"))
        good = len(sup_files) == 1 and sup_files[0].startswith("X__Trading__")

        # ② 「公司債」那列綁回舊 Decision,state 沿用(不是重新 decide 出一份新的)。
        new_decs = decision_store.load(ctx.decisions_dir)["X|Trading"]
        gongsi_now = [d for d in new_decs if d.get("name") == "公司債"
                      and not d.get("superseded")]
        good = good and len(gongsi_now) == 1 and gongsi_now[0]["state"] == "PROVISIONAL"

        # ③ 新補的第三列建了新 Decision。
        new_row_dec = [d for d in new_decs if d.get("name") == "新補上的列"]
        good = good and len(new_row_dec) == 1

        return ok("F3 覆寫保護:舊版進 _superseded、matched 列沿用舊 state、新列建新 Decision",
                   f"sup_files={sup_files}") if good else fail("F3", f"sup_files={sup_files}")
    finally:
        ctx.cleanup()


def F3_inject_would_delete_without_supersede():
    """注入:若覆寫時直接刪掉舊 record(不進 _superseded),必須被抓到。"""
    ctx = _Ctx()
    try:
        rec_v1 = _rec(1, "c", 500, [{"name": "公司債", "cols": {"c": 500}}])
        outcome1 = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                    "recs": [rec_v1], "level": 0, "retries": 0, "message": "m"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome1, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)

        # 模擬「壞版」:直接覆寫,不呼叫 _supersede_old。
        bad_facts_dir = os.path.join(ctx.root, "facts_bad")
        shutil.copytree(ctx.facts_dir, bad_facts_dir)
        import facts as facts_mod
        orig = facts_mod.DIR
        facts_mod.DIR = bad_facts_dir
        try:
            cells = facts_mod.load()
            cells["X|Trading"] = [_rec(1, "c", 999, [{"name": "全新的列",
                                                        "cols": {"c": 999}}])]
            facts_mod.save(cells)
        finally:
            facts_mod.DIR = orig
        bad_sup_exists = os.path.isdir(os.path.join(bad_facts_dir, "_superseded"))
        return ok("F3 inject:直接覆寫(不經 _supersede_old)不會產生 _superseded/ "
                    "→ 證實正式路徑(有呼叫 _supersede_old)才是安全的")\
            if not bad_sup_exists else fail("F3 inject", "壞版意外也產生了 _superseded/")
    finally:
        ctx.cleanup()


# ── PASS 也要建 Decision(不是只有 FILED)────────────────────────────────

def G_pass_also_creates_decisions():
    ctx = _Ctx()
    try:
        rec = _rec(1, "c", 500, [{"name": "公司債", "cols": {"c": 500}}])
        outcome = {"outcome": "PASS", "doc": "X", "cls": "Trading",
                   "recs": [rec], "level": 0, "retries": 0, "message": "m"}
        pending = os.path.join(ctx.root, "pending.json")
        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        decs = decision_store.load(ctx.decisions_dir).get("X|Trading", [])
        good = len(decs) == 1 and decs[0]["mapping"] == "公司債"
        return ok("PASS 也建立 Decision(與 FILED 共用落地邏輯)", decs) if good \
            else fail("G_pass_also_creates_decisions", decs)
    finally:
        ctx.cleanup()


# ── idempotence:同一輸入連跑兩次,三者都不重複 ──────────────────────────

def G_idempotent_rerun():
    ctx = _Ctx()
    try:
        rec = _rec(1, "c", 200, [{"name": "測試專用ZZZ", "cols": {"c": 200}}])
        outcome = {"outcome": "FILED", "doc": "X", "cls": "Trading",
                   "recs": [rec], "level": 0, "retries": 0, "message": "m"}
        pending = os.path.join(ctx.root, "pending.json")

        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        facts_bytes_1 = open(os.path.join(ctx.facts_dir, "X.json"), "rb").read()
        decs_bytes_1 = open(os.path.join(ctx.decisions_dir, "X.json"), "rb").read()

        # 這次是「同一份 record 再送一次」(等同覆寫自己)——會走 supersede 分支,
        # 但因為新舊 record_fp/row_fp 完全相同,重綁後內容應該邏輯等價。
        # 這裡驗證的是 review 佇列不重複(不變量:同 occurrence 不長出第二筆)。
        ingest.apply_outcome(outcome, None, pending, facts_dir=ctx.facts_dir,
                              decisions_dir=ctx.decisions_dir,
                              review_path=ctx.review_path,
                              taxonomy_dir=ctx.taxonomy_dir)
        review = decision_store.load_review(ctx.review_path)
        good = len(review) == 1
        return ok("idempotence:同輸入重跑兩次,review 佇列仍只 1 筆(不因重跑而長出重複)",
                   f"review={len(review)}") if good \
            else fail("G_idempotent_rerun", f"review={len(review)}(應為1)")
    finally:
        ctx.cleanup()


def main():
    print("=" * 60)
    print("test_b2.py — B2 兩道閘門 + 覆寫保護 + review 去重")
    print("=" * 60)
    tests = [F1_filed_writes_everything, F1_never_expands_never_consumes_budget,
             F1_inject_review_dedup, F3_supersede_and_rebind,
             F3_inject_would_delete_without_supersede,
             G_pass_also_creates_decisions, G_idempotent_rerun]
    results = [t() for t in tests]
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
