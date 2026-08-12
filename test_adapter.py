#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_adapter.py — v4/adapter.py 與 W5(check_bucket_complete)驗收。

docs/plan_v5_統一.md P1-2 兩條閘門各要一個「注入錯誤後必須變紅」的測試,
不是只驗綠燈——恆真的測試抓不到「桶沒接好、錢悄悄消失」這種 bug
(見 memory/checks-must-fail)。

執行方式: python3 test_adapter.py       exit 0 = 全綠
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))


from v4 import adapter, witness

GOOD_ROWS = [
    {"group": "", "name": "政府公債", "amount": 100},
    {"group": "", "name": "公司債", "amount": 200},
    {"group": "", "name": "金融債", "amount": 50},
]
GOOD_SUBTOTAL = 350


def a1_split_matches_first_before_splitting():
    """T1:「定期存單-可轉讓」本身就是 buckets.SYN 的既有鍵(字序倒裝),
    先拆再查會拆散它、查不到 —— 這是實測抓到的真 bug(P1-1 開發時)。
    這條測試釘住「先整條查、查不到才拆」這個順序不能被之後的改動悄悄倒退。"""
    row = {"group": "", "name": "定期存單-可轉讓", "amount": 100}
    check("T1 整條原名優先於拆開的結果",
          adapter.bucket_row(row) == "可轉讓定存單", adapter.bucket_row(row))


def a2_group_split_resolves_generic_plus_group():
    """T2:「其他」配段落「衍生金融資產」要能透過 GROUP_SYN 解出「衍生」——
    這是 P1-1 改 prompt 要求 group/name 分開兩欄之後才通的路。"""
    row = {"group": "衍生金融資產", "name": "其他", "amount": 100}
    check("T2 GENERIC 名字配 group 解出衍生桶",
          adapter.bucket_row(row) == "衍生", adapter.bucket_row(row))


def a3_aggregate_green_on_clean_rows():
    """基準情境:乾淨的三列,桶都認得、Σ桶等於小計 → 應該合格。"""
    agg = adapter.aggregate(GOOD_ROWS, GOOD_SUBTOTAL)
    check("T3 乾淨資料 aggregate 合格", agg.ok, agg.reason)
    check("T3 七桶裡有對應金額",
          agg.book["GB"] == 100 and agg.book["公司債"] == 200 and agg.book["金融債"] == 50)


def a4_unknown_row_must_fail_not_silently_drop():
    """**注入錯誤測試(閘門一):有列對不到桶。**
    拿基準情境,加一列分桶表完全不認得的科目名 —— 這筆錢不准悄悄從
    七桶加總裡消失,aggregate 必須回報不合格,不能算出一個「看起來對」
    但漏了一列的七桶。"""
    bad_rows = GOOD_ROWS + [{"group": "", "name": "不存在的科目名稱ZZZ", "amount": 999}]
    agg = adapter.aggregate(bad_rows, GOOD_SUBTOTAL + 999)
    check("T4 有列對不到桶 → aggregate 不合格(閘門會抓,不是自主觀察)",
          not agg.ok, agg.reason)
    check("T4 unknown 清單裡點得到是哪一列",
          any("不存在的科目名稱ZZZ" in u[0] for u in agg.unknown), agg.unknown)


def a5_sum_mismatch_must_fail():
    """**注入錯誤測試(閘門二):Σ七桶 ≠ 小計。**
    每一列單獨看都認得桶,但給一個跟實際加總對不起來的 printed_subtotal
    (模擬:模型把小計抄錯,或某一列金額被改過但小計沒同步改)——
    aggregate 必須抓到,不能因為「每一列都查得到桶」就放行。"""
    agg = adapter.aggregate(GOOD_ROWS, GOOD_SUBTOTAL + 1)
    check("T5 Σ桶≠小計 → aggregate 不合格", not agg.ok, agg.reason)
    check("T5 差額有算出來(1)", "1" in (agg.reason or ""), agg.reason)


def a6_witness_w5_mismatch_forces_not_green():
    """**串到 W5**:`check_bucket_complete` 遇到對不到桶的列要回 MISMATCH,
    這樣 `ledger.classify_cell()` 才會判 RED,不會因為前面幾道 witness
    OK 就放行成 GREEN —— 這是這道 witness 存在的唯一理由,見 witness.py W5。"""
    good_book = {"rows": GOOD_ROWS, "printed_subtotal": GOOD_SUBTOTAL}
    bad_book = {"rows": GOOD_ROWS + [{"name": "查無此科目", "amount": 999}],
                "printed_subtotal": GOOD_SUBTOTAL + 999}
    check("T6a 乾淨 book → W5 OK",
          witness.check_bucket_complete(good_book)["status"] == "OK")
    check("T6b 有列對不到桶的 book → W5 MISMATCH(不是 no_witness、不是 OK)",
          witness.check_bucket_complete(bad_book)["status"] == "MISMATCH")


