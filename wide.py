# -*- coding: utf-8 -*-
"""S8 視圖層:rows(事實)+ buckets(判斷)→ wide(網站的 7 桶)。

三層分離(plan_v3_2_flow.md §2.2)的最後一層。**本層不做任何判斷** ——
桶怎麼歸問 `buckets`,口徑怎麼判問 `buckets.basis_of`,這裡只負責:
挑出能代表該口徑的來源、加總、把加不進 7 桶的東西**留在明面上**。

兩個口徑各自獨立取源(memory/oracle-basis-mismatch):
    wide       帳面 = 公允(Trading/OCI)/ 攤銷後成本(AC)
    wide_cost  取得成本

⚠️ **取不到就是 null,不准拿另一個口徑頂替、不准補 0。**
兆豐半年報的逐桶帳面在文件裡**真的不存在**(只有逐桶成本 + 一整筆評價調整),
拿成本填進 wide 會讓兆豐被系統性低估,而總額檢查照樣全綠 —— 總額是對的,
錯的是每一桶。這正是舊管線那個 bug 的形狀。

⚠️ **不用 `__UNKNOWN__` sentinel。** 認不出來的列就顯示它自己的名字與金額
(`View.unknown`),讓它在畫面上顯眼。丟進「其他」會讓錯誤看起來像正常值。
"""
from config import (BUCKET_MAP, WIDE_BUCKETS, DERIVATIVE, VALUATION_ADJ,
                    BOOK_COLS, COST_COLS)
import buckets
import checks
import transcribe

#: 恆等式是**三段**的:`sum(wide 7 桶) + 衍生 + 評價調整 == 類別合計`。
#: 衍生與評價調整刻意不進 7 桶 —— 塞進「其他」之後就再也拆不開,而兩者
#: 會計意義相反(衍生是真實持有的資產,評價調整是成本→公允的橋)。
SIDE = (DERIVATIVE, VALUATION_ADJ)


class View:
    """一格 × 一個口徑的視圖。`book is None` 代表**該口徑在文件裡不存在**。"""

    def __init__(self, cls, basis, book=None, reason=None, rec=None, col=None,
                 side=None, others=(), unknown=()):
        self.cls, self.basis, self.book, self.reason = cls, basis, book, reason
        self.rec, self.col = rec, col
        self.side = side or {k: 0 for k in SIDE}
        self.others, self.unknown = list(others), list(unknown)

    @property
    def total(self):
        return None if self.book is None else sum(self.book.values())

    @property
    def expected(self):
        """這個欄該對到哪個合計。**不是永遠 `printed_total`** —— 取成本欄時要對
        的是那一欄自己的合計(兆豐明細表:成本欄 44,631,513、公允欄 58,831,126)。"""
        return (self.rec.get("printed_totals") or {}).get(
            self.col, self.rec["printed_total"])

    @property
    def unbucketed_total(self):
        """未歸桶的金額合計。**永遠是個數字(可能是 0),不會是 None** ——
        它要能無條件顯示在網站上,而 `None` 在畫面上會塌成「沒有這個東西」,
        跟「這格未歸桶是 0」是兩件事(v9 §二原則 3)。"""
        return sum(v for _n, v, _w in self.unknown if v is not None)

    @property
    def arithmetic_ok(self):
        """**抄寫對不對** —— 未歸桶算進等式。這是 v9 的發布判準。

        跟 `ok` 的差別只有一項:這一支不要求 unknown 是空的。少一個字典詞條
        時它仍然是 True,於是七桶照樣發布、未歸桶站自己那一行。
        """
        if self.book is None:
            return False
        return checks.arithmetic_matches(
            list(self.book.values()) + list(self.side.values()),
            self.unknown, self.expected) is None

    @property
    def ok(self):
        """三段恆等式成立,而且沒有列落在 7 桶之外。

        ⚠️ **這是嚴格版,v9 之後不再是發布閘門** —— 發布看 `arithmetic_ok`,
        這一支留給「要求七桶全齊」的呼叫端(`core/publish_gate.py` 的
        `fully_confirmed` 那半邊)。兩者的差別就是 `unknown` 空不空。

        **判準走 `checks.bucket_sum_matches()`,與 `v4.adapter.aggregate()`
        同一份實作**(2026-08-10,P2 收斂)。在此之前兩邊各寫一份,對「金額是
        null」的處置相反 —— 實測 `202004_玉山_個體|Trading` 成本同一份資料
        兩個相反答案。
        """
        if self.book is None:
            return False
        return checks.bucket_sum_matches(
            list(self.book.values()) + list(self.side.values()),
            self.unknown, self.expected) is None

    @property
    def bond_mv(self):
        """債券市值:**只扣衍生,不扣評價調整。**

        評價調整不是持有的部位,是逐項成本橋到公允的差額,扣掉等於把口徑扣掉。
        舊版兩者一起扣,中信算出 215,117,416 > 類別合計 209,334,435 —— 子集大於全集。
        """
        if self.book is None:
            return None
        return self.total - self.side[DERIVATIVE] - self.book["股票"]


