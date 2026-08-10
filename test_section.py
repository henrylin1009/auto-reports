# -*- coding: utf-8 -*-
"""章節切分回歸測試(快):釘住四份已人工查過的文件,不跑全語料。

全語料回歸請跑 `python3 test_section.py --full`(約 2 分鐘):
    ① 155 格已驗收的每一份附註 record 都必須落在某個章節內(基準 144/144)
    ② `locate.EXPAND_TRUTH` 的 11 格必須不擴頁就被涵蓋(基準 11/11)
兩個數字掉下來就是切分行為變了 —— 修 bug,或確認是改進後更新這裡的基準。

用法:python3 test_section.py [--full]
"""
import sys

import locate
import section

#: (檔名, 類別, 必須被涵蓋的頁(0-based), 最小章節的頁數上界)
#: 頁數上界不是精確值,是「別悄悄變大」的警戒線 —— 章節撐大代表切分器漏認了
#: 某一層標題,而那會讓工單成本失控(未切細之前中位是 58 頁)。
CASES = [
    # 富邦 2023 年報 OCI:主表(兩列)+ 子附註(一)(二)同章。經典的兩層附註。
    ("202304_5836_AI3", "OCI", 40, 4),
    # 富邦 2023 年報 Trading:同頁三段(指定/強制/衍生),三段小計相加 == 錨。
    ("202304_5836_AI3", "Trading", 38, 4),
    # 玉山 2021H1 OCI:子附註在下一頁 —— 現行管線要靠擴頁才找得到。
    ("202102_5847_AI3", "OCI", 24, 4),
    # 中信合併 2024Q1 OCI:債務小計在前一頁,跨頁表。
    ("202401_5841_AI1", "OCI", 15, 4),
]


def _units(doc, cls):
    return section.units(locate.locate(f"pdf_cache/{doc}.pdf"), cls)


def quick():
    bad = 0
    for doc, cls, need, cap in CASES:
        us = _units(doc, cls)
        if not us:
            print(f"✗ {doc} {cls}:切不出任何章節")
            bad += 1
            continue
        hit = [u for u in us if u[0] <= need <= u[1]]
        if not hit:
            print(f"✗ {doc} {cls}:需 p.{need + 1},章節 "
                  f"{[(a + 1, b + 1) for a, b in us]} 都沒涵蓋")
            bad += 1
            continue
        n = min(b - a + 1 for a, b in hit)
        if n > cap:
            print(f"✗ {doc} {cls}:涵蓋到了,但最小章節 {n} 頁 > 上界 {cap} 頁")
            bad += 1
            continue
        print(f"✓ {doc} {cls:<8} p.{need + 1} 落在 {n} 頁的章節內")
    return bad


def full():
    """全語料:附註 record 涵蓋率 + EXPAND_TRUTH。"""
    import facts

    cells = facts.load()
    ok = miss = 0
    for key, recs in cells.items():
        doc, cls = key.split("|")
        note = [r for r in recs if "附註" in (r.get("source_kind") or "")]
        if not note:
            continue
        us = _units(doc, cls)
        for r in note:
            p = r["source_page"]
            if any(a <= p <= b for a, b in us):
                ok += 1
            else:
                miss += 1
                print(f"  ✗ {key} p.{p + 1} 不在任何章節內 "
                      f"{[(a + 1, b + 1) for a, b in us]}")
    print(f"附註 record 涵蓋 {ok}/{ok + miss}(基準 144/144)")

    hit = 0
    for doc, cls, need in locate.EXPAND_TRUTH:
        us = _units(doc, cls)
        covered = any(a <= need <= b for a, b in us)
        hit += covered
        if not covered:
            print(f"  ✗ {doc} {cls} 需 p.{need + 1} 不在章節內")
    print(f"EXPAND_TRUTH 涵蓋 {hit}/{len(locate.EXPAND_TRUTH)}(基準 11/11)")
    return (miss > 0) + (hit != len(locate.EXPAND_TRUTH))


def main():
    bad = quick()
    if "--full" in sys.argv:
        print()
        bad += full()
    print("\n" + ("全部通過" if not bad else f"✗ {bad} 項不符"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
