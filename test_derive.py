#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_derive.py — 推導層驗收(`docs/plan_schema_derive.md` D1)

根因(該文件 §0 實測):25 格拒收裡 22 格死在 `total_col` / `printed_total` /
破折號列這三個 schema 欄位,而系統自己就有答案(213/213 份既有 record
唯一命中)。這支測的是 `core/derive.py` 那個答案算得對不對。

⚠️ **恆真閘門的教訓**(`memory/checks-must-fail`):推導層一旦上線,
「這道檢查看起來全綠」不代表它在做事。case_wrong_amount_is_zero_hit 與
case_fabricated_printed_totals_dropped 是特地注入錯誤來確認閘門真的會擋,
不是只測 happy path。

case_real_rejected_regression 是全部 25 格真實拒收檔案的回歸鎖:
`plan_schema_derive.md` §2 的模擬結果(17 通過 / 2 進裁示台 / 3 抄錯 / 3 仍拒收)
寫死在這裡,以後改動推導層或六道,這個分布跑掉就代表行為變了,必須重新裁示。

執行方式: python3 test_derive.py       exit 0 = 全綠
"""
import copy
import glob
import json
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


from core import derive


def _rec(rows, printed_totals=None):
    r = {"doc": "x", "class": "Trading", "source_page": 10,
         "source_kind": "附註", "rows": rows}
    if printed_totals is not None:
        r["printed_totals"] = printed_totals
    return r


def case_unique_hit_derives():
    """唯一命中:兩欄,只有一欄列和等於錨 → total_col/printed_total 補上。"""
    rec = _rec([
        {"name": "公司債", "cols": {"114年6月30日": 60, "113年12月31日": 50}},
        {"name": "金融債", "cols": {"114年6月30日": 40, "113年12月31日": 45}},
    ])
    out = derive.derive_record(rec, 100)
    yield ("total_col 選對", out["total_col"] == "114年6月30日")
    yield ("printed_total = 錨", out["printed_total"] == 100)
    yield ("原始 rec 沒被動到(深拷貝)", "total_col" not in rec)


def case_wrong_amount_is_zero_hit():
    """**注入測試**:把金額改錯,逐列相加就不等於錨 —— 必須變成 0 個欄命中,
    不能悄悄選一個最接近的欄硬湊。這是證明推導層不是恆真閘門的關鍵一案。"""
    rec = _rec([{"name": "公司債", "cols": {"114年6月30日": 61}}])  # 故意差 1
    raised = False
    try:
        derive.derive_record(rec, 60)
    except derive.DeriveError as e:
        raised = "0 個欄命中" in str(e)
    yield ("金額錯一塊錢,0 個欄命中被抓到", raised)


def case_ambiguous_hit_rejected():
    """歧義:兩欄剛好都等於錨(人造情況,今天實測 0 格但邏輯要在)——
    不准沉默選第一個,必須報告需要人工挑選(`plan_schema_derive.md` §8①)。"""
    rec = _rec([{"name": "x", "cols": {"A": 100, "B": 100}}])
    raised = False
    try:
        derive.derive_record(rec, 100)
    except derive.DeriveError as e:
        raised = "個欄命中" in str(e) and "無法唯一推導" in str(e)
    yield ("兩欄都命中,回報歧義而不是硬選一個", raised)


def case_dash_row_filled_only_after_anchor_confirms():
    """破折號列:缺合計欄的列補 0,**但只在錨已經確認欄位之後**——
    這裡故意讓「缺欄那列」剛好是唯一命中欄的差額,證明補 0 的順序是對的。"""
    rec = _rec([
        {"name": "公司債", "cols": {"114年6月30日": 60}},
        {"name": "基金受益憑證", "cols": {}},           # 合計欄印「—」,模型沒放 key
    ])
    out = derive.derive_record(rec, 60)                  # 60 + 0(補的) == 60
    yield ("破折號列補了 0", out["rows"][1]["cols"].get("114年6月30日") == 0)
    yield ("total_col 仍然選對", out["total_col"] == "114年6月30日")


def case_fabricated_printed_totals_dropped():
    """**注入測試**:偽造一個對不上的 `printed_totals`,必須被丟掉那個欄,
    不能被系統「修正」成算出來的值(那樣第 6 道就恆真了),也不能連累
    整格失敗——這欄本來就是選填的獨立驗證,驗不過就是沒有,不是抄錯。"""
    rec = _rec(
        [{"name": "公司債", "cols": {"114年6月30日": 60, "取得成本": 55}}],
        printed_totals={"取得成本": 999},                # 偽造,對不上真正的列和 55
    )
    out = derive.derive_record(rec, 60)
    yield ("錯的 printed_totals 被丟掉", "取得成本" not in (out.get("printed_totals") or {}))
    yield ("該格本身仍然推導成功(沒有被連累)", out["total_col"] == "114年6月30日")


def case_correct_printed_totals_kept():
    """對得上的 `printed_totals` 要保留,不能連好的也一起丟。"""
    rec = _rec(
        [{"name": "公司債", "cols": {"114年6月30日": 60, "取得成本": 55}}],
        printed_totals={"取得成本": 55},
    )
    out = derive.derive_record(rec, 60)
    yield ("對得上的欄保留", out.get("printed_totals") == {"取得成本": 55})


def case_no_anchor_fails_cleanly():
    """沒有錨(≤2022 那批掃描影像)不准當成 0 個命中去湊,要清楚說「沒有錨」。"""
    rec = _rec([{"name": "x", "cols": {"A": 1}}])
    raised = False
    try:
        derive.derive_record(rec, None)
    except derive.DeriveError as e:
        raised = "沒有錨" in str(e)
    yield ("無錨清楚失敗", raised)


def case_records_all_or_nothing():
    """`derive_records`:一格通常 1-2 份 record,**一份失敗整批就失敗**——
    不該讓另一份先斬後奏歸檔進去(見 `core/derive.py` docstring)。"""
    good = _rec([{"name": "a", "cols": {"C": 60}}])
    good["source_page"] = 10
    bad = _rec([{"name": "b", "cols": {"C": 61}}])       # 差 1,湊不到錨
    bad["source_page"] = 11
    derived, err = derive.derive_records([good, bad], 60)
    yield ("整批失敗,derived 是 None", derived is None)
    yield ("錯誤訊息帶頁碼(1-based),方便追查是哪一份", "p.12" in (err or ""))

    derived2, err2 = derive.derive_records([good], 60)
    yield ("單一份成功時整批成功", err2 is None and derived2 is not None)


def case_real_rejected_regression():
    """全部 9 格真實拒收檔案的回歸鎖(`plan_schema_derive.md` §2 模擬結果)。

    這不是抽樣,是**全部**——分母就是 `work/rejected/` 現有的每一個檔案。
    數字改變不一定是壞事(可能是推導層變聰明了),但**改變就必須被看見**,
    不能悄悄漂移。

    ⚠️ **這個目錄是活的**,不是凍結的測試 fixture,數字動過三次:
      · 17/2/3/3(分母 25)→ 16/2/3/3(分母 24):`202502_國泰_個體|Trading`
        被人工 `ratify()` 放行離開了這個目錄——這是進度,不是回歸。
      · 16/2/3/3 → 14/2/4/3(分母 23):`202304_國泰_個體` 的 OCI/Trading
        在測試過程中被**另一個還在跑舊程式碼的 server.py process** 動過
        (`work/rejected/202304_國泰_個體__Trading.json` 的 `reason` 是
        `缺必要欄位 ['total_col','printed_total']`——這是 D1 之前
        `facts.validate()` 的舊訊息格式,D1 之後同樣的失敗會先在
        `derive.py` 就擋下來,訊息會是「0 個欄命中」。訊息格式對不上,
        代表寫這個檔案的程式碼不是這次改過的版本)。
      · 14/2/4/3(分母 23)→ 0/2/4/3(分母 9):新增 `fill.py revalidate`
        (2026-07-31)—— 23 格裡有 15 格是舊版 pipeline 尚未接上
        `derive.split_foreign_records`(丟掉擴頁誤拉進來的別類別表)前就
        卡住的,`submitted.records` 其實早就存在檔裡,重驗一次(不問模型)
        就過了,已經歸檔進 `facts/` 並從這個目錄移除。剩下的是真的還沒解的
        (`derive_fail` 是抄錯、`blocked` 是分類表缺口待人審、`reject` 是第 5 道
        分桶失敗);同一次改動也讓 revalidate 把重驗後仍失敗的格子的 `reason`
        更新成當下的真實理由(舊字串會指著早已修好的問題,誤導人去找不存在的
        毛病),並把分類表缺口從 `rejected/` 改路由進 `blocked/`。
        分母 8→9 是 server 在這期間新拒收了 `202502_玉山_個體|OCI`。
    **改動這支之前先用上面的邏輯手動重算一次**,不要只是把數字改到測試
    會過為止;如果數字改變的原因是「有 stale server 還在跑」,那是要去
    處理的問題,不是測試該吞下去的噪音。
    """
    import locate
    import transcribe
    import fill

    # **兩個目錄一起看**:`fill.py revalidate`(2026-07-31)會把重驗後判定為
    # 分類表缺口的格子從 `rejected/` 搬進 `blocked/`,只 glob 前者的話那些格子
    # 會憑空從分母裡消失,看起來像「問題自己好了」——那正是這支要擋的漂移。
    files = sorted(glob.glob("work/rejected/*.json") + glob.glob("work/blocked/*.json"))
    yield ("有拒收檔案可以回歸(分母不是 0)", len(files) > 0, f"{len(files)} 個檔案")

    tally = {"pass": 0, "blocked": 0, "derive_fail": 0, "reject": 0}
    for p in files:
        m = json.load(open(p, encoding="utf-8"))
        recs = copy.deepcopy((m.get("submitted") or {}).get("records") or [])
        if not recs:
            continue
        loc = locate.locate(f"pdf_cache/{m['doc']}.pdf")
        anchor = loc.anchors.get(m["cls"])

        derived, err = derive.derive_records(recs, anchor)
        if err:
            tally["derive_fail"] += 1
            continue
        ok, res = transcribe.verify(derived, loc)
        if ok:
            tally["pass"] += 1
            continue
        if fill._taxonomy_gap(derived, loc):
            tally["blocked"] += 1
        else:
            tally["reject"] += 1

    yield ("推導後直接通過 = 0(2026-07-31 起,已被 revalidate 撿走,見上方註記)",
           tally["pass"] == 0, tally)
    yield ("路由到裁示台 = 2", tally["blocked"] == 2, tally)
    yield ("推導失敗(真的抄錯) = 4", tally["derive_fail"] == 4, tally)
    yield ("仍然拒收(第 5 道) = 3", tally["reject"] == 3, tally)


def main():
    bad = 0
    for case in (case_unique_hit_derives, case_wrong_amount_is_zero_hit,
                 case_ambiguous_hit_rejected,
                 case_dash_row_filled_only_after_anchor_confirms,
                 case_fabricated_printed_totals_dropped,
                 case_correct_printed_totals_kept,
                 case_no_anchor_fails_cleanly,
                 case_records_all_or_nothing,
                 case_real_rejected_regression):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for item in case():
            label, ok = item[0], item[1]
            detail = item[2] if len(item) > 2 else ""
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
