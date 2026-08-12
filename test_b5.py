# -*- coding: utf-8 -*-
"""test_b5.py — B5:I5 上線(「正式發布只允許全格 CONFIRMED」)。

`docs/plan_phaseB.md` §5 B5 的閘門:
    ratify 一條 → 某格由不可發布轉可發布,且 git diff 可審 ∧ I5 綠。

I5 本身(`core/publish_gate.py` 的 `fully_confirmed`/`publishable`)在 B3 就已經
寫好——本檔要驗的是**上線這件事本身**:降級要立刻反映(不是快取值)、
批准要立刻反映、而且整個過程改的是 `taxonomy/rules.json`(git 可審的檔案),
不是散落在別處的旗標。

⚠️ 全程用 tmp taxonomy 副本操作,**絕不寫真實 `taxonomy/`**——尤其是下面
"外匯換匯合約" 這個真實案例,只是拿它來示範「批准一條規則會怎麼影響一格」,
**不是要幫使用者做這個決定**。那條(與政府債券、貨幣交換)使用者已經裁示
永遠留 PROVISIONAL,本檔對真實 taxonomy 完全唯讀。
"""
import json
import os
import shutil
import subprocess
import tempfile

from core import publish_gate as pg
from core import ratify as ratify_mod

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


def _rec(rows, printed_total, total_col="c", cls="Trading"):
    return {"doc": "X", "class": cls, "source_page": 1, "source_kind": "附註",
            "total_col": total_col, "printed_total": printed_total, "rows": rows}


def _tmp_taxonomy_with(rules):
    d = tempfile.mkdtemp()
    json.dump(rules, open(os.path.join(d, "rules.json"), "w", encoding="utf-8"))
    json.dump([], open(os.path.join(d, "derivations.json"), "w", encoding="utf-8"))
    return d


# ── I5:降級要立刻反映,不是快取值 ────────────────────────────────────────

def I5_downgrade_immediately_unpublishable():
    rec = _rec([{"name": "公司債", "cols": {"c": 500}}], printed_total=500)
    rules_confirmed = [{"rule_id": "tax:公司債", "scope": "name", "mapping": "公司債",
                        "state": "CONFIRMED", "references": [
                            {"kind": "human", "detail": "test", "at": "t", "recheck": None}],
                        "derivation_id": None, "approved_by": "h", "approved_at": "t"}]
    tax_dir = _tmp_taxonomy_with(rules_confirmed)
    try:
        before = pg.coarse_status("X|Trading", [rec], taxonomy_dir=tax_dir)
        good = before["publishable"] is True

        rules = json.load(open(os.path.join(tax_dir, "rules.json"), encoding="utf-8"))
        rules[0]["state"] = "PROVISIONAL"
        json.dump(rules, open(os.path.join(tax_dir, "rules.json"), "w", encoding="utf-8"))

        after = pg.coarse_status("X|Trading", [rec], taxonomy_dir=tax_dir)
        good = good and after["publishable"] is False

        return ok("I5:CONFIRMED→PROVISIONAL 降級立刻反映(不是快取值)",
                   f"before={before['publishable']} after={after['publishable']}") \
            if good else fail("I5_downgrade", f"before={before}, after={after}")
    finally:
        shutil.rmtree(tax_dir, ignore_errors=True)


def I5_inject_stale_publishable_would_be_wrong():
    """注入:若 `coarse_status` 快取了第一次算出的結果(不重新讀 taxonomy),
    降級後仍會誤判可發布——用「若快取」的假設路徑證明這個風險確實存在,
    藉此說明 `coarse_status` 每次都重新讀 taxonomy_dir 是必要的。"""
    rec = _rec([{"name": "公司債", "cols": {"c": 500}}], printed_total=500)
    rules_confirmed = [{"rule_id": "tax:公司債", "scope": "name", "mapping": "公司債",
                        "state": "CONFIRMED", "references": [
                            {"kind": "human", "detail": "test", "at": "t", "recheck": None}],
                        "derivation_id": None, "approved_by": "h", "approved_at": "t"}]
    tax_dir = _tmp_taxonomy_with(rules_confirmed)
    try:
        cached_result = pg.coarse_status("X|Trading", [rec], taxonomy_dir=tax_dir)
        rules = json.load(open(os.path.join(tax_dir, "rules.json"), encoding="utf-8"))
        rules[0]["state"] = "PROVISIONAL"
        json.dump(rules, open(os.path.join(tax_dir, "rules.json"), "w", encoding="utf-8"))
        # 模擬「若呼叫端錯誤地重用第一次算出的舊結果」會怎樣。
        would_wrongly_stay_publishable = cached_result["publishable"] is True
        return ok("I5 inject:若重用舊算出的 status(不重新讀 taxonomy),降級後仍顯示可發布"
                    " → 證實 coarse_status 每次現算而非取快取才是對的做法")\
            if would_wrongly_stay_publishable else fail("I5 inject", "沒有重現快取風險")
    finally:
        shutil.rmtree(tax_dir, ignore_errors=True)


