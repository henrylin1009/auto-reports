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
    """四種狀態互斥且加總 = 檔數 × 3 類。**格數對不上就是有格子靜靜消失了**,
    那正是這個專案踩過兩次的坑(先漏 AI1、修完又漏 AI2)。"""
    ov = webdata.overview()
    st = ov["stats"]
    n_docs = len(webdata.docs_in_scope())
    total = sum(st.values())
    check("W2a 狀態加總 = 檔數 × 3 類", total == n_docs * 3,
          f"{total} vs {n_docs}×3={n_docs * 3}")
    check("W2b grid 每份檔都有一格", len(ov["grid"]) == n_docs,
          f"{len(ov['grid'])} vs {n_docs}")
    # 欄位是從資料推導的,不是寫死的列舉
    cols_from_docs = {d.split("_", 1)[1].replace("_", " ") for d in webdata.docs_in_scope()}
    check("W2c 欄位集合由資料推導", set(ov["cols"]) == cols_from_docs,
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
    cells = facts_mod.load()
    todo = webdata.todo_cells()
    overlap = [t for t in todo if t["key"] in cells]
    check("W5a 待抄與已抄不重疊", not overlap, f"{len(todo)} 格待抄")
    ov = webdata.overview()
    check("W5b 待抄數 = overview 的 todo 統計", len(todo) == ov["stats"]["todo"],
          f"{len(todo)} vs {ov['stats']['todo']}")


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
                                        today="2026-07-29", path=p)
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


if __name__ == "__main__":
    for fn in (w1_scope, w2_overview, w3_source_page_is_zero_based,
               w4_cell_detail_shape, w5_todo_disjoint,
               w6_confirm_bucket_writes, w7_confirm_bucket_rejects_bad_bucket):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