def pick(recs, basis):
    """挑能代表該口徑的 record。回傳 (rec, 欄名) 或 (None, 說不出口的理由)。

    帳面有兩條路:明細表把公允獨立成欄(直接指名),或附註逐項本身就是公允
    (欄名是日期,口徑靠「有沒有評價調整列」推)。

    成本有兩條路,而且**都必須驗得到合計**:附註逐項本身就是成本(合計 == 錨),
    或明細表的取得成本欄**有抄下欄合計**(`printed_totals`,第 6 道驗過)。
    沒抄欄合計的明細表成本欄一律不採用 —— 驗不到的數字不准送上網。

    ⚠️ **含跨桶合併列的 record 先排除**(`transcribe.coarse`)。富邦 202404 附註
    的「其他」吃掉了政府公債與公司債,拿它分桶會三個桶同時錯而總額照樣對 ——
    這一步排除的正是「六道檢查全綠但每一桶都錯」那種形狀。
    """
    bad = transcribe.coarse(recs, buckets)
    recs = [r for r in recs if r["source_page"] not in bad]
    if not recs:
        # **不准退回去用它。** 全部來源都把跨桶科目併成一列 = 這格的逐桶在文件裡
        # 不存在,跟兆豐半年報的帳面同一種情形,正確輸出是 null 不是勉強湊一個。
        return None, f"唯一來源含跨桶合併列(p{sorted(bad)}),逐桶分不出來"
    if basis == "帳面":
        for r in recs:
            for c in BOOK_COLS:
                if all(c in row["cols"] for row in r["rows"]):
                    return r, c
        for r in recs:
            # **`total_col` 是成本欄的 record 不准當帳面用。** `basis_of()` 只看
            # 「有沒有評價調整列」,而成本明細表本來就沒有那一列 → 它回「公允」,
            # 於是「取得成本」那一欄會被當成帳面發布。
            #
            # 既有 v3 資料踩不到(實測 0 格):v3 的明細表 record 同時抄了
            # 「公允價值總額」欄,上面 BOOK_COLS 那圈就先接走了。會踩到的是
            # v4 那種「附註(帳面)+明細表(成本)分成兩份 record」的形狀 ——
            # 附註是成本口徑時第一圈跳過它,第二圈就撿到成本明細表。
            # 實測 202504_兆豐_個體|OCI 等 10 格,成本七桶被當帳面。
            if r["total_col"] in COST_COLS:
                continue
            if buckets.basis_of(r) == "公允":
                return r, r["total_col"]
        return None, "所有來源逐項皆為成本口徑,逐桶帳面在文件裡不存在"
    for r in recs:
        if buckets.basis_of(r) == "成本":
            return r, r["total_col"]
    for r in recs:
        for c in COST_COLS:
            if c in (r.get("printed_totals") or {}):
                return r, c
    return None, "沒有來源逐項是成本口徑,明細表也沒抄下取得成本欄的合計(驗不到)"


def view(recs, basis="帳面"):
    """一格 → View。"""
    cls = recs[0]["class"]
    rec, col = pick(recs, basis)
    if rec is None:
        return View(cls, basis, reason=col)
    book = {wb: 0 for wb in WIDE_BUCKETS}
    side = {k: 0 for k in SIDE}
    others, unknown = [], []
    for row in rec["rows"]:
        if col not in row["cols"]:
            continue        # 缺欄 = 未揭露,不是 0(兆豐明細表 5 種衍生無取得成本)
        v = row["cols"][col]
        b = buckets.bucket(row)
        if b in side:
            side[b] += v
            continue
        wb = BUCKET_MAP.get(b)
        if wb is None:
            # 三種都留原名:桶沒有 wide 對應 / 待人審 / 根本不認得。
            why = f"桶「{b}」無 wide 對應" if b else \
                  "待人審" if buckets.pending(row) else "分桶表不認得"
            unknown.append((row["name"], v, why))
            continue
        book[wb] += v
        if wb == "其他":
            # R6:「其他」在畫面上是一格,但成分要留著讓人展開 ——
            # 否則「其他」變大時沒人知道是真的其他變多,還是又混進了認不出來的東西。
            others.append((row["name"], v))
    return View(cls, basis, book, rec=rec, col=col, side=side,
                others=others, unknown=unknown)


def cell(recs):
    """一格 → {"帳面": View, "成本": View}。"""
    return {b: view(recs, b) for b in ("帳面", "成本")}


def report(key, recs):
    vs = cell(recs)
    print(f"\n{'=' * 68}\n{key}")
    for r in recs:
        print(f"  p{r['source_page']}({r['source_kind']}) 逐項口徑 = {buckets.basis_of(r)}")
    for basis, v in vs.items():
        if v.book is None:
            print(f"  ✗ {basis}:全 null —— {v.reason}")
            continue
        print(f"  {basis}  取值來源 p{v.rec['source_page']} 欄「{v.col}」")
        for wb in WIDE_BUCKETS:
            print(f"     {v.cls}_{wb:<6} = {v.book[wb]:>15,}")
        for k in SIDE:
            print(f"     {'(不進 wide)':<12} {k} = {v.side[k]:>15,}")
        tot = v.total + sum(v.side.values())
        print(f"  {'✓' if v.ok else '✗'} {v.total:,} + 衍生 {v.side[DERIVATIVE]:,}"
              f" + 評價調整 {v.side[VALUATION_ADJ]:,} = {tot:,}"
              f"  vs 印出合計 {v.expected:,}  差 {v.expected - tot:,}")
        print(f"    債券MV(只扣衍生與股票)= {v.bond_mv:,}")
        for n, amt in v.others:
            print(f"    ·「其他」成分 {n}  {amt:,}")
        for n, amt, why in v.unknown:
            print(f"  ⚠ 進不了 wide:{n}  {amt:,}  ({why})")
    return vs


if __name__ == "__main__":
    import json
    import sys
    import facts
    path = sys.argv[1] if len(sys.argv) > 1 else None
    data = json.load(open(path, encoding="utf-8")) if path else facts.load()
    bad = [k for k, recs in data.items()
           if not any(v.ok for v in report(k, data[k]).values())]
    print(f"\n{len(data)} 格,{len(data) - len(bad)} 格至少一個口徑可用")
    for k in bad:
        print("  ✗", k)
