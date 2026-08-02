#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_webdata.py — 複核台資料層驗收 (W1-W7)

UI 已經換過兩次(Streamlit → 自刻網站)。每換一次都重寫取數邏輯,就等於每換
一次都要重驗「35 已抄 / 90 可抄」。`core/webdata.py` 把取數抽出來,這支盯著它。

**W3 是重點**:`source_page` 存的是 0-based(與 `locate` 的候選頁同制),
不是印在紙上的頁碼。這點踩過一次 —— 抄列模板寫成 `候選頁+1`、核對畫面讀成
`source_page-1`,兩邊都錯,而且畫面看起來很正常(圖有出來、數字也有),
只是圖跟數字對不起來。**恆真的測試抓不到這種 bug,所以 W3 直接跟 PDF 對答案。**

W6/W7 用 tmp 檔驗寫入,**真實 buckets.py 與 work/ 全程唯讀**。

執行方式: python3 test_webdata.py       exit 0 = 全綠
"""
import json
import os
import shutil
import sys
import tempfile

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


import facts
import locate
from core import webdata


def w1_scope():
    """只做 2023+,且沒有把任何一份檔漏掉。"""
    docs = webdata.docs_in_scope()
    check("W1a 範圍內全部 >= 2023", all(int(d[:4]) >= 2023 for d in docs),
          f"{len(docs)} 份")
    import fill
    all_docs = fill._all_docs()
    expect = [d for d in all_docs if int(d[:4]) >= 2023]
    check("W1b 沒漏任何 2023+ 的檔", sorted(docs) == sorted(expect),
          f"{len(docs)} vs {len(expect)}")


def w2_overview():
    """四種狀態互斥且加總 = 有檔的格數 × 3 類。**格數對不上就是有格子靜靜消失了**,
    那正是這個專案踩過兩次的坑(先漏 AI1、修完又漏 AI2)。

    grid 現在是**日曆格**(period × bank,含還沒抓到檔的空格,doc=None),
    不是「每份檔一格」——2026-07 加的「矩陣畫預期清單」功能之後就是如此。
    所以這裡只驗**同一口徑**內、真的有檔的那些格。
    """
    import fill
    ov = webdata.overview()
    st = ov["stats"]
    idx = fill._load_index()
    bmap = idx.get("basis") or {}
    docs_this_basis = [d for d in webdata.docs_in_scope() if bmap.get(d) == ov["basis"]]
    n_docs = len(docs_this_basis)
    total = sum(st.values())
    check("W2a 狀態加總 = 有檔格數 × 3 類", total == n_docs * 3,
          f"{total} vs {n_docs}×3={n_docs * 3}")
    filled = sum(1 for g in ov["grid"].values() if g["doc"] is not None)
    check("W2b grid 裡有檔的格數 = 該口徑檔數", filled == n_docs,
          f"{filled} vs {n_docs}")
    # 欄位是從資料推導的,不是寫死的列舉
    cols_from_docs = {webdata.split_doc(d)[1] for d in docs_this_basis}
    check("W2c 欄位集合由資料推導(不小於該口徑的檔案欄位)", cols_from_docs <= set(ov["cols"]),
          f"{sorted(ov['cols'])}")


def w3_source_page_is_zero_based():
    """**這支測試存在的全部理由**:證明 `source_page` 是 0-based。

    做法是拿一格已抄好的資料,把它的 `printed_total` 格式化成千分位字串,
    去該頁的文字層裡 grep。對得上才代表頁碼指對了地方。
    這是跟 PDF 對答案,不是跟另一段同樣可能錯的程式對答案。
    """
    ov = webdata.overview()
    tested = 0
    bad = []
    for g in ov["grid"].values():
        if g["classes"] is None:  # 日曆格,還沒抓到檔
            continue
        for cls, state in g["classes"].items():
            if state != "done" or tested >= 5:
                continue
            key = f"{g['doc']}|{cls}"
            d = webdata.cell_detail(key)
            loc = locate.locate(f"pdf_cache/{g['doc']}.pdf")
            for rec in d["records"]:
                p = rec["source_page"]
                if not (0 <= p < len(loc.texts)):
                    bad.append(f"{key} p={p} 超出範圍")
                    continue
                needle = f"{rec['printed_total']:,}"
                if needle not in loc.text(p).replace(" ", ""):
                    bad.append(f"{key} p={p} 找不到 {needle}")
            tested += 1
    check("W3 source_page 直接當 0-based 索引找得到印出合計",
          not bad, f"驗了 {tested} 格" + ("" if not bad else f";{bad[:3]}"))


def w4_cell_detail_shape():
    ov = webdata.overview()
    key = None
    for g in ov["grid"].values():
        if g["classes"] is None:  # 日曆格,還沒抓到檔
            continue
        for cls, state in g["classes"].items():
            if state == "done":
                key = f"{g['doc']}|{cls}"
                break
        if key:
            break
    d = webdata.cell_detail(key)
    check("W4a 已抄的格取得到內容", d is not None and bool(d["records"]), key)
    rows = [r for rec in d["records"] for r in rec["rows"]]
    check("W4b 每列都有 name/value/bucket 三個欄位",
          all({"name", "value", "bucket"} <= set(r) for r in rows), f"{len(rows)} 列")
    check("W4c pages 與 records 的 source_page 一致",
          set(d["pages"]) == {r["source_page"] for r in d["records"]})
    check("W4d 沒抄的格回 None", webdata.cell_detail("209904_9999_AI3|AC") is None)


def w5_todo_disjoint():
    """待抄的格**不可以**同時是已抄的格。兩邊各自算就是下一個假綠燈。"""
    import facts as facts_mod
    import fill
    cells = facts_mod.load()
    todo = webdata.todo_cells()
    overlap = [t for t in todo if t["key"] in cells]
    check("W5a 待抄與已抄不重疊", not overlap, f"{len(todo)} 格待抄")
    ov = webdata.overview()
    idx = fill._load_index()
    bmap = idx.get("basis") or {}
    todo_this_basis = [t for t in todo if bmap.get(t["doc"]) == ov["basis"]]
    check("W5b 待抄數(同口徑)= overview 的 todo 統計",
          len(todo_this_basis) == ov["stats"]["todo"],
          f"{len(todo_this_basis)} vs {ov['stats']['todo']}")


def w6_confirm_bucket_writes():
    """收錄寫進 SYN。用 tmp 副本,**真的 buckets.py 不准動**。"""
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "buckets_copy.py")
        shutil.copy("buckets.py", p)
        before = open(p, encoding="utf-8").read()
        import buckets
        saved = dict(buckets._SYN_N)
        try:
            r = webdata.confirm_bucket("__測試科目__", "公債", "測試理由",
                                        today="2026-07-29", path=p,
                                        blocked_dir=tmp)  # 隔離,不碰真實 work/blocked/
            after = open(p, encoding="utf-8").read()
            check("W6a 有寫入", r["written"] and len(after) > len(before))
            check("W6b 寫的是合法桶名且名字在裡面",
                  "'__測試科目__': '公債'" in after)
            check("W6c 理由與日期進了註解",
                  "測試理由" in after and "2026-07-29" in after)
        finally:
            buckets._SYN_N.clear()
            buckets._SYN_N.update(saved)
    finally:
        shutil.rmtree(tmp)


def w7_confirm_bucket_rejects_bad_bucket():
    """**桶名不在 config.BUCKETS 就要炸**。打錯字會變成一個永遠對不到的新桶,
    而且沒有任何下游檢查抓得到(金額照樣加得對,錯的只有那一桶)。"""
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "buckets_copy.py")
        shutil.copy("buckets.py", p)
        before = open(p, encoding="utf-8").read()
        raised = False
        try:
            webdata.confirm_bucket("__測試科目2__", "公倩", "打錯字", path=p)
        except ValueError:
            raised = True
        check("W7a 不合法桶名會擋下來", raised)
        check("W7b 擋下來時檔案沒被改", open(p, encoding="utf-8").read() == before)
    finally:
        shutil.rmtree(tmp)


def w8_queue_view_groups_by_name():
    """裁示台按名字批次(2026-07-30 加,plan_web_complete.md W1)。

    人真正要做的決定數是不重複名字數,不是出現次數——138 筆出現處在今天
    的資料上只對應 31 個不重複名字,查一次就该看到 31 張卡,不是 138 張。
    """
    v = webdata.queue_view()
    names = [g["name"] for g in v["groups"]]
    check("W8a 名字不重複", len(names) == len(set(names)))
    check("W8b occurrences 加總與 pending() 一致",
          v["occurrences"] == len(webdata.pending_entries()))
    has_sugg = [g["suggested"] is not None for g in v["groups"]]
    # 一旦出現過 True,後面不准再出現 False —— 沒建議的必須全部排在有建議的之前。
    flips = sum(1 for i in range(1, len(has_sugg)) if has_sugg[i] < has_sugg[i - 1])
    check("W8c 沒建議的排最前面(只切一次,不交錯)", flips == 0)
    if v["groups"]:
        g0 = v["groups"][0]
        check("W8d 每組帶 cells 清單", isinstance(g0["cells"], list) and g0["cells"])


def w9_confirm_bucket_unsticks_fully_resolved_blocked():
    """收錄一個名字後,**只有全部提案名字都解了的 blocked 檔才放行**
    (2026-07-30 加)。同一個 blocked 檔可能列了好幾個名字,其中一個先被
    收錄不代表整格解套——這是 `fill.py` 自己的手動流程(「收錄後 requeue」)
    在網頁上的等價物,漏了會讓「收錄」按了跟沒按一樣(pending 數不會少)。
    """
    btmp = tempfile.mkdtemp()
    ctmp = tempfile.mkdtemp()
    try:
        p = os.path.join(ctmp, "buckets_copy.py")
        shutil.copy("buckets.py", p)
        import buckets
        saved = dict(buckets._SYN_N)
        try:
            # 兩個提案名字都還沒解 → 都收錄了才放行
            only_one = os.path.join(btmp, "docA__ClsA.json")
            json.dump({"proposals": [{"name": "__W9甲__", "bucket": "公債"},
                                     {"name": "__W9乙__", "bucket": "股票"}]},
                      open(only_one, "w", encoding="utf-8"))

            r1 = webdata.confirm_bucket("__W9甲__", "公債", "t", path=p, blocked_dir=btmp)
            check("W9a 只解一半,檔案還在(不放行)",
                  os.path.exists(only_one) and only_one.replace("__", "|") not in
                  [x.replace(btmp + "/", "") for x in r1["unstuck"]])
            check("W9b 只解一半,unstuck 是空的", r1["unstuck"] == [])

            r2 = webdata.confirm_bucket("__W9乙__", "股票", "t", path=p, blocked_dir=btmp)
            check("W9c 兩個都解了,檔案被清掉(放行)", not os.path.exists(only_one))
            check("W9d unstuck 回報那一格", r2["unstuck"] == ["docA|ClsA"])
        finally:
            buckets._SYN_N.clear()
            buckets._SYN_N.update(saved)
    finally:
        shutil.rmtree(btmp)
        shutil.rmtree(ctmp)


#: 用真實的 doc(pdf_cache/ 裡真的有這份 PDF),edit_row 收工時會呼叫
#: `locate.locate()` 算即時檢查——編造一個不存在的檔名會在那一步就炸掉,
#: 跟這裡要測的東西(row_index 對不對、_src 有沒有蓋、格式有沒有守住)無關。
_EDIT_DOC, _EDIT_CLS = "202404_5843_AI3", "Trading"
_EDIT_KEY = f"{_EDIT_DOC}|{_EDIT_CLS}"


def _edit_fixture(tmp):
    """一份最小事實庫,寫進 tmp facts_dir,回傳該目錄。"""
    rec = {"doc": _EDIT_DOC, "class": _EDIT_CLS,
           "source_page": 20, "source_kind": "附註",
           "total_col": "114年6月30日", "printed_total": 100,
           "rows": [{"name": "公司債", "cols": {"114年6月30日": 60}},
                    {"name": "金融債券", "cols": {"114年6月30日": 40}}]}
    facts.save({_EDIT_KEY: [rec]}, facts_dir=tmp)


def w10_edit_row_add():
    """新增一列:附加到尾端,蓋上 `_src`。"""
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)
        r = webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, None,
                             {"name": "政府公債", "cols": {"114年6月30日": 10}},
                             "補抄漏掉的一列", by="test", today="2026-07-30T00:00",
                             facts_dir=tmp)
        check("W10a 回報 saved", r["saved"])
        cells = facts.load(facts_dir=tmp)
        rows = cells[_EDIT_KEY][0]["rows"]
        check("W10b 列數變 3", len(rows) == 3)
        check("W10c 新列在尾端且是政府公債", rows[-1]["name"] == "政府公債")
        check("W10d 新列蓋了 _src", rows[-1].get("_src", {}).get("by") == "test")
    finally:
        shutil.rmtree(tmp)


def w11_edit_row_replace():
    """改一列:name/cols 都能改,一樣蓋 `_src`,其他列不動。"""
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)
        r = webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, 0,
                             {"name": "公司債（附註十一）", "cols": {"114年6月30日": 61}},
                             "文字層少抄一位數字", by="test", facts_dir=tmp)
        check("W11a 回報 saved", r["saved"])
        rows = facts.load(facts_dir=tmp)[_EDIT_KEY][0]["rows"]
        check("W11b 第 0 列改名了", rows[0]["name"] == "公司債（附註十一）")
        check("W11c 第 0 列數字改了", rows[0]["cols"]["114年6月30日"] == 61)
        check("W11d 第 0 列蓋了 _src", "_src" in rows[0])
        check("W11e 第 1 列沒被動到", rows[1]["name"] == "金融債券" and "_src" not in rows[1])
    finally:
        shutil.rmtree(tmp)


def w12_edit_row_delete():
    """刪一列:少一列,沒有東西可以掛 _src(那一列已經不存在了)。"""
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)
        r = webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, 1, None,
                             "重複列,抄兩次了", by="test", facts_dir=tmp)
        check("W12a 回報 saved", r["saved"])
        rows = facts.load(facts_dir=tmp)[_EDIT_KEY][0]["rows"]
        check("W12b 剩 1 列", len(rows) == 1)
        check("W12c 剩下的是公司債(第 1 列金融債券被刪)", rows[0]["name"] == "公司債")
    finally:
        shutil.rmtree(tmp)


def w13_edit_row_requires_why():
    """沒填 why 一定要擋下來——這是唯一的品質控制。"""
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)
        raised = False
        try:
            webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, 0,
                             {"name": "x", "cols": {"114年6月30日": 1}}, "",
                             facts_dir=tmp)
        except webdata.EditError:
            raised = True
        check("W13a 空白 why 被擋下來", raised)
        rows = facts.load(facts_dir=tmp)[_EDIT_KEY][0]["rows"]
        check("W13b 擋下來時資料沒被改", rows[0]["name"] == "公司債")
    finally:
        shutil.rmtree(tmp)


def w14_edit_row_schema_still_enforced():
    """`_src` 不是通行證——float 混進 cols 一樣要被 facts.validate() 擋下來,
    而且擋下來時**完全沒有寫入**(不是寫一半)。"""
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)
        raised = False
        try:
            webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, 0,
                             {"name": "公司債", "cols": {"114年6月30日": 60.5}},
                             "手滑打了小數", facts_dir=tmp)
        except webdata.EditError:
            raised = True
        check("W14a 格式違規被擋下來", raised)
        rows = facts.load(facts_dir=tmp)[_EDIT_KEY][0]["rows"]
        check("W14b 擋下來時資料沒被改", rows[0]["cols"]["114年6月30日"] == 60)
    finally:
        shutil.rmtree(tmp)


def w15_edit_row_reports_checks_without_blocking():
    """六道語意檢查算出來附在回傳值裡,**不阻擋寫入**——即使錨對不上
    (這裡故意把印出合計改到跟錨差很遠),還是要存進去,只是 checks.ok=False。
    """
    tmp = tempfile.mkdtemp()
    try:
        _edit_fixture(tmp)  # printed_total=100,錨(真實 202404_5843_AI3 Trading)是 58,831,126,差很遠
        r = webdata.edit_row(_EDIT_DOC, _EDIT_CLS, 0, 0,
                             {"name": "公司債", "cols": {"114年6月30日": 61}},
                             "文字層本身壞掉,人工核對過就是這個數字", facts_dir=tmp)
        check("W15a 錨對不上仍然寫入了", r["saved"])
        check("W15b checks.ok 誠實回報 False", r["checks"]["ok"] is False)
        check("W15c 有列出哪一道不過", bool(r["checks"]["problems"]))
    finally:
        shutil.rmtree(tmp)


def w22b_ratify_fills_dash_row_and_drops_bad_printed_totals():
    """**2026-07-30 使用者實測抓到的真 bug**:`ratify()` 原本不套用
    `core/derive.py` 的「破折號列補 0」與「丟掉對不上的 printed_totals」——
    導致人工歸檔的格子永久卡著這兩種問題,每次開這格 check_identity /
    check_col_totals 都報同一個錯,而使用者的原話是「就應該當作是零啊」。

    這支鎖住修好之後的行為:破折號列(缺 total_col 那一欄)補 0、
    對不上的 printed_totals 欄被丟掉、對得上的保留。
    """
    tmp = tempfile.mkdtemp()
    try:
        rec = {"doc": _EDIT_DOC, "class": _EDIT_CLS,
               "source_page": 34, "source_kind": "附註",
               "total_col": "114年6月30日", "printed_total": 60,
               "printed_totals": {"113年6月30日": 999},   # 故意對不上
               "rows": [
                   {"name": "公司債", "cols": {"114年6月30日": 60, "113年6月30日": 55}},
                   {"name": "基金受益憑證", "cols": {"113年6月30日": 39428}},  # 破折號列
               ]}
        r = webdata.ratify(_EDIT_DOC, _EDIT_CLS, [rec], "回歸測試", facts_dir=tmp)
        check("W22b-a 歸檔成功", r["saved"])
        saved_rec = facts.load(facts_dir=tmp)[_EDIT_KEY][0]
        check("W22b-b 破折號列補了 0",
              saved_rec["rows"][1]["cols"].get("114年6月30日") == 0)
        check("W22b-c 對不上的 printed_totals 被丟掉",
              "113年6月30日" not in (saved_rec.get("printed_totals") or {}))
        # 不斷言 r["checks"]["ok"] 整體是不是 True——`printed_total=60` 跟
        # `_EDIT_DOC`/`_EDIT_CLS` 真實的錨(58,831,126)差很遠,④合計==錨
        # 本來就會不過,那是這個 fixture 的另一件事,不是這支要測的東西。
        # 這支只認 check_identity/check_col_totals(受這次修補影響的那兩道)。
        import transcribe
        loc = locate.locate(f"pdf_cache/{_EDIT_DOC}.pdf")
        check("W22b-d ①②列相加現在過了(補 0 之後列和等於印出合計)",
              transcribe.check_identity(saved_rec) is None)
        check("W22b-e ⑥逐欄合計現在過了(丟掉對不上的欄之後)",
              transcribe.check_col_totals(saved_rec) is None)
    finally:
        shutil.rmtree(tmp)


def w22_ratify_writes_despite_failing_gate():
    """被拒收的一格,人裁示後**要寫得進去**——這是 `plan_web_usable.md` P4
    的全部重點。在這之前 rejected 的格子在網頁上是死路:指定頁沒用(頁是對的)、
    標記無資料是錯的(有資料)、退回重抄撞同一道閘門、手動貼 JSON 走 submit()
    也是同一道閘門。

    fixture 的 `printed_total=100` 跟真實錨(58,831,126)差很遠,所以六道**一定**
    有不過的——正好拿來證明「不過也照樣歸檔,但誠實回報」。
    """
    tmp = tempfile.mkdtemp()
    try:
        rec = {"doc": _EDIT_DOC, "class": _EDIT_CLS,
               "source_page": 20, "source_kind": "附註",
               "total_col": "114年6月30日", "printed_total": 100,
               "rows": [{"name": "公司債", "cols": {"114年6月30日": 60}},
                        {"name": "基金受益憑證", "cols": {}}]}   # 破折號列:此欄無值
        r = webdata.ratify(_EDIT_DOC, _EDIT_CLS, [rec],
                           "破折號列在合計欄本來就沒有值", by="test",
                           today="2026-07-30T00:00", facts_dir=tmp)
        check("W22a 六道不過仍然歸檔了", r["saved"])
        check("W22b checks.ok 誠實回報 False", r["checks"]["ok"] is False)
        check("W22c 有列出哪一道不過", bool(r["checks"]["problems"]))
        rows = facts.load(facts_dir=tmp)[_EDIT_KEY][0]["rows"]
        check("W22d 每一列都蓋上 _src", all("_src" in x for x in rows))
        check("W22e _src.why 存的是人給的理由",
              rows[0]["_src"]["why"] == "破折號列在合計欄本來就沒有值")
        # ⚠️ 2026-07-30 使用者實測抓到的真 bug:這裡原本斷言「破折號列原樣
        # 保留(沒被偷偷補 0)」——那其實是在替 bug 背書。修好之後
        # `ratify()` 跟自動路徑共用同一套「合計欄缺值補 0」邏輯
        # (`core/derive.fill_zero_for_col`),使用者的原話是
        # 「就應該當作是零啊」,見 w22b。
        check("W22f 破折號列在合計欄補了 0(跟自動路徑一致)",
              rows[1]["cols"].get("114年6月30日") == 0)
    finally:
        shutil.rmtree(tmp)


def w23_ratify_requires_why_and_keeps_schema():
    """裁示**不需要理由**(2026-07-30 使用者裁示,推翻原本 why 必填的決定——
    見 `core/webdata.ratify` docstring),但格式違規照擋、而且完全不寫入。

    ① 這一條是照 `memory/checks-must-fail` 加的——注入一個 float,如果它
    竟然過了,就代表 `ratify` 的驗證是恆真的,那整支就是廢的。
    """
    tmp = tempfile.mkdtemp()
    try:
        rec = {"doc": _EDIT_DOC, "class": _EDIT_CLS,
               "source_page": 20, "source_kind": "附註",
               "total_col": "114年6月30日", "printed_total": 100,
               "rows": [{"name": "公司債", "cols": {"114年6月30日": 60}}]}
        r = webdata.ratify(_EDIT_DOC, _EDIT_CLS, [rec], facts_dir=tmp)
        check("W23a 沒填 why 也能歸檔", r["saved"])
        saved_rec = facts.load(facts_dir=tmp)[_EDIT_KEY][0]
        check("W23a2 _src.by/at 仍然有標記(稽核軌跡不靠 why)",
              all("by" in x["_src"] and "at" in x["_src"] for x in saved_rec["rows"]))
        check("W23a3 沒給 why 就不寫入這個 key(不是空字串)",
              "why" not in saved_rec["rows"][0]["_src"])

        bad = json.loads(json.dumps(rec))
        bad["rows"][0]["cols"]["114年6月30日"] = 60.5
        raised = False
        try:
            webdata.ratify(_EDIT_DOC, _EDIT_CLS, [bad], "注入測試", facts_dir=tmp)
        except webdata.EditError:
            raised = True
        check("W23b float 仍然被 facts.validate 擋下來(閘門不是恆真的)", raised)
        # W23a 已經合法寫過一次,這裡不能再斷言檔案不存在——要驗證的是
        # 「壞資料沒有混進去」,不是「檔案是空的」。
        untouched = facts.load(facts_dir=tmp)[_EDIT_KEY][0]
        check("W23c 擋下來時沒有把壞資料寫進去(值還是合法的 60)",
              untouched["rows"][0]["cols"]["114年6月30日"] == 60)
    finally:
        shutil.rmtree(tmp)


#: cellmeta 測試用的假 doc|cls——不必是真的檔案,因為這幾支測的是**儲存與
#: 判斷邏輯**(set/clear/cell_status 怎麼看 cellmeta),不是抄列本身。
_CM_KEY_DOC, _CM_KEY_CLS = "__cm_test_doc__", "Trading"


def w16_set_cellmeta_requires_why():
    """跟 edit_row 同一個模式:沒填 why 一定要擋下來。"""
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "cellmeta.json")
        raised = False
        try:
            webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "no_data", True, "", path=p)
        except webdata.EditError:
            raised = True
        check("W16a 空白 why 被擋下來", raised)
        check("W16b 擋下來時檔案沒建立(或是空的)",
              not os.path.exists(p) or webdata.load_cellmeta(p) == {})
    finally:
        shutil.rmtree(tmp)


def w17_set_cellmeta_validates_field_and_pages_shape():
    """field 只認 pages/no_data;pages 一定要是非空整數清單
    (不能是空清單、不能混浮點數——那多半是使用者把頁碼打成小數點的手滑)。"""
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "cellmeta.json")
        bad_field = bad_empty = bad_float = False
        try:
            webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "wrong_field", 1, "x", path=p)
        except webdata.EditError:
            bad_field = True
        try:
            webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "pages", [], "x", path=p)
        except webdata.EditError:
            bad_empty = True
        try:
            webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "pages", [1.5], "x", path=p)
        except webdata.EditError:
            bad_float = True
        check("W17a 不認得的 field 被擋下來", bad_field)
        check("W17b 空清單被擋下來", bad_empty)
        check("W17c 浮點數頁碼被擋下來", bad_float)
    finally:
        shutil.rmtree(tmp)


def w18_set_and_clear_cellmeta_roundtrip():
    """設定 → 讀到 → 清除 → 讀不到;清除不影響同一格的其他 field。"""
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "cellmeta.json")
        webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "pages", [10, 11],
                             "抄到彙總層,指定明細表那頁", by="test", path=p)
        webdata.set_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "no_data", True,
                             "順便測兩個 field 共存", by="test", path=p)
        meta = webdata.load_cellmeta(p)
        key = f"{_CM_KEY_DOC}|{_CM_KEY_CLS}"
        check("W18a 兩個 field 都讀得到", "pages" in meta[key] and "no_data" in meta[key])
        check("W18b pages 值正確", meta[key]["pages"]["value"] == [10, 11])

        r = webdata.clear_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "pages", path=p)
        meta = webdata.load_cellmeta(p)
        check("W18c 清除回報 cleared", r["cleared"])
        check("W18d pages 沒了", "pages" not in meta.get(key, {}))
        check("W18e no_data 還在(清除不是清空整格)", meta[key]["no_data"]["value"] is True)

        r2 = webdata.clear_cellmeta(_CM_KEY_DOC, _CM_KEY_CLS, "pages", path=p)
        check("W18f 清不存在的 field 回報 False,不炸", r2["cleared"] is False)
    finally:
        shutil.rmtree(tmp)


def w19_cell_status_no_data_wins_over_everything():
    """`no_data` 是人下的最終判斷,優先於 done/blocked/rejected/todo——
    即使這格剛好也在 `cells`(facts)裡,no_data 還是要贏,因為那本身
    就是矛盾,不該讓機器狀態偷偷蓋過去。"""
    key = f"{_CM_KEY_DOC}|{_CM_KEY_CLS}"
    cellmeta = {key: {"no_data": {"value": True, "by": "t", "at": "t", "why": "t"}}}
    st = webdata.cell_status({key: [{}]}, {key}, {key},
                             {"cells": {_CM_KEY_DOC: {_CM_KEY_CLS: True}}},
                             _CM_KEY_DOC, _CM_KEY_CLS, cellmeta)
    check("W19 no_data 贏過 done/blocked/rejected/todo 全部", st == "no_data")


def w20_cell_status_pages_override_unlocks_na():
    """`index` 說候選頁是空的(今天 2 格的真實情況:錨有、grep 找不到頁),
    但 cellmeta 有 pages 覆寫 → 算 todo,不是 na。"""
    key = f"{_CM_KEY_DOC}|{_CM_KEY_CLS}"
    index_empty = {"cells": {_CM_KEY_DOC: {_CM_KEY_CLS: False}}}
    st_before = webdata.cell_status({}, set(), set(), index_empty, _CM_KEY_DOC, _CM_KEY_CLS, {})
    st_after = webdata.cell_status({}, set(), set(), index_empty, _CM_KEY_DOC, _CM_KEY_CLS,
                                   {key: {"pages": {"value": [5], "by": "t", "at": "t", "why": "t"}}})
    check("W20a 沒有覆寫時是 na(基準)", st_before == "na")
    check("W20b 有 pages 覆寫時變 todo", st_after == "todo")


def w21_effective_pages_override_wins():
    """`effective_pages()`:覆寫優先於 `loc.pages`,沒覆寫就照舊。"""
    class FakeLoc:
        pages = {"Trading": [1, 2, 3]}
    key = "docX|Trading"
    check("W21a 沒覆寫,回原本候選頁",
          webdata.effective_pages(FakeLoc(), "docX", "Trading", {}) == [1, 2, 3])
    check("W21b 有覆寫,回覆寫值",
          webdata.effective_pages(FakeLoc(), "docX", "Trading",
                                  {key: {"pages": {"value": [9]}}}) == [9])
    check("W21c 沒有這個 class 的候選頁也不炸(回空清單)",
          webdata.effective_pages(FakeLoc(), "docX", "OCI", {}) == [])


if __name__ == "__main__":
    for fn in (w1_scope, w2_overview, w3_source_page_is_zero_based,
               w4_cell_detail_shape, w5_todo_disjoint,
               w6_confirm_bucket_writes, w7_confirm_bucket_rejects_bad_bucket,
               w8_queue_view_groups_by_name,
               w9_confirm_bucket_unsticks_fully_resolved_blocked,
               w10_edit_row_add, w11_edit_row_replace, w12_edit_row_delete,
               w13_edit_row_requires_why, w14_edit_row_schema_still_enforced,
               w15_edit_row_reports_checks_without_blocking,
               w16_set_cellmeta_requires_why,
               w17_set_cellmeta_validates_field_and_pages_shape,
               w18_set_and_clear_cellmeta_roundtrip,
               w19_cell_status_no_data_wins_over_everything,
               w20_cell_status_pages_override_unlocks_na,
               w21_effective_pages_override_wins,
               w22_ratify_writes_despite_failing_gate,
               w22b_ratify_fills_dash_row_and_drops_bad_printed_totals,
               w23_ratify_requires_why_and_keeps_schema):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
