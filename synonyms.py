# -*- coding: utf-8 -*-
"""S6 同義詞產生器:從 rows **自動長出**「原名 → 桶」,不是手寫。

判準是定義,不是猜測(plan_v3_2_flow.md §3):

    同一份文件、同一格、同一個口徑欄,金額相同、名字不同 → **定義上就是同一個東西**

所以若其中一邊的名字已經在 `buckets.SYN` 裡,另一邊的桶就**推得出來**,
不需要人去判斷「金融債券」是不是「金融債」。人只審推不出來的那些。

⚠️ **這只在年報成立。** 配對需要一份文件裡有兩份表述(附註 + 明細表),
半年報只有附註一份 → 表從年報長,套到半年報。半年報冒出年報沒有的名目,
只能進人審佇列,**不准在這裡猜**。

⚠️ **為什麼要有這支程式:** 手工往 `SYN` 塞名字是打版 —— 抄一格塞幾個,
塞到後面那張表是靠感覺拼出來的,而**塞錯了沒有任何檢查抓得到**
(金額照樣加得對、兩表照樣對得上,錯的只有那一桶)。見 memory/checks-must-fail。

跑法:
    python3 synonyms.py scratchpad/rows_v3.json          # 候選 + 未涵蓋清單
    python3 synonyms.py scratchpad/rows_v3.json --check  # 有衝突就 exit 1(回歸用)
"""
import buckets
import transcribe

#: 候選的四種下場。`衝突` 是**失敗**,其餘三種是資訊。
COVERED, PROPOSE, HUMAN, CONFLICT = "已涵蓋", "可自動推定", "待人審", "衝突"


def _unique(rec, col, skip):
    """{金額: 原名},**只留該欄裡出現剛好一次的金額**。

    重複金額不能用來配對:兩邊各有兩列同額時,誰對誰是猜的,而猜錯會直接寫進
    分桶表。寧可少長幾條,也不要長出一條沒人驗得到的錯的。
    """
    seen = {}
    for name, v in ((r["name"], r["cols"].get(col)) for r in rec["rows"]
                    if not skip(r)):
        if v:
            seen.setdefault(v, []).append(name)
    return {v: n[0] for v, n in seen.items() if len(n) == 1}


def candidates(recs):
    """一格 → [(金額, 名字A, 名字B)]。單一來源頁回空(這道機制不適用)。

    欄位對齊沿用第 3 道的 `align()`:附註逐項成本、明細表逐項公允時,
    要挑明細表的「取得成本」欄才比得動(兆豐 2024 Trading 實測)。
    **口徑沒對齊就不准配對** —— 成本 21,684,995 與公允 22,284,807 是同一個科目,
    但金額不同;反過來,不同科目的成本與公允偶然相等就會配出假同義詞。
    """
    if len(recs) < 2:
        return []
    cols = transcribe.align(recs, buckets.basis_of, buckets.is_adj)
    if cols is None:
        return []
    # 評價調整沒有對造(它就是兩個口徑的差),拿它配對只會配出垃圾。
    skip = buckets.is_adj
    ref, *rest = recs
    base = _unique(ref, cols[id(ref)], skip)
    out = []
    for rec in rest:
        cur = _unique(rec, cols[id(rec)], skip)
        for v in sorted(set(base) & set(cur)):
            a, b = base[v], cur[v]
            if buckets.norm(a) != buckets.norm(b):
                out.append((v, a, b))
    return out


def classify(a, b):
    """一組候選 → (下場, 說明)。**兩邊都認得但桶不同 = 衝突,是失敗不是資訊。**"""
    ba, bb = buckets.bucket({"name": a}), buckets.bucket({"name": b})
    if ba and bb:
        return (COVERED, ba) if ba == bb else (
            CONFLICT, f"{a}→{ba} vs {b}→{bb}")
    if ba or bb:
        new = b if ba else a
        if buckets.pending({"name": new}):
            # 人審佇列裡的名字**不准被自動推定吃掉**:它進佇列是因為字面分不出來,
            # 而「同金額」只證明兩邊指同一筆錢,不證明我們把桶挑對了。
            return HUMAN, f"{new} 在人審佇列,金額配對不能代替那個決定"
        return PROPOSE, f'"{new}": "{ba or bb}",'
    return HUMAN, f"{a} / {b} 兩邊都不認得"


def uncovered(cells):
    """未涵蓋的名字,**按金額由大到小**(§9 使用者指示:不用門檻,按金額給人看)。"""
    amt = {}
    for recs in cells.values():
        for rec in recs:
            for r in rec["rows"]:
                if buckets.bucket(r) is None:
                    key = (r["name"], "待人審" if buckets.pending(r) else "未收錄")
                    amt[key] = amt.get(key, 0) + abs(r["cols"].get(rec["total_col"], 0))
    return sorted(amt.items(), key=lambda kv: -kv[1])


def scan(cells):
    """全部格子 → {下場: [(金額, A, B, 說明, 格)]}。"""
    out = {}
    for key, recs in cells.items():
        for v, a, b in candidates(recs):
            kind, why = classify(a, b)
            out.setdefault(kind, []).append((v, a, b, why, key))
    return out


def main(path, check=False):
    import json
    cells = json.load(open(path, encoding="utf-8"))
    res = scan(cells)
    dual = sum(len(r) > 1 for r in cells.values())
    print(f"{len(cells)} 格,其中 {dual} 格有雙來源頁(只有這些長得出同義詞)")
    for kind in (CONFLICT, PROPOSE, COVERED, HUMAN):
        rows = res.get(kind, [])
        mark = "✗" if kind == CONFLICT else "→" if kind == PROPOSE else "·"
        print(f"\n{mark} {kind} {len(rows)} 組")
        for v, a, b, why, key in sorted(rows):
            print(f"    {v:>15,}  {a} = {b}   [{key}]\n        {why}")

    print("\n未涵蓋的名字(按金額;要嘛補進 SYN,要嘛它根本不是葉列)")
    for (name, state), v in uncovered(cells):
        print(f"    {v:>15,}  {name}  ({state})")
    if check and res.get(CONFLICT):
        print(f"\n{len(res[CONFLICT])} 組衝突 —— 分桶表或抄列有一邊是錯的")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__.rsplit("跑法:", 1)[-1])
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], "--check" in sys.argv))
