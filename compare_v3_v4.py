# -*- coding: utf-8 -*-
"""P2 遷移驗證:v3 的 `facts/` vs v4 的 `v4/ledger` 逐格逐桶對照。

    python3 compare_v3_v4.py            印摘要 + 不一致清單
    python3 compare_v3_v4.py --md       另外寫出 docs/v3_v4_對照.md

**這是「全面轉 v4」這個決定的安全帶**(docs/plan_v5_統一.md P2)。
砍 v3 之前唯一誠實的證據就是這張表:`facts/` 是 156 格通過六道檢查的真值,
拿它當 v4 的第三道 witness。

判定規則(照 P2 原文):
    七桶完全相同      → v4 該格可信
    有任何一桶不同    → **兩邊都進待辦**,人翻原始頁裁決
    v3 有 / v4 沒有   → 進待辦,查是漏讀還是 v3 抄錯

⚠️ **口徑要分開比。** v3 與 v4 都各自產 wide(帳面)與 wide_cost(成本)兩份,
混在一起比會憑空冒出一堆「不一致」——實測 v4 曾把成本口徑的七桶寫進 wide,
那個 bug 就是靠分口徑比才看得清楚(見 build.rebuild_v4 的口徑註解)。

⚠️ **不比保留集。** `holdout.split()` 切出來的格永不進發布路徑,也不該拿來
當調表的依據 —— 它存在的意義就是「沒被看過」。
"""
import argparse
import collections
import datetime
import json
import os

import facts as facts_mod
import holdout
from config import WIDE_BUCKETS

BASES = ("wide", "wide_cost")


def _v3_verdict():
    """v3 逐格七桶。走與 `build.rebuild_v3()` 完全同一條路,不另寫一套。"""
    import results
    cells = facts_mod.load()
    train, _leak = holdout.split(cells)
    verdict, _audit = results.build(train)
    return verdict


def _v4_verdict():
    import build
    return build.rebuild_v4()


def _anchor_diffs():
    """{(doc, cls): check_anchor 的 diff} —— 只收 MISMATCH 的。

    為什麼要交叉比對:實測第一版報告「不一致率 5.6%」看起來像「v4 整體不如 v3」,
    但兩筆不一致的七桶總差**剛好都等於該格 check_anchor 的 diff**
    (63,649 與 48,937),也就是 100% 的分歧都是 anchor 早就舉手的格子。
    光報一個百分比會把這件事藏起來,所以在報告裡直接標出來。
    """
    from v4 import ledger
    out = {}
    for e in ledger.load_all():
        for cls, c in e["cells"].items():
            w = (c.get("witnesses") or {}).get("check_anchor") or {}
            if w.get("status") == "MISMATCH" and w.get("diff") is not None:
                out[(e["doc"], cls)] = w["diff"]
    return out


def compare():
    """→ (rows, stats)。`rows` 每筆是一個「格 × 口徑」的比對結果。"""
    v3, v4 = _v3_verdict(), _v4_verdict()
    keys = sorted(set(v3) | set(v4))
    rows = []
    for key in keys:
        a, b = v3.get(key), v4.get(key)
        for basis in BASES:
            ba = (a or {}).get(basis) if (a or {}).get("pass") else None
            bb = (b or {}).get(basis) if (b or {}).get("pass") else None
            if ba is None and bb is None:
                continue                      # 兩邊都沒有,沒什麼好比的
            if ba is None or bb is None:
                rows.append({"key": key, "basis": basis,
                             "verdict": "只有 v3" if bb is None else "只有 v4",
                             "diffs": {}})
                continue
            diffs = {wb: (ba.get(wb), bb.get(wb))
                     for wb in WIDE_BUCKETS if ba.get(wb) != bb.get(wb)}
            rows.append({"key": key, "basis": basis,
                         "verdict": "相同" if not diffs else "不一致",
                         "diffs": diffs})

    # 每筆不一致都去問一次 check_anchor:七桶總差 == anchor diff 的話,
    # 這筆分歧不是「兩套管線各說各話」,是 anchor 已經指出來的同一件事。
    anchors = _anchor_diffs()
    for r in rows:
        r["anchor_diff"] = None
        r["anchor_explains"] = False
        if r["verdict"] != "不一致":
            continue
        doc, cls = r["key"].split("|")
        ad = anchors.get((doc, cls))
        r["anchor_diff"] = ad
        total = sum((y - x) for x, y in r["diffs"].values()
                    if isinstance(x, int) and isinstance(y, int))
        r["anchor_explains"] = ad is not None and ad == total

    stats = collections.Counter(r["verdict"] for r in rows)
    return rows, stats