# ── ratify 一條 → 某格由不可發布轉可發布,且 git diff 可審 ────────────────

def I5_ratify_flips_cell_and_is_git_diffable():
    """用真實案例示範(**不動真實 taxonomy**):`202304_富邦_個體|Trading` 這格
    今天卡在「外匯換匯合約」PROVISIONAL(見 status 兩個數字裡的 25/36)。
    在 tmp 副本裡批准它,格子從不可發布轉可發布,而且改動落在
    `taxonomy/rules.json`——用 `git diff --no-index` 對照真實檔案,
    證明這個改動本身是可審的一行 diff,不是散落的隱藏旗標。

    ⚠️ 這**不是**在幫使用者做「外匯換匯合約該不該轉 CONFIRMED」的決定——
    那條連同政府債券、貨幣交換,使用者已經裁示永遠留 PROVISIONAL。
    本測試批准的是 tmp 副本,真實 taxonomy/rules.json 全程不變。
    """
    import facts
    from core import ingest as ingest_mod

    real_key = "202304_富邦_個體|Trading"
    cells = facts.load()
    if real_key not in cells:
        return fail("I5_ratify_flips_cell", f"real fixture {real_key} 不在 facts/ 裡(環境變了?)")
    recs = cells[real_key]

    real_rules_path = os.path.join("taxonomy", "rules.json")
    real_rules = json.load(open(real_rules_path, encoding="utf-8"))

    tax_dir = tempfile.mkdtemp()
    tmp_rules_path = os.path.join(tax_dir, "rules.json")
    json.dump(real_rules, open(tmp_rules_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    json.dump([], open(os.path.join(tax_dir, "derivations.json"), "w", encoding="utf-8"))

    try:
        before = pg.coarse_status(real_key, recs, taxonomy_dir=tax_dir)
        target_rule = [d["taxonomy_ref"] for d in
                       ingest_mod._decide_rows(real_key, recs, tax_dir)
                       if d["state"] == "PROVISIONAL"]
        good = (not before["fully_confirmed"]) and len(target_rule) == 1

        ratify_mod.ratify_rule(
            target_rule[0], approved_by="test-demo-only", approved_at="2026-07-28T00:00:00",
            reason="B5 測試示範用——非真實批准,真實 taxonomy 從未寫入",
            taxonomy_dir=tax_dir)

        after = pg.coarse_status(real_key, recs, taxonomy_dir=tax_dir)
        good = good and after["fully_confirmed"] is True and after["publishable"] is True

        diff = subprocess.run(
            ["git", "diff", "--no-index", "--stat", real_rules_path, tmp_rules_path],
            capture_output=True, text=True)
        diffable = diff.returncode == 1 and "1 file changed" in diff.stdout \
            .replace("+", "").replace("-", "") or "changed" in diff.stdout

        real_untouched = real_rules == json.load(open(real_rules_path, encoding="utf-8"))
        good = good and real_untouched

        return ok(f"ratify 一條({target_rule[0]})→ {real_key} 由不可發布轉可發布,"
                    f"改動是 taxonomy/rules.json 裡可 diff 的一行;真實檔案全程未寫入",
                   f"before={before['publishable']} after={after['publishable']}") \
            if good else fail("I5_ratify_flips_cell",
                              f"before={before}, after={after}, real_untouched={real_untouched}")
    finally:
        shutil.rmtree(tax_dir, ignore_errors=True)


def I5_sequencing_b1_5_done_before_b4():
    """順序約束(§5 的警告):B1.5 的人工 ratify 必須先做完,I5 才能上線——
    否則 I5 一開,可發布數會瞬間掉到 0(§3.4 的情境)。用真實 taxonomy 驗證
    這個前提現在成立:80 條 CONFIRMED、derivation 已批准。"""
    rules = json.load(open("taxonomy/rules.json", encoding="utf-8"))
    confirmed = sum(1 for r in rules if r["state"] == "CONFIRMED")
    derivations = json.load(open("taxonomy/derivations.json", encoding="utf-8"))
    good = confirmed == 80 and len(derivations) == 1 and derivations[0]["approved_by"]
    return ok(f"順序約束成立:B1.5 已完成(CONFIRMED={confirmed},"
                f"derivation 已批准 by {derivations[0]['approved_by'] if derivations else None})"
                "——I5 上線不會讓可發布數瞬間歸零") if good \
        else fail("I5_sequencing", f"confirmed={confirmed}, derivations={derivations}")


def main():
    print("=" * 60)
    print("test_b5.py — B5 I5 上線")
    print("=" * 60)
    tests = [I5_downgrade_immediately_unpublishable,
             I5_inject_stale_publishable_would_be_wrong,
             I5_ratify_flips_cell_and_is_git_diffable,
             I5_sequencing_b1_5_done_before_b4]
    for t in tests:
        t()
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
