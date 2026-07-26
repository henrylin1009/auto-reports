# -*- coding: utf-8 -*-
"""遞迴錨 grep 實驗:主附註頁上的每個數字,都當成下一輪的錨再 grep 一次。

動機:富邦附註是兩層(主附註給總數、子附註給明細),明細頁不印 BS 錨,
所以單層 grep 撈不到。見 202402_5836 p38/p39。

設計:定位放寬、驗證收緊。這裡只負責把 p39 這種頁撈進候選,
「這頁是不是真的明細」由抄列時的 sum(逐項)==小計 決定,不在這裡判。

MIN_GROUPS 是唯一的旋鈕(數字要有幾組千分位才算候選小計),
故附掃描:不同值下候選頁會膨脹多少。
"""
import re
import sys
import os

sys.path.insert(0, os.getcwd())
import locate

NUM = re.compile(r"\d{1,3}(?:,\d{3})+")


def subanchors(txt, min_groups):
    """頁上所有夠大的數字,去重。"""
    out = set()
    for m in NUM.findall(txt):
        if m.count(",") >= min_groups:
            out.add(m)
    return out


def expand(loc, cls, min_groups):
    """回傳 (第一層頁, 第二層新增頁)。"""
    lvl1 = loc.pages[cls]
    if not lvl1:
        return [], []
    subs = set()
    for i in lvl1:
        subs |= subanchors(loc.text(i), min_groups)
    subs.discard(f"{loc.anchors[cls]:,}")
    lvl2 = []
    for i, t in enumerate(loc.texts):
        if i in lvl1 or i == loc.bs_page:
            continue
        if any(s in t for s in subs):
            lvl2.append(i)
    return lvl1, lvl2


if __name__ == "__main__":
    docs = sys.argv[1:] or ["202402_5836_AI3"]
    for g in (2, 3, 4):
        print(f"\n===== MIN_GROUPS={g}(數字 ≥ {10**(3*g):,} 才當子錨)=====")
        for d in docs:
            loc = locate.locate(f"pdf_cache/{d}.pdf")
            for cls in ("Trading", "OCI", "AC"):
                if cls not in loc.anchors:
                    continue
                a, b = expand(loc, cls, g)
                print(f"  {d} {cls:<8} 第1層 {a}  第2層新增 {len(b)} 頁 {b[:12]}")
