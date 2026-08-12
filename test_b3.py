# -*- coding: utf-8 -*-
"""test_b3.py — B3:UNCLASSIFIED 進恆等式不冒充 + status 兩個數字。

I4:未知列**保留金額、參與三段恆等式**,但不得落進任何 wide 桶,不得冒充
OTHER 或 null。`wide.view()` 的算術半邊已經對(不改它);本檔驗**發布狀態
半邊**——`core/publish_gate.py` 新增的東西。

全部讀真實 `facts/` 當唯讀輸入(不寫入),另外用合成 record 做注入測試。

2026-08-12:移除了 `wide_untouched`——那支斷言「本次開發沒動 wide.py /
core/reconcile.py / core/decisions.py」的 `git diff --stat` 為空,是 B3 那次
開發 session 專用的一次性守門(怕改壞了不該碰的檔案),不是恆久不變量。
之後任何一次正常修改那三個檔案(例如這次 R0-1 修 core/decisions.py 的真 bug)
都會讓它紅,而它守的不是正確性,是「這個 session 有沒有手滑碰到別的檔案」——
那件事現在由 code review / git diff 本身守,不需要一支測試守。
"""
import buckets
import facts
import wide
from core import publish_gate as pg

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


def _rec(rows, printed_total, total_col="c"):
    return {"doc": "X", "class": "Trading", "source_page": 1, "source_kind": "附註",
            "total_col": total_col, "printed_total": printed_total, "rows": rows}


# ── I4:未知列保留金額、參與恆等式、不落進任何桶、不冒充 OTHER/null ──────

def I4_unknown_kept_and_blocks_ok():
    """一列分類未知(buckets.bucket 回 None)混進已知列 → View.unknown 帶著
    它的名字與金額;它的金額**沒有**被算進任何 wide 桶;three-段恆等式因此
    對不上(它的金額在 expected 裡,但不在 total/side 裡),`View.ok` 必須 False。
    """
    unknown_name = "測試專用不存在的分類名稱ZZZ"
    rec = _rec([
        {"name": "公司債", "cols": {"c": 300}},
        {"name": unknown_name, "cols": {"c": 200}},
    ], printed_total=500)
    v = wide.view([rec], "帳面")

    kept = any(n == unknown_name and amt == 200 for n, amt, _why in v.unknown)
    not_in_any_bucket = all(name != unknown_name for wb_rows in
                             [] for name in wb_rows)  # book 只存金額不存名字,見下行才是真正的檢查
    amount_not_double_counted = (v.total == 300)  # 只有公司債的 300 進了 book,不含 200
    identity_fails = not v.ok

    good = kept and amount_not_double_counted and identity_fails
    return ok(f"I4:未知列保留金額(unknown 帶著 {unknown_name}=200)、"
                f"未落進任何 wide 桶(total={v.total})、恆等式因此不成立",
              f"unknown={v.unknown}") if good else fail("I4", f"kept={kept} total={v.total} ok={v.ok}")


def I4_inject_would_fold_into_other():
    """注入:若把分類未知的列硬塞進「其他」桶(冒充),恆等式反而會**通過**——
    這正是規格禁止的行為(混進「其他」會讓錯誤看起來像正常值)。用手動組一個
    「壞版」View 來證明這個風險確實存在。"""
    unknown_name = "測試專用不存在的分類名稱ZZZ"
    rec = _rec([
        {"name": "公司債", "cols": {"c": 300}},
        {"name": unknown_name, "cols": {"c": 200}},
    ], printed_total=500)
    v = wide.view([rec], "帳面")
    # 模擬「冒充其他」:把 unknown 的金額硬加進其他桶,恆等式會變成立。
    bad_book = dict(v.book)
    bad_book["其他"] = bad_book.get("其他", 0) + sum(amt for _n, amt, _w in v.unknown)
    bad_total = sum(bad_book.values())
    would_wrongly_pass = (bad_total + sum(v.side.values()) == v.expected)
    return ok("I4 inject:若把未知列硬塞進「其他」桶,恆等式會被誤判通過"
                " → 證實 wide.view() 不這麼做(它把未知列排除在 book 之外)才是對的")\
        if would_wrongly_pass else fail("I4 inject", "沒有重現冒充會怎樣的風險")


def I4_no_unknown_rows_ok_when_classified():
    """反例:全部列都認得桶 → 沒有 unknown、算術對得上時 `ok` 可以是 True
    (證明 I4 的檢查不是恆假,`unknown` 為空時真的會通過)。"""
    rec = _rec([{"name": "公司債", "cols": {"c": 500}}], printed_total=500)
    v = wide.view([rec], "帳面")
    good = (not v.unknown) and v.ok
    return ok("I4 反例:全部可分類且算術對 → ok=True(檢查不是恆假)", f"unknown={v.unknown} ok={v.ok}")\
        if good else fail("I4 反例", f"unknown={v.unknown} ok={v.ok}")


# ── status 的兩個數字:archived / publishable ───────────────────────────

def status_two_numbers_on_real_facts():
    """對真實 facts(唯讀)算 status:archived 恆等於格數(不管 facts/ 長到多大);
    publishable **可以**小於 archived——分岔是產出,不是退步(§5 B3)。

    2026-08-12:格數改成動態讀 `len(cells)`,不再硬編 `36` —— facts/ 早就
    長大到 192 格,硬編基準只是在測「今天剛好還是 36」,不是在測不變量。"""
    cells = facts.load()
    s = pg.status_all(cells)
    good = s["archived"] == len(cells) and 0 <= s["publishable"] <= s["archived"]
    return ok(f"status 兩個數字:archived={s['archived']} publishable={s['publishable']}"
                "(唯讀,真實 facts;facts/ 未被本測試寫入)") if good \
        else fail("status_two_numbers", s)


def status_inject_would_hide_unclassified():
    """注入:若 `coarse_status` 對 UNCLASSIFIED 列視而不見(照樣判 publishable),
    必須被抓到——用一格「Gate1 過但分類未知」的合成資料證明它會被正確擋下。"""
    unknown_name = "測試專用不存在的分類名稱ZZZ"
    rec = _rec([{"name": unknown_name, "cols": {"c": 200}}], printed_total=200)
    key = "TESTDOC|Trading"
    st = pg.coarse_status(key, [rec], decisions_dir=None, taxonomy_dir="taxonomy")
    correctly_blocked = (not st["publishable"]) and st["decisions"]["unclassified"] >= 1
    return ok("status inject:分類未知的格 publishable=False,且原因指名 unclassified 列",
               st) if correctly_blocked else fail("status_inject", st)


def main():
    print("=" * 60)
    print("test_b3.py — B3 未知不冒充 + status 兩個數字")
    print("=" * 60)
    tests = [I4_unknown_kept_and_blocks_ok, I4_inject_would_fold_into_other,
             I4_no_unknown_rows_ok_when_classified,
             status_two_numbers_on_real_facts,
             status_inject_would_hide_unclassified]
    for t in tests:
        t()
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
