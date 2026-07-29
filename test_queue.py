#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_queue.py — S0 佇列合流驗收 (Q1-Q6)

**背景(這支測試存在的理由)**:人工待辦分散在兩個互不相干的地方——

    core/decision_store.py  →  review/queue.jsonl        (B4 的三種處置)
    fill.py                 →  work/blocked/*.json       (分類表缺口卡住的格)
                               work/proposals.jsonl      (待收錄的科目名提案)

`core/workbench.py` 只讀第一個。實際資料裡第一個**檔案根本不存在**、第二個
有 8 筆提案 1 格卡住,所以畫面顯示「待審 0」是假綠燈——比缺功能危險。

Q6 是這支測試的重點:**它必須在 core/queue.py 出現之前就是紅的**,
否則就是個恆真閘門。

**一律寫 tmp workspace,真實 work/ 與 review/ 全程唯讀。**

執行方式: python3 test_queue.py       exit 0 = 全綠
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


def eq(label, got, want):
    ok(label) if got == want else fail(label, f"got {got!r}, want {want!r}")


# ── tmp workspace 建構 ────────────────────────────────────────────────

def mkws(blocked=None, proposals=None, review=None):
    """建一個只有指定內容的 workspace。回傳路徑,呼叫者負責 shutil.rmtree。"""
    ws = tempfile.mkdtemp(prefix="q_")
    if blocked:
        os.makedirs(f"{ws}/work/blocked")
        for name, payload in blocked.items():
            json.dump(payload, open(f"{ws}/work/blocked/{name}.json", "w",
                                    encoding="utf-8"), ensure_ascii=False)
    if proposals is not None:
        os.makedirs(f"{ws}/work", exist_ok=True)
        with open(f"{ws}/work/proposals.jsonl", "w", encoding="utf-8") as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    if review is not None:
        os.makedirs(f"{ws}/review", exist_ok=True)
        with open(f"{ws}/review/queue.jsonl", "w", encoding="utf-8") as f:
            for e in review:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return ws


BLOCKED_SAMPLE = {
    "202504_5847_AI3__AC": {
        "doc": "202504_5847_AI3", "cls": "AC", "level": 1,
        "reason": "⑤列皆可分桶@p127:3 列對不到桶",
        "proposals": [
            {"name": "可轉讓定期存單（註三）", "bucket": "可轉讓定存單",
             "why": "BUCKET_RULES 關鍵字「可轉讓定期存單」"},
            {"name": "國外機構發行債券（註二）", "bucket": None,
             "why": "BUCKET_RULES 沒有任何關鍵字命中,需要人工新增規則"},
        ],
        "submitted": {"records": []},
    }
}

REVIEW_SAMPLE = [{
    "cell_key": "202404_5835_AI3|OCI",
    "decision": {"name": "某科目", "group": None, "state": "UNCLASSIFIED",
                 "mapping": None,
                 "occurrence": {"record_fp": "aa", "row_fp": "bb", "scope": "name"}},
}]


# ── Q1-Q5:core.queue 的行為 ──────────────────────────────────────────

def test_queue_module():
    import core.queue as Q

    ws = mkws()
    try:
        eq("Q1 空 workspace 回空清單", Q.pending(ws), [])
    finally:
        shutil.rmtree(ws)

    ws = mkws(review=REVIEW_SAMPLE)
    try:
        got = Q.pending(ws)
        eq("Q2 讀得到 review/queue.jsonl", len(got), 1)
        eq("Q2b 來源標成 review", got[0]["source"], "review")
        eq("Q2c 帶得出 cell_key", got[0]["cell_key"], "202404_5835_AI3|OCI")
    finally:
        shutil.rmtree(ws)

    ws = mkws(blocked=BLOCKED_SAMPLE)
    try:
        got = Q.pending(ws)
        # 一格卡住裡有 2 個提案 → 2 筆待辦(每個科目名各自要裁示)
        eq("Q3 讀得到 work/blocked/ 的提案", len(got), 2)
        eq("Q3b 來源標成 blocked", {g["source"] for g in got}, {"blocked"})
        eq("Q3c cell_key 由檔名還原", {g["cell_key"] for g in got},
           {"202504_5847_AI3|AC"})
        names = {g["name"]: g["suggested"] for g in got}
        eq("Q3d 有建議桶的帶得出來", names["可轉讓定期存單（註三）"], "可轉讓定存單")
        eq("Q3e 沒建議的是 None,不准瞎猜", names["國外機構發行債券（註二）"], None)
    finally:
        shutil.rmtree(ws)

    ws = mkws(blocked=BLOCKED_SAMPLE, review=REVIEW_SAMPLE)
    try:
        got = Q.pending(ws)
        eq("Q4 兩邊合流", len(got), 3)
        eq("Q4b 兩種 source 都在", {g["source"] for g in got}, {"blocked", "review"})
    finally:
        shutil.rmtree(ws)

    # count() 必須跟 pending() 一致 —— 兩個數字不同步就是下一個假綠燈
    ws = mkws(blocked=BLOCKED_SAMPLE, review=REVIEW_SAMPLE)
    try:
        eq("Q5 count() 與 pending() 一致", Q.count(ws), len(Q.pending(ws)))
    finally:
        shutil.rmtree(ws)


# ── Q6:假綠燈的回歸測試 ──────────────────────────────────────────────

def test_no_false_green():
    """**這條必須在修好之前是紅的。**

    只有 work/blocked/ 有東西、review/queue.jsonl 不存在時,對外報出來的
    待辦數字不准是 0 —— 那正是真實資料現在的狀態。
    """
    import core.queue as Q
    ws = mkws(blocked=BLOCKED_SAMPLE)          # 刻意不建 review/queue.jsonl
    try:
        n = Q.count(ws)
        if n > 0:
            ok(f"Q6 只有 blocked 時待辦數 = {n}(不是假的 0)")
        else:
            fail("Q6 假綠燈", "work/blocked/ 有東西,待辦數卻是 0")
    finally:
        shutil.rmtree(ws)


if __name__ == "__main__":
    print("== S0 佇列合流 ==")
    try:
        test_queue_module()
        test_no_false_green()
    except ImportError as e:
        fail("import", f"{e} —— core/queue.py 還沒寫")
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