def report(rows, stats):
    both = stats["相同"] + stats["不一致"]
    rate = stats["不一致"] / both * 100 if both else 0.0
    print(f"可比對(兩邊都有數字)的「格×口徑」: {both}")
    print(f"  相同    {stats['相同']}")
    print(f"  不一致  {stats['不一致']}   ← 不一致率 {rate:.1f}%")
    print(f"只有 v3   {stats['只有 v3']}   (v4 漏讀?還是 v3 抄錯?)")
    print(f"只有 v4   {stats['只有 v4']}   (v4 補上了 v3 沒抄到的格)")
    print()
    # **門檻寫死在這裡並印出來**:P2 原文「不一致率 > 5% 就停下來重新評估
    # 全面轉 v4 這個決定」。印出判語是為了讓這個決定有據可查,不是靠人記得。
    if both == 0:
        print("⚠ 沒有任何格子可比 —— 這份報告是空的,不能拿來當砍 v3 的依據。")
    elif rate > 5:
        print(f"⚠ 不一致率 {rate:.1f}% > 5% —— 依 P2 規則**停下來**,不要推進「全面轉 v4」。")
    else:
        print(f"✔ 不一致率 {rate:.1f}% ≤ 5% —— 符合 P2 的推進門檻。")

    bad = [r for r in rows if r["verdict"] == "不一致"]
    if bad:
        expl = [r for r in bad if r["anchor_explains"]]
        print(f"\n不一致明細({len(bad)} 筆):")
        for r in bad:
            tag = ("  ★ 七桶總差 == check_anchor diff,v3 對得上錨、v4 對不上"
                   if r["anchor_explains"] else "")
            print(f"  {r['key']} · {r['basis']}{tag}")
            for wb, (x, y) in r["diffs"].items():
                d = (y - x) if isinstance(x, int) and isinstance(y, int) else None
                print(f"      {wb:8} v3 {x!s:>16}  v4 {y!s:>16}"
                      + (f"   差 {d:,}" if d is not None else ""))
        if expl:
            print(f"\n★ {len(expl)}/{len(bad)} 筆不一致由 check_anchor 完全解釋 ——"
                  " 這些不是「兩套管線各說各話」,是 v4 對不上資產負債表錨而 v3 對得上。")
            if len(expl) == len(bad):
                print("  **全部**不一致都是這一類:這個百分比實際上在量 check_anchor 的覆蓋,"
                      "不是在量 v4 的整體品質。")


def to_md(rows, stats):
    both = stats["相同"] + stats["不一致"]
    rate = stats["不一致"] / both * 100 if both else 0.0
    out = [f"# v3 / v4 對照(P2 遷移驗證)",
           "",
           f"產生時間 {datetime.datetime.now().isoformat(timespec='seconds')}",
           "",
           "由 `python3 compare_v3_v4.py --md` 產生,**不要手改**。",
           "",
           "| | 數量 |",
           "|---|---|",
           f"| 可比對(兩邊都有) | {both} |",
           f"| 七桶完全相同 | {stats['相同']} |",
           f"| 有桶不一致 | {stats['不一致']} |",
           f"| 只有 v3 | {stats['只有 v3']} |",
           f"| 只有 v4 | {stats['只有 v4']} |",
           "",
           f"**不一致率 {rate:.1f}%** —— P2 門檻是 5%,"
           + ("超過,依規則停下來重新評估。" if rate > 5 else "符合推進門檻。"),
           ""]
    bad = [r for r in rows if r["verdict"] == "不一致"]
    if bad:
        expl = [r for r in bad if r["anchor_explains"]]
        if expl:
            out += ["## ⚠ 先看這個:不一致率不等於 v4 的品質", ""]
            out.append(f"{len(expl)}/{len(bad)} 筆不一致的**七桶總差,剛好等於該格 "
                       "`check_anchor` 的 diff** —— 也就是 v4 對不上資產負債表錨、"
                       "而 v3 對得上。這些不是「兩套管線各說各話」,是同一件已經被 "
                       "witness 舉手的事。")
            out.append("")
            if len(expl) == len(bad):
                out.append("**全部**不一致都屬於這一類,所以上面那個百分比實際上在量 "
                           "`check_anchor` 抓到什麼,不是在量 v4 的整體正確性。"
                           "要降低它,該做的是把 anchor 對不上的格修好(或擋住),"
                           "不是重新評估 v4。")
                out.append("")
        out += ["## 不一致明細", "",
                "| 格 | 口徑 | 桶 | v3 | v4 | 差 | anchor 解釋? |",
                "|---|---|---|---|---|---|---|"]
        for r in bad:
            mark = f"★ diff {r['anchor_diff']:,}" if r["anchor_explains"] else "—"
            for wb, (x, y) in r["diffs"].items():
                d = f"{y - x:,}" if isinstance(x, int) and isinstance(y, int) else "—"
                out.append(f"| {r['key']} | {r['basis']} | {wb} | {x} | {y} | {d} | {mark} |")
        out.append("")
    only3 = [r for r in rows if r["verdict"] == "只有 v3"]
    if only3:
        out += ["## 只有 v3 有(查:v4 漏讀,還是 v3 抄錯?)", ""]
        out += [f"- `{r['key']}` · {r['basis']}" for r in only3]
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="寫出 docs/v3_v4_對照.md")
    args = ap.parse_args()
    rows, stats = compare()
    report(rows, stats)
    if args.md:
        os.makedirs("docs", exist_ok=True)
        path = "docs/v3_v4_對照.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_md(rows, stats))
        print(f"\n已寫出 {path}")


if __name__ == "__main__":
    main()
