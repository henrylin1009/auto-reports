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

⚠️ **「兩個口徑」也是平行根,見 `build()` 的口徑分組。**「找得出一組 record 的
   印出合計」不代表它們屬於同一棵樹——公允口徑跟成本口徑的合計本來就不會互相
   對應,硬湊只會產生假警報(v10 洞①,實測:華南 202504 OCI 等 5 格)。
"""
from config import COST_COLS


def merge_anchor(recs, fallback):
    """一格要拿去驗④的錨(仟元)。回 `(值, 不一致與否)`。

    **資料自帶的優先,`fallback` 是退路。** 抽取器整份讀過 PDF、當場看到 BS
    那一行;`fallback`(通常是 `locate.locate()` 或它寫進 `anchors/*.json` 的
    快取)只看它猜到的那幾頁,實測 **31/91 份文件一個錨都讀不到**。

    ⚠️ **兩個來源都有而且不一致時,值回 None 讓④誠實說查無可查,
    但第二個回傳值標成 True。** 「查無可查」與「兩邊打架」都會讓值變 None,
    意義不同,呼叫端要能分得出來。

    這支是 `results.build()`(讀 PDF)與 `core/reconcile.py`(讀 `anchors/`
    快取,零 PDF)共用的邏輯 —— **兩邊都要叫同一支,不准各自抄一份**,
    否則 E2 等價閘門(`test_e2_equiv.py`)會憑空冒出差異。
    """
    carried = {r["bs_anchor"] for r in recs
               if isinstance(r.get("bs_anchor"), int)
               and not isinstance(r.get("bs_anchor"), bool)}
    if len(carried) > 1:
        return None, True
    if not carried:
        return fallback, False
    got = carried.pop()
    if fallback is not None and fallback != got:
        return None, True
    return got, False


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

    ⚠️ **先按口徑分組,一個口徑一棵樹**(v10 洞①)。舊寫法找「印出合計等於誰的
    哪一列」時把全部 record 混在一起找,於是成本口徑的合計(逐項是成本,錨是
    公允)在公允口徑的表裡永遠找不到對應列,被誤判成「掛不上去」——但那不是
    子節點,是另一個口徑的平行根,本來就不該跟公允口徑的表比對。判準借既有的
    `total_col in COST_COLS`(合計欄本身就印著「取得成本」),不在這裡另寫一套
    口徑判斷(見 memory two-implementations-one-rule)。

    ⚠️ **這裡不能用 `buckets.basis_of()`。** 它的判準「有評價調整列 → 成本」是
    為 AC(逐項要橋回公允價值)設計的;OCI/Trading 的公允口徑主表**也可能自己
    印一列「評價調整」**(兆豐/中信實測:那是損益的一部分,不是成本橋公允的
    橋接列),用 `basis_of()` 會把真正的公允根也判成成本,跟同樣被 `total_col`
    判成成本的明細表**混進同一組**,重現原本的 bug。`total_col` 是這裡唯一
    可靠的訊號——那是文件自己印的欄名,不是猜的。

    **只讓跨口徑那條路過,同口徑內對不上的仍然要報錯**——
    `case_失敗_跨口徑存在時同口徑對不上仍要報錯` 驗這件事。
    """
    if not recs:
        return None, "沒有 record"
    if anchor is None:
        return None, "這個類別沒有錨,無法檢查閉合"

    def rec_basis(r):
        return "成本" if r.get("total_col") in COST_COLS else "公允"

    groups = {}
    for r in recs:
        groups.setdefault(rec_basis(r), []).append(r)

    primary_basis = next((b for b, g in groups.items()
                          if any(r.get("printed_total") == anchor for r in g)), None)
    if primary_basis is None:
        got = sorted({r.get("printed_total") for r in recs})
        return None, (f"沒有任何一份 record 的印出合計 == 錨 {anchor:,}"
                      f"(抄回來的合計:{[f'{v:,}' for v in got if v is not None]})")

    roots, parent, expanded = [], {}, set()
    for basis, group in groups.items():
        if basis == primary_basis:
            g_roots = [r for r in group if r.get("printed_total") == anchor]
        else:
            # 這個口徑跟錨的口徑不同,沒有錨可比——根 = 沒被同口徑裡任何一份
            # 表的某一列展開的那些,不跟主口徑的錨比較,也不會被主口徑的列
            # 誤認成子節點。
            claimed = {_col_value(p, x) for p in group for x in p["rows"]}
            g_roots = [r for r in group if r.get("printed_total") not in claimed]
            if not g_roots:
                names = ", ".join(f"p{r.get('source_page', -1) + 1}" for r in group)
                return None, (f"「{basis}」口徑({names})裡沒有一份 record 撐得起根,"
                              f"互相對不上")
        roots.extend(g_roots)

        for rec in group:
            if rec in g_roots:
                continue
            pt = rec.get("printed_total")
            tag = f"p{rec.get('source_page', -1) + 1}"
            if pt is None:
                # **沒有印出合計的 record 掛不上樹,而且理由跟「掛錯地方」不同。**
                # 文件本來就可能不印某一欄的合計(明細表的取得成本欄常常沒有),
                # 那不是抄錯。舊寫法走到下面的訊息格式化會直接 TypeError 崩掉 ——
                # 之前碰不到是因為錨讀不到、整格更早就被擋下;錨跟著資料走之後
                # 這條路才真的會走到。
                return None, (f"{tag}:這份沒有印出合計,掛不上樹"
                              f"(文件沒印該欄合計時是正常的,但這格就驗不到閉合)")
            # ⚠️ 候選只在**同口徑**裡找(`p in group`,不是 `p in recs`)——
            # 這正是洞①的修法本身:跨口徑的列本來就不該掛上去。
            cand = [(p, x["name"]) for p in group if p is not rec
                    for x in p["rows"] if _col_value(p, x) == pt]
            names = sorted({c[1] for c in cand})
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
