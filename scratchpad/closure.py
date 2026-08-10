# -*- coding: utf-8 -*-
"""章節閉合檢查原型 —— 取代現行「每份 record 的葉列相加都必須 == 錨」。

樹的形狀由**金額**認,不由版型認:
  根   = printed_total == 錨 的 record(舊行為;既有 202 份全是這種)
  子節 = printed_total 等於「某個 record 的某一列在合計欄的金額」的 record
  葉列 = 沒有被任何子節展開的列 —— 只有葉列進分桶、進 wide

閉合條件(三個都要):
  1. 每份 record 自己:葉列相加 == 自己的 printed_total(即現行 ①②,不放寬)
  2. 每份非根 record 都掛得上某一列(唯一)。掛不上 → 失敗,不猜
  3. 至少有一個根;根的 printed_total == 錨

**沒有子集和。**「湊得出一組加起來等於錨」是恆真閘門的溫床(隨便幾個數字都湊得到),
所以子節一定要指名它是哪一列展開來的。
"""

def _col_value(rec, row):
    return row["cols"].get(rec.get("total_col"))

def build(recs, anchor):
    """→ (ok, 理由, 樹)。樹 = {id(rec): [(父rec, 父列名)]}"""
    if not recs:
        return False, "沒有 record", None
    # 1. 每份自己的算術
    for r in recs:
        col = r.get("total_col")
        if col is None:
            return False, f"p{r['source_page']+1}:沒有合計欄", None
        miss = [x["name"] for x in r["rows"] if col not in x["cols"]]
        if miss:
            return False, f"p{r['source_page']+1}:有列缺合計欄「{col}」:{miss}", None
        s = sum(x["cols"][col] for x in r["rows"])
        if s != r["printed_total"]:
            return False, (f"p{r['source_page']+1}:列相加 {s:,} != 自己印出的合計 "
                           f"{r['printed_total']:,}(差 {r['printed_total']-s:,})"), None
    roots = [r for r in recs if r["printed_total"] == anchor]
    if not roots:
        return False, f"沒有任何一份 record 的印出合計 == 錨 {anchor:,}", None
    # 2. 非根掛列
    parent = {}
    expanded = set()          # (id(父rec), 父列名) 已被展開
    for r in recs:
        if r in roots:
            continue
        cand = [(p, x["name"]) for p in recs if p is not r
                for x in p["rows"] if _col_value(p, x) == r["printed_total"]]
        if not cand:
            return False, (f"p{r['source_page']+1}:印出合計 {r['printed_total']:,} "
                           f"在別的表裡找不到對應的那一列,掛不上去"), None
        if len({c[1] for c in cand}) > 1:
            return False, (f"p{r['source_page']+1}:{r['printed_total']:,} 同時對到多列 "
                           f"{sorted({c[1] for c in cand})},無法唯一掛載"), None
        parent[id(r)] = cand[0]
        expanded.add((id(cand[0][0]), cand[0][1]))
    return True, None, {"roots": roots, "parent": parent, "expanded": expanded}

def leaves(recs, tree):
    """只有沒被展開的列才是葉列。母表那兩列「權益工具投資/債務工具投資」在這裡消失。"""
    out = []
    for r in recs:
        for x in r["rows"]:
            if (id(r), x["name"]) not in tree["expanded"]:
                out.append((r, x))
    return out