def a7_subtotal_rows_filtered_not_treated_as_unknown():
    """`合計`/`小計` 這類列不是投資標的,normalize_rows 要濾掉,不能被
    bucket_row 判成「對不到桶」而製造假警報(P1-1 prompt 規則的程式端保險絲)。"""
    rows, dropped = adapter.normalize_rows(
        GOOD_ROWS + [{"group": "", "name": "小計", "amount": GOOD_SUBTOTAL}])
    check("T7 小計列被濾掉,不進 rows", len(rows) == len(GOOD_ROWS))
    check("T7 小計列有被記錄在 dropped 裡(不是憑空消失)", len(dropped) == 1)


def a8_basis_is_cost_when_valuation_adj_present():
    """**口徑閘門。** 有評價調整列 ⇒ 逐項是成本,那一列是補到公允的差額,
    而它是**一整筆、不分桶** —— 所以「逐桶帳面」在文件裡不存在。

    這條要是壞了,症狀是「數字全對、閘門全綠、發布的欄位錯」:實測 20 格把成本
    當帳面發布過(兆豐 202302 Trading 差 5,979,308 = 10.73%)。人對著原始頁
    逐列核對也看不出來 —— 每一列都跟紙上一模一樣,錯的是它落在 wide 還是
    wide_cost。這正是「全綠但產出是廢的」那一類,只有這裡擋得住。
    """
    clean = adapter.aggregate(GOOD_ROWS, GOOD_SUBTOTAL)
    check("T8 沒有評價調整列 → 口徑是公允(可以當帳面發布)",
          clean.ok and clean.basis == "公允", f"basis={clean.basis}")

    # 注入:同一批列多一筆評價調整,小計同步加上去(算術仍然完全對得起來)
    adj_rows = GOOD_ROWS + [{"group": "", "name": "評價調整", "amount": 40}]
    adj = adapter.aggregate(adj_rows, GOOD_SUBTOTAL + 40)
    check("T8 注入評價調整列 → 口徑翻成成本", adj.ok and adj.basis == "成本",
          f"basis={adj.basis}")
    check("T8 翻成成本之後,七桶本身仍然有效(不是把資料丟掉)",
          adj.ok and adj.book["GB"] == 100 and adj.book["公司債"] == 200)
    check("T8 評價調整沒有被算進七桶(它不是持有的資產)",
          adj.ok and sum(adj.book.values()) == 350)


def a9_cost_basis_must_not_publish_as_wide():
    """T8 的**發布端**對照:口徑是成本時,發布路徑一定要把七桶放進 wide_cost
    而不是 wide。分開驗是因為 adapter 判對了、build 用錯欄位的話,
    錯的數字照樣會上網站(這正是修這個 bug 之前的實況)。

    ⚠️ **判「這格是成本」時不准呼叫 `adapter.aggregate().basis`** —— 那樣寫的話
    adapter 一壞,這條測試會跟著用同一個壞掉的判斷,永遠自我一致、永遠綠。
    (實測:第一版就是這樣寫的,注入 bug 之後 T8 紅了、T9 照樣綠。)

    ⚠️ 但也**不可以直接用 `buckets.is_adj`** —— 第二版是那樣寫的,結果對
    `債務工具-評價調整`(段落黏進名字)判 False,跟真正的分桶路徑相反,
    測試自己也跟著漏掉 `202504_兆豐_個體|OCI`。獨立不等於可以用比較弱的判準。
    這裡用 `adapter.bucket_row()`(分桶真正走的那支原語,與 basis 的計算分開)。

    ⚠️ 2026-08-11(R0-4):`build.rebuild_v4()` 已刪除,這條改成驗**真正的發布路徑**
    (`rebuild_v3()`,唯一的一條)。要守的不變量一個字都沒變,只是換了受檢對象 ——
    v4 那條路徑不存在了,再驗它就是驗一個不會影響任何人的東西。
    """
    from config import VALUATION_ADJ

    import build
    import facts as facts_mod

    verdict, _, _ = build.rebuild_v3()
    cells = facts_mod.load()
    wrong = []
    for key, v in verdict.items():
        if not v["pass"] or v.get("wide") is None:
            continue
        recs = cells.get(key) or []
        if not recs:
            continue

        # 獨立判定「這份 record 是成本口徑」:它的 rows 裡有評價調整/備抵損失列。
        # 走 `adapter.bucket_row()`(分桶真正的原語),不走 adapter 算 basis 的那支,
        # 也不走比較弱的 `buckets.is_adj` —— 理由見上面兩段。
        def rec_is_cost(rec):
            return any(
                adapter.bucket_row({"name": r.get("name") or "",
                                    "group": r.get("group") or ""}) == VALUATION_ADJ
                for r in (rec.get("rows") or []) if isinstance(r, dict))

        # ⚠️ 判準是「**每一份**來源都是成本」,不是「有任何一份是成本」。
        # 一格常常同時有附註(成本口徑,含評價調整列)與明細表(帳面金額欄),
        # `wide.pick(帳面)` 會正確地挑後者 —— 那種格子有 wide 是對的。
        # 第一版寫成 any(),誤報 30 格(例:202004_兆豐_個體|AC,附註 p34 成本
        # + 明細表 p154 帳面金額)。這條對應 `wide.py`「所有來源逐項皆為成本口徑」。
        if all(rec_is_cost(rec) for rec in recs):
            wrong.append(key)
    check("T9 沒有任何成本口徑的格把七桶寫進 wide(帳面)", not wrong,
          f"{len(wrong)} 格寫錯欄:{wrong[:3]}" if wrong else "全部走 wide_cost")
    check("T9 這條測試不是空的(真的有格在發布 wide)",
          any(v["pass"] and v.get("wide") is not None for v in verdict.values()))


