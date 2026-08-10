# -*- coding: utf-8 -*-
"""章節閉合 —— 一格的多份 record 怎麼拼成一棵樹,以及哪些列才是葉列。

取代舊的「每一份 record 的葉列相加都必須 == 錨」。舊規矩把**文件本來就分兩層印**
的東西判死:玉山 202502 OCI 附註「九、」是主表(p24,兩列)+ 子附註(一)(二)
(p24/p25),三張表沒有任何一張自己等於錨 316,073,868 → 三張全被拒收。
實測(2026-07-31,章節模式重跑目前抄不過的 9 格):8 格的跨 record 欄聯集
剛好 == 錨 —— 抄回來的內容是對的,錯的是驗收單位。

樹的形狀由**金額**認,不由版型認,也不問模型:

    根   printed_total == 錨 的 record(既有 202 份 record 全部是這種,
         所以這條規則對既有事實庫零改判 —— 上線前實測 155 格全過)
    子節 printed_total 等於「某份 record 的某一列在其合計欄的金額」的 record,
         那一列就是它的父列。**必須唯一命中**,0 個或 2 個以上都判失敗
    葉列 沒有被任何子節展開的列 —— 只有葉列進分桶、進 wide、上網站

⚠️ **沒有子集和。** 「找得出一組 record 的合計加起來等於錨」這種判準是恆真閘門的
   溫床:隨便幾個數字都湊得出一個總和,而湊出來的組合跟文件的真實結構無關。
   子節一定要指名它是從哪一列展開的,對不上就停下來讓人判(實測注入:兩份湊得出
   錨但誰也掛不上誰 → 正確拒收)。

⚠️ 這裡**不判斷誰是附註誰是明細表**。年報的附註與明細表是兩個**平行的根**
   (兩份都印著錨),它們不相加、也不互為父子 —— 交叉比對是 `transcribe.check_cross`
   的事。實測注入:附註 + 明細表兩個根同時存在 → 正確通過,不會被誤加成兩倍。
"""


def _col_value(rec, row):
    return (row.get("cols") or {}).get(rec.get("total_col"))


class Tree:
    """一格的樹。`parent[id(rec)] = (父rec, 父列名)`;根不在 parent 裡。"""

    def __init__(self, recs, roots, parent, expanded):
        self.recs = recs
        self.roots = roots
        self.parent = parent
        self.expanded = expanded          # {(id(父rec), 父列名)}

    def is_leaf(self, rec, row):
        return (id(rec), row["name"]) not in self.expanded

    def leaves(self):
        """→ [(rec, row)] 葉列。母表那幾列「已被子節展開」的在這裡消失。"""
        return [(r, x) for r in self.recs for x in r["rows"] if self.is_leaf(r, x)]

    def subtree(self, root):
        """一個根底下的所有 record(含自己)。平行根不會互相牽連。"""
        out, changed = [root], True
        while changed:
            changed = False
            for r in self.recs:
                if r in out:
                    continue
                p = self.parent.get(id(r))
                if p and p[0] in out:
                    out.append(r)
                    changed = True
        return out


def build(recs, anchor):
    """→ (tree, err)。err 是 None 才表示閉合;訊息面向人看,不給程式 parse。

    這裡**不驗**「列相加 == 自己的印出合計」—— 那是 `transcribe.check_identity`
    (①②)的職責,一份 record 一則訊息,不要在兩個地方各報一次同一件事。
    """
    if not recs:
        return None, "沒有 record"
    if anchor is None:
        return None, "這個類別沒有錨,無法檢查閉合"

    roots = [r for r in recs if r.get("printed_total") == anchor]
    if not roots:
        got = sorted({r.get("printed_total") for r in recs})
        return None, (f"沒有任何一份 record 的印出合計 == 錨 {anchor:,}"
                      f"(抄回來的合計:{[f'{v:,}' for v in got if v is not None]})")

    parent, expanded = {}, set()
    for rec in recs:
        if rec in roots:
            continue
        pt = rec.get("printed_total")
        cand = [(p, x["name"]) for p in recs if p is not rec
                for x in p["rows"] if _col_value(p, x) == pt]
        names = sorted({c[1] for c in cand})
        tag = f"p{rec.get('source_page', -1) + 1}"
        if not cand:
            return None, (f"{tag}:印出合計 {pt:,} 在別的表裡找不到對應的那一列,"
                          f"掛不上去(這份是誰的子節?)")
        if len(names) > 1:
            return None, (f"{tag}:{pt:,} 同時對到多列 {names},無法唯一掛載"
                          f"(該掛哪一列請人判,系統不猜)")
        parent[id(rec)] = cand[0]
        expanded.add((id(cand[0][0]), cand[0][1]))
    return Tree(recs, roots, parent, expanded), None


def flatten(recs, anchor):
    """每個根 → 一份「攤平的 record」,rows 是那棵子樹的葉列。

    給下游用(`wide` / `webdata` / `check_cross`):它們的心智模型是「一份 record
    就是一整張表」,樹對它們沒有意義,也不該讓它們每個都自己走一次樹。
    攤平之後,**單根單份 record 的舊格子攤出來就是它自己**(既有 155 格實測),
    所以下游不需要為了這個改判準。

    回傳 (flat_recs, err)。子節的合計欄名跟根不一樣時直接報錯 —— 那代表兩層
    的欄根本對不起來(例如子附註只印取得成本),攤平會產生一份缺欄的假 record,
    寧可停下來。
    """
    tree, err = build(recs, anchor)
    if err:
        return None, err
    out = []
    for root in tree.roots:
        col = root["total_col"]
        rows = []
        for rec in tree.subtree(root):
            for row in rec["rows"]:
                if not tree.is_leaf(rec, row):
                    continue
                if col not in (row.get("cols") or {}):
                    return None, (f"p{rec['source_page'] + 1} 的「{row['name']}」沒有"
                                  f"根(p{root['source_page'] + 1})的合計欄「{col}」,"
                                  f"兩層的欄對不起來,不攤平")
                rows.append(row)
        flat = dict(root)
        flat["rows"] = rows
        out.append(flat)
    return out, None
