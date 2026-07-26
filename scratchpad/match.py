# -*- coding: utf-8 -*-
"""附註 ↔ 明細表 逐列配對測試。

三層,由強到弱,每層都必須**精確相等**:
  L1 1:1        一列對一列
  L2 區段對一列  明細表某個 group 整段加總 == 附註某一列(表上印的區段標題當邊界)
  L3 同桶子集   剩餘列在同一個桶內湊,**解必須唯一**,否則報衝突

不比名字。欄位也不預先指定 —— 對每個候選欄都試,精確相等才收;
若同一列在兩個欄都對得上,視為歧義,報衝突不採用。
"""
import itertools
import json
import sys

MAXK = 4  # L3 子集大小上限。放大只會製造巧合,不會提升真實命中


def _rows(rec, cols):
    out = []
    for r in rec["rows"]:
        for c in cols:
            if c in r["cols"] and r["cols"][c]:
                out.append({"name": r["name"], "group": r.get("group", ""),
                            "col": c, "v": r["cols"][c]})
    return out


def match(note, detail, note_cols, det_cols, bucket):
    A = _rows(note, note_cols)      # 附註側
    B = _rows(detail, det_cols)     # 明細表側
    log, usedA, usedB = [], set(), set()

    # L1:1:1 精確相等。同一金額在任一側出現多次 → 不唯一,跳過留給後面
    for i, a in enumerate(A):
        hits = [j for j, b in enumerate(B) if b["v"] == a["v"] and j not in usedB]
        same = [k for k, x in enumerate(A) if x["v"] == a["v"]]
        if len(hits) == 1 and len(same) == 1 and i not in usedA:
            j = hits[0]
            usedA.add(i); usedB.add(j)
            log.append(("L1", f"{a['name']} == {B[j]['name']}", a["v"]))

    # L2:明細表區段整段 == 附註某一列
    groups = {}
    for j, b in enumerate(B):
        if j not in usedB and b["group"]:
            groups.setdefault((b["group"], b["col"]), []).append(j)
    for (g, col), js in groups.items():
        s = sum(B[j]["v"] for j in js)
        hits = [i for i, a in enumerate(A) if i not in usedA and a["v"] == s]
        if len(hits) == 1:
            i = hits[0]
            usedA.add(i); usedB.update(js)
            log.append(("L2", f"{A[i]['name']} == 區段「{g}」{len(js)} 列相加", s))

    # L3:同桶子集,解必須唯一
    for j, b in enumerate(B):
        if j in usedB:
            continue
        pool = [i for i in range(len(A)) if i not in usedA
                and bucket.get(A[i]["name"]) == bucket.get(b["name"])]
        sols = []
        for k in range(2, min(MAXK, len(pool)) + 1):
            for combo in itertools.combinations(pool, k):
                if sum(A[i]["v"] for i in combo) == b["v"]:
                    sols.append(combo)
        if len(sols) == 1:
            usedB.add(j); usedA.update(sols[0])
            log.append(("L3", f"{b['name']} == " +
                        " + ".join(A[i]["name"] for i in sols[0]), b["v"]))
        elif len(sols) > 1:
            log.append(("衝突", f"{b['name']} 有 {len(sols)} 組解 → 不採用", b["v"]))

    left = ([f"附註 {A[i]['name']} {A[i]['v']:,}" for i in range(len(A)) if i not in usedA] +
            [f"明細 {B[j]['name']} {B[j]['v']:,}" for j in range(len(B)) if j not in usedB])
    return log, left, len(A), len(B)


if __name__ == "__main__":
    d = json.load(open("scratchpad/rows_match.json", encoding="utf-8"))
    note, detail = d["note"], d["detail"]
    bucket = d["bucket"]
    log, left, na, nb = match(note, detail, d["note_cols"], d["det_cols"], bucket)
    print(f"附註 {na} 列  明細表 {nb} 個數值\n")
    for lv, txt, v in log:
        print(f"  [{lv}] {txt}  = {v:,}")
    print(f"\n配對 {len([l for l in log if l[0].startswith('L')])} 組")
    if left:
        print(f"未配對 {len(left)}:")
        for x in left:
            print("   ", x)
    else:
        print("未配對 0 —— 全數對上")