def a10_hard_gates_vs_hints():
    """**降級的驗收**(2026-08-03 五道收成三道)。這條要釘住兩件事:

    ① 提示類 witness 沒過**不可以**讓格子變 RED —— 否則降級根本沒生效
    ② 硬閘門沒過**一定要**變 RED —— 否則降級把閘門一起降掉了

    兩件事要一起驗:只驗其中一邊的話,「全部都判 RED」和「全部都不判 RED」
    各自都能讓單邊測試通過。
    """
    from v4 import ledger
    book = {"rows": GOOD_ROWS, "printed_subtotal": GOOD_SUBTOTAL}

    only_hint_bad = {
        "check_rowsum": {"status": "MISMATCH", "diff": 999},
        "check_anchor": {"status": "MISMATCH", "diff": 888},
        "check_page_ref": {"status": "MISMATCH", "diff": None},
        "check_bucket_complete": {"status": "OK", "diff": 0},
        "check_basis": {"status": "OK", "diff": 0},
    }
    got = ledger.classify_cell("D", "Trading", only_hint_bad, book)
    check("T10a 三道提示全掛、硬閘門都過 → 仍然 GREEN(降級真的生效了)",
          got["status"] == "GREEN", f"status={got['status']}")

    for gate in ledger.HARD_GATES:
        checks = {k: {"status": "OK", "diff": 0} for k in only_hint_bad}
        checks[gate] = {"status": "MISMATCH", "diff": None}
        g = ledger.classify_cell("D", "Trading", checks, book)
        check(f"T10b 硬閘門 {gate} 不過 → RED(閘門沒被一起降掉)",
              g["status"] == "RED", f"status={g['status']}")

    check("T10c check_cross_period 已整支移除(不再出現在 run_witness 的輸出裡)",
          "check_cross_period" not in only_hint_bad
          and not hasattr(witness, "check_cross_period"))


def a11_soft_failures_must_appear_in_queue():
    """降級之後那些格子**會發布**,所以必須有一份清單讓人去對圖 ——
    佇列只列 RED/GREY 的話它們會 publish 而且不出現在任何畫面上,
    那就是把「降級」偷偷變成「靜靜放行」。"""
    from v4 import ledger
    q = ledger.review_queue()
    check("T11a review_queue 有 hint 這一段", "hint" in q)
    listed = {(r["doc"], r["cls"]) for r in q.get("hint", [])}
    missing = []
    for e in ledger.load_all():
        for cls, c in e["cells"].items():
            if c["status"] not in ("GREEN", "RATIFIED"):
                continue
            soft = [w for w, v in (c.get("witnesses") or {}).items()
                    if v.get("status") == "MISMATCH" and w not in ledger.HARD_GATES]
            if soft and (e["doc"], cls) not in listed:
                missing.append(f"{e['doc']}|{cls}")
    check("T11b 每個「會發布但有提示沒過」的格都在 hint 清單裡", not missing,
          f"{len(missing)} 格沒列出來:{missing[:3]}" if missing
          else f"{len(listed)} 格在清單上")


if __name__ == "__main__":
    for fn in (a1_split_matches_first_before_splitting,
               a2_group_split_resolves_generic_plus_group,
               a3_aggregate_green_on_clean_rows,
               a4_unknown_row_must_fail_not_silently_drop,
               a5_sum_mismatch_must_fail,
               a6_witness_w5_mismatch_forces_not_green,
               a7_subtotal_rows_filtered_not_treated_as_unknown,
               a8_basis_is_cost_when_valuation_adj_present,
               a9_cost_basis_must_not_publish_as_wide,
               a10_hard_gates_vs_hints,
               a11_soft_failures_must_appear_in_queue):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
