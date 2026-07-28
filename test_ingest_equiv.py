#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ingest_equiv.py — C3-a A1 的 E5 等價閘門

    對 facts/ 的 36 格走 transcriber.replay:
        old = fill.cmd_submit 的判斷邏輯(這裡就地複刻,不寫檔案)
        new = core.ingest.classify_outcome(..., use_policy=False)
    斷言:36/36 outcome 相同、訊息逐字相同、level 相同。

    另外四條出口(PASS/BLOCKED/RETRY/REJECT)各一個合成案例,
    斷言 core.ingest.classify_outcome 各自走到正確出口。

執行方式: python3 test_ingest_equiv.py
exit 0 = 全綠
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fill
import facts
import locate
import pipeline
import transcribe
import transcriber
from core import ingest

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


class _FakeLoc:
    """給合成案例用的最小假 loc —— 只提供 classify_outcome 用得到的介面。"""

    def __init__(self, anchors, expand_pages=None):
        self.anchors = anchors
        self._expand_pages = expand_pages or {}

    def expand(self, cls, level):
        return self._expand_pages.get(level, [])


def _old_outcome(doc, cls, recs, loc, level, pages, retries):
    """就地複刻 fill.cmd_submit 的判斷(不含 I/O),當作 A1 的參照組。"""
    ok_, reason, res, problems = False, "抄不出來(records 為空)", {}, None
    if recs:
        problems = facts.validate({f"{doc}|{cls}": recs})
        if problems:
            reason = "; ".join(problems)
        else:
            ok_, res = transcribe.verify(recs, loc)
            if not ok_:
                reason = "; ".join(f"{k}:{v}" for k, v in res.items() if v)

    if ok_:
        return "PASS", f"PASS      已歸檔進 facts/{doc}.json({cls})。", level

    gap = fill._taxonomy_gap(recs, loc) if recs and not problems else None
    if gap:
        return ("BLOCKED",
                "BLOCKED   這格卡在**分類表缺口**,不是你抄錯 —— "
                "擴頁修不好這種失敗,所以不擴了。", level)

    new_level = level + 1
    more = loc.expand(cls, new_level) if new_level <= pipeline.MAX_LEVEL else []
    new_pages = sorted(set(pages) | set(more))
    if new_level > pipeline.MAX_LEVEL or not more or new_pages == pages:
        return ("REJECT",
                f"REJECT    擴張到上限仍對不上,已進 work/rejected/{doc}__{cls}.json。",
                new_level - 1)
    return "RETRY", f"RETRY     沒過:{reason}", new_level


def test_e5_replay():
    label = "E5: facts/ 36 格 replay,old vs core.ingest.classify_outcome(use_policy=False)"
    cells = facts.load()
    transcribe_fn = transcriber.replay(cells)

    total = 0
    mismatches = []
    for key, recs in cells.items():
        doc, cls = key.split("|", 1)
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        pages = list(loc.pages[cls])
        got_recs = transcribe_fn(doc, cls, None)  # replay 忽略 prompt,直接回事實庫

        total += 1
        old_outcome, old_msg, old_level = _old_outcome(doc, cls, got_recs, loc, 0, pages, 0)
        new = ingest.classify_outcome(doc, cls, got_recs, loc, 0, pages, 0,
                                       pipeline.MAX_LEVEL, use_policy=False)

        if (new["outcome"], new["message"], new["level"]) != (old_outcome, old_msg, old_level):
            mismatches.append((key, old_outcome, new["outcome"], old_msg, new["message"],
                               old_level, new["level"]))

    if not mismatches:
        ok(label, f"({total}/{total} 相同)")
    else:
        fail(label, f"{len(mismatches)}/{total} 格不同")
        for m in mismatches[:10]:
            print(f"    {m}")
    return total, len(mismatches)


def test_four_exits():
    label = "四條出口各一個合成案例"
    all_ok = True

    # PASS —— 拿一格真實 record 原封不動送進去
    cells = facts.load()
    any_key = sorted(cells)[0]
    doc0, cls0 = any_key.split("|", 1)
    loc0 = locate.locate(f"pdf_cache/{doc0}.pdf")
    r = ingest.classify_outcome(doc0, cls0, cells[any_key], loc0, 0,
                                 list(loc0.pages[cls0]), 0, pipeline.MAX_LEVEL,
                                 use_policy=False)
    all_ok &= (r["outcome"] == "PASS")
    print(f"  {'OK' if r['outcome']=='PASS' else 'FAIL'}  PASS 合成案例 → {r['outcome']}")

    # BLOCKED —— 一列改成 taxonomy 認不得、但 rules.propose() 提得出桶的名字
    #   「承兌匯票」不在 buckets.SYN,但命中 KEYS['貨幣市場'] 的關鍵字「承兌匯票」。
    rec_blocked = {"doc": "X", "class": "Trading", "source_page": 1,
                   "source_kind": "附註", "total_col": "113年12月31日",
                   "printed_total": 1000, "rows": [
                       {"name": "承兌匯票", "cols": {"113年12月31日": 1000}}]}
    loc_b = _FakeLoc({"Trading": 1000})
    rb = ingest.classify_outcome("X", "Trading", [rec_blocked], loc_b, 0, [1], 0,
                                  pipeline.MAX_LEVEL, use_policy=False)
    all_ok &= (rb["outcome"] == "BLOCKED")
    print(f"  {'OK' if rb['outcome']=='BLOCKED' else 'FAIL'}  BLOCKED 合成案例 → {rb['outcome']}"
          f"  msg={rb['message']!r}")

    # RETRY —— printed_total 改掉讓 ①②/④ 失敗,level < MAX_LEVEL,擴頁擴得出新頁
    rec_retry = {"doc": "X", "class": "Trading", "source_page": 1,
                 "source_kind": "附註", "total_col": "113年12月31日",
                 "printed_total": 999, "rows": [
                     {"name": "公司債", "cols": {"113年12月31日": 500}}]}
    loc_r = _FakeLoc({"Trading": 999}, expand_pages={1: [99]})
    rr = ingest.classify_outcome("X", "Trading", [rec_retry], loc_r, 0, [1], 0,
                                  pipeline.MAX_LEVEL, use_policy=False)
    all_ok &= (rr["outcome"] == "RETRY")
    print(f"  {'OK' if rr['outcome']=='RETRY' else 'FAIL'}  RETRY 合成案例 → {rr['outcome']}"
          f"  msg={rr['message']!r}")

    # REJECT —— 同 RETRY,但 level 已達 MAX_LEVEL
    loc_j = _FakeLoc({"Trading": 999}, expand_pages={pipeline.MAX_LEVEL + 1: [99]})
    rj = ingest.classify_outcome("X", "Trading", [rec_retry], loc_j, pipeline.MAX_LEVEL,
                                  [1], 0, pipeline.MAX_LEVEL, use_policy=False)
    all_ok &= (rj["outcome"] == "REJECT")
    print(f"  {'OK' if rj['outcome']=='REJECT' else 'FAIL'}  REJECT 合成案例 → {rj['outcome']}"
          f"  msg={rj['message']!r}")

    if all_ok:
        ok(label)
    else:
        fail(label)
    return all_ok


def main():
    print("=" * 60)
    print("test_ingest_equiv.py — C3-a A1 E5 等價閘門")
    print("=" * 60)
    total, mismatches = test_e5_replay()
    four_ok = test_four_exits()

    print("=" * 60)
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    print(f"E5: {total - mismatches}/{total} 格相同")
    if FAIL > 0:
        print("RESULT: FAIL")
        sys.exit(1)
    print("RESULT: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
