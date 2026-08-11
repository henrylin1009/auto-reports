# -*- coding: utf-8 -*-
"""v4 raw book/cost → 七桶。docs/plan_v5_統一.md P1-2。

**不走 `wide.pick()`。** `pick()` 是為 v3 那種「一堆來源頁,不知道哪份代表
哪個口徑」的情況設計的自動判別(`buckets.basis_of()` 靠有沒有「評價調整」列
猜成本/公允)。v4 的 `book`/`cost` 是模型自己在 JSON 頂層分開回報的,口徑
本來就不含糊——尤其 AC 類的 `book`(攤銷後成本的帳面金額)沒有評價調整列,
硬套 `basis_of()` 會被誤判成「成本」,跟真正的 `cost`(取得成本)撞在一起。
所以這裡直接做 `wide.view()` 核心那段「桶名查表 + 累加」的邏輯,`buckets.py`
的同義詞表原封不動共用,只是不繞經 `pick()` 那層自動判別。

閘門(P1-2 規格,兩條都要能被注入錯誤測出來,見 test_adapter.py):
    有列對不到桶  → 不合格(那筆錢不准悄悄從發布數字裡消失)
    Σ桶 ≠ 小計    → 不合格
"""
import datetime
import re

import buckets
from config import VALUATION_ADJ, WIDE_BUCKETS

SIDE = ("衍生", "評價調整")
#: 這幾個詞是加總列,不是投資標的。P1-1 已經把「別把合計列塞進 rows」寫進
#: prompt,這裡是保險絲——模型還是可能忘記,尤其是舊的 4 份 v4/raw(P1-1 之前
#: 產出的,prompt 沒這條規則)。
_SUBTOTAL_WORDS = {"合計", "小計", "淨額", "總計"}
_ROW_SEP = re.compile(r"[－\-]")


def split_row_name(raw_group, raw_name):
    """把『大類段落－具體標的』黏在一起的列名拆開。

    模型照 P1-1 的新 prompt 應該已經自己拆好(`group`/`name` 分開兩個欄位),
    這裡是保險絲,處理兩種情況:
    ①模型忘了拆,`group` 是空的但 `name` 裡還黏著分隔符;
    ②舊資料(P1-1 之前產出的 4 份 v4/raw),整段 schema 只有 `name`,沒有 `group`。

    ⚠️ **只在整條名字本身對不到桶時才拆**(呼叫端負責這個順序,見 `bucket_row`)——
    `buckets.SYN` 裡有些既有鍵本身就長得像「大類－標的」(例如「定期存單-可轉讓」,
    見 `buckets.py`:104,是既有鍵「可轉讓定期存單」的字序倒裝,整條照抄才對得上),
    先拆再查會把這種已經收錄的完整名字拆散,反而查不到。
    """
    name = (raw_name or "").strip()
    group = (raw_group or "").strip()
    if not group and re.search(_ROW_SEP, name):
        g, _, n = name.rpartition("－") if "－" in name else name.rpartition("-")
        if g and n:
            return g.strip(), n.strip()
    return group, name


def normalize_rows(raw_rows):
    """v4 raw 的 rows → `[{"name","group","amount"}]`,濾掉誤入的合計列。
    這裡**不拆**大類前綴——是否要拆由 `bucket_row()` 在查表當下決定
    (先整條查、查不到才拆,見 `split_row_name` 的說明)。
    回傳 (rows, dropped_subtotals)——後者純粹給人看,不影響判定。
    """
    rows, dropped = [], []
    for r in raw_rows or []:
        name = (r.get("name") or "").strip()
        if name in _SUBTOTAL_WORDS:
            dropped.append(r)
            continue
        rows.append({"name": name, "group": (r.get("group") or "").strip(),
                      "amount": r.get("amount")})
    return rows, dropped


def is_adjustment_row(row):
    """這一列是不是「評價調整/備抵損失」這種橋接列(而不是持有的標的)。

    **一定要走 `bucket_row()`,不可以直接呼叫 `buckets.is_adj()`。**
    模型有時會把段落黏進名字(`債務工具-評價調整`),`bucket_row()` 會先整條查、
    查不到再拆前綴,`buckets.is_adj()` 不會 —— 實測 `202504_5843_AI3|OCI`
    兩條路徑對同一列給出相反答案,害口徑判成「公允」、七桶(成本)被當帳面發布。
    這是「同一件事有兩套判斷」的老毛病,收斂成這一支。
    """
    return bucket_row(row) == VALUATION_ADJ


def bucket_row(row):
    """一列 → 桶名(或 None)。**先整條原名查,查不到再拆**——理由見
    `split_row_name`。拆完的 `name`/`group` 也讓 `buckets.bucket()` 走它
    原本的 GENERIC + GROUP_SYN 那條路(例如「其他」配段落「衍生金融資產」)。
    """
    b = buckets.bucket(row)
    if b:
        return b
    group, name = split_row_name(row.get("group"), row.get("name"))
    if (group, name) == (row.get("group") or "", row.get("name") or ""):
        return None          # 沒有分隔符可拆,原樣查過就是查不到
    return buckets.bucket({"name": name, "group": group})


class Aggregated:
    """一份 book 或 cost 攤開成七桶後的結果。`ok=False` 時 `book` 是 None——
    不合格的格不准硬湊一個部分正確的七桶出來(同一條鐵則見 wide.View)。

    `basis` 是**這七桶本身**的口徑,不是這份 record 叫什麼名字:
      "公允" —— 七桶就是帳面,可以直接發布成 wide
      "成本" —— 七桶是逐項成本,帳面要靠那一筆評價調整才補得到,而評價調整
                是**一整筆**、不分桶,所以「逐桶帳面」在文件裡根本不存在。
                這時 wide 必須是 null(見 `wide.py:99` 同一條規則),
                七桶要改走 wide_cost。
    """

    def __init__(self, ok, book=None, side=None, others=None, unknown=None, reason=None,
                 basis="公允"):
        self.ok, self.book, self.side = ok, book, side
        self.others = others or []
        self.unknown = unknown or []
        self.reason = reason
        self.basis = basis


def aggregate(raw_rows, printed_subtotal):
    """rows + 小計 → `Aggregated`。這是 `wide.view()` 核心那段迴圈的 v4 版本
    (桶名查表 + 累加),刻意不呼叫 `wide.pick()`——理由見檔頭。
    """
    rows, dropped = normalize_rows(raw_rows)
    if not rows:
        return Aggregated(False, reason="rows 為空(可能整份都被當成合計列濾掉了)")

    # **口徑由表自己的算術決定,不由這份 record 叫什麼名字決定**(同 `buckets.basis_of`
    # 的判準,memory/oracle-basis-mismatch)。有評價調整列 ⇒ 逐項是成本,那一列是補到
    # 公允的差額。這件事一定要在這裡算:呼叫端拿到七桶之後就分不出它是成本還是帳面了,
    # 而兩者在網站上是兩個不同欄位(wide / wide_cost),放錯就是發布錯的數字
    # ——實測 20 格踩過(兆豐 Trading 差 11.82%),見 docs/plan_v5_統一.md。
    basis = "成本" if any(is_adjustment_row(r) for r in rows) else "公允"

    book = {wb: 0 for wb in WIDE_BUCKETS}
    side = {k: 0 for k in SIDE}
    others, unknown = [], []
    for row in rows:
        v = row["amount"]
        if v is None:
            unknown.append((row["name"], None, "金額是 null"))
            continue
        b = bucket_row(row)
        if b in side:
            side[b] += v
            continue
        wb = _to_wide(b)
        if wb is None:
            why = f"桶「{b}」無 wide 對應" if b else \
                  "待人審" if buckets.pending(row) else "分桶表不認得"
            unknown.append((row["name"], v, why))
            continue
        book[wb] += v
        if wb == "其他":
            others.append((row["name"], v))

    if unknown:
        return Aggregated(False, book=book, side=side, others=others, unknown=unknown,
                           reason=f"{len(unknown)} 列對不到桶,錢不能悄悄消失", basis=basis)

    # **沒有可對帳的小計 ⇒ 不合格。**(2026-08-10 加)原本這裡是
    # `if printed_subtotal is not None:` —— 沒有小計就整段跳過、直接回 ok,
    # 等於「沒東西可以檢查」被當成「檢查過了」。
    #
    # 這條擋得到的實例:玉山 202104 OCI 的取得成本欄,reader 正確判定債務工具
    # 那 5 項填的是**攤銷後成本不是取得成本**,依規則填 null 只抄了 2 列股票,
    # 並註明表上的合計 312,625,010 混了兩種口徑、不能當比對基準(見該份
    # `cost_note`)。少了 5 個債券桶的 rows 照樣加得出七桶 —— 只是那 5 桶全是 0。
    # 於是網站上玉山 2021H2 OCI 的成本是「公債 0 / 公司債 0 / 金融債 0」,
    # 而同一格帳面是 2,947 億。**沒有任何其他檢查抓得到**,因為能抓的那一個
    # (跟小計對)正好就是不存在的那個。
    #
    # 實測影響:v4 目前 87 筆 book 全都有小計,不受影響;cost 少 4 筆
    # (富邦 202004/202104 Trading、玉山 202104 OCI、國泰 202304 Trading)。
    if printed_subtotal is None:
        return Aggregated(False, book=book, side=side, others=others, basis=basis,
                           reason="沒有可對帳的小計 —— 少抄幾列照樣加得出七桶,"
                                  "缺的桶會靜靜變成 0")

    total = sum(book.values()) + sum(side.values())
    diff = total - printed_subtotal
    if diff != 0:
        return Aggregated(False, book=book, side=side, others=others,
                           reason=f"Σ桶+Σ衍生評價 {total:,} ≠ 小計 {printed_subtotal:,}(差 {diff:,})",
                           basis=basis)

    return Aggregated(True, book=book, side=side, others=others, basis=basis)


def _to_wide(bucket_name):
    import wide
    return wide.BUCKET_MAP.get(bucket_name)


# ── v4 raw → facts/ records ────────────────────────────────────────────────
#
# A-1(docs/plan_工具化.md 階段 A):**這是兩條管線會合的那個接縫。**
# 在此之前 `v4/reader.py` 的產出停在 `v4/raw/`,進不了 `facts/` —— 於是同一件事
# 有兩個事實庫、兩個 ratify、兩套人審介面,每條規則都要做兩次。實例:用 claude
# 重抽 `202502_5836` 之後,gemini 那份壞資料還留在 `facts/`,待辦也清不掉。
#
# ⚠️ **本檔頭那段「不走 wide.pick()」的顧慮已被推翻,不是被忽略。**
#     原文說「AC 的 book 沒有評價調整列,硬套 basis_of() 會被誤判成成本」。
#     實測(202502_5836 AC):book 的 rows 含「減:備抵損失 -543,513」,
#     逐項是**未扣備抵的毛額**、合計才是淨額,備抵一整筆沒分攤到桶 ——
#     所以「AC 逐桶帳面」在文件裡**真的不存在**,`basis_of()` 判成本是對的。
#     (memory/oracle-basis-mismatch、2026-08-10 完成度普查同結論。)
#     `aggregate()` 那條路徑照舊不受影響,本段只新增一個輸出形狀。

_COST_COL = "取得成本"          # 必須是 config.COST_COLS 的成員


def _split_for_facts(raw_row):
    """把 `bucket_row()` 那個「整條查不到才拆前綴」的決定**固化進 record**。

    ⚠️ **這是 A-1 最容易踩的坑,本檔 `is_adjustment_row()` 的警告講的就是它。**
    `bucket_row()` 會拆前綴,但下游的 `buckets.basis_of()` 走的是
    `buckets.is_adj()` —— **不拆**。所以若把模型原始的黏合名字
    (`債務工具-評價調整`)直接寫進 `facts/`,`basis_of()` 認不出那是評價調整列,
    口徑就從「成本」翻成「公允」,整格成本七桶會被當帳面發布。

    實測(未修前):`202104_5843` `202304_5841` `202504_5843` 的 Trading/OCI
    帳面因此憑空出現數字,而 v4 那條路徑判定它們是成本。
    `202504_5843_AI3|OCI` 正是本檔警告裡點名的那一格。

    所以寫進 `facts/` 的名字必須**已經是 `bucket_row()` 看到的那個樣子**,
    下游任何只查 `buckets.bucket()`/`is_adj()` 的地方才會得到一致答案。
    """
    row = {"name": (raw_row.get("name") or "").strip(),
           "group": (raw_row.get("group") or "").strip() or None}
    if buckets.bucket(row) is not None:
        return row                       # 整條查得到,不動它
    g, n = split_row_name(raw_row.get("group"), raw_row.get("name"))
    if (g, n) != (row["group"] or "", row["name"]) and \
            buckets.bucket({"name": n, "group": g}) is not None:
        return {"name": n, "group": g or None}
    return row                           # 拆了也查不到 ⇒ 保留原樣進人審


def _date_col(bs_date):
    """`114/06/30` → `114年6月30日`。認不得就原樣回傳(當成一個欄名用)。"""
    m = re.fullmatch(r"\s*(\d{2,3})[/-](\d{1,2})[/-](\d{1,2})\s*", bs_date or "")
    return f"{int(m[1])}年{int(m[2])}月{int(m[3])}日" if m else (bs_date or "合計")


def to_facts_records(doc, cls, parsed_cls, bs_date, model=None, at=None):
    """v4 的一格(`parsed[cls]`)→ `facts/` 的 records(0~2 份)。

    **book 與 cost 各成一份 record**,因為 `facts[key]` 本來就是 list,而
    `wide.pick()` 就是設計成從多份來源裡挑出符合該口徑的那一份。

    兩個欄名不是隨便取的,它們是 `wide.pick()` 的兩個鉤子:

    · **book 用日期欄名,絕不可以叫「帳面金額」。** 叫帳面金額會命中
      `pick()` 的 `BOOK_COLS` 分支、**繞過 `basis_of()`**,於是 AC 那種
      「逐項毛額 + 一整筆備抵」的表會產出一個不存在的逐桶帳面。用日期欄名
      才會走 `basis_of()`,由「有沒有評價調整列」決定 —— 那是對的判準。

    · **cost 的 `printed_totals` 必須含 `取得成本` 這個鍵。** 那是 `pick()`
      成本口徑第二分支唯一的鉤子(第一分支要 `basis_of()==成本`,而明細表
      的成本欄通常沒有評價調整列,走不到)。

    回傳的 record **不含 `basis` 欄** —— 該欄位在 `buckets.basis_of()` 已停用
    (agent 自由敘述沒法機械驗證)。口徑一律由表自己算。
    """
    stamp = {"via": "v4/reader", "model": model or "claude",
             "at": at or datetime.datetime.now().isoformat(timespec="minutes")}

    def _rec(sub, col, kind, side, total):
        """一份 record,湊不齊就回 None。

        **金額是 None ⇒ 不要那個欄鍵,不要填 0。** `facts.validate()` 要求
        `cols[col]` 是 int,而 `wide.view()` 的語意本來就是「缺欄 = 未揭露,
        不是 0」(兆豐明細表 5 種衍生無取得成本)。填 0 會把「沒揭露」講成
        「這桶是零」,那是兩件事。

        **`printed_totals` 沒有整數合計就整個省略。** 它是 `wide.pick()` 認
        成本口徑的鉤子;沒有印出來的合計就驗不到,不給鉤子讓它落空是**對的** ——
        `pick()` 的理由字串「明細表也沒抄下取得成本欄的合計(驗不到)」講的就是
        這件事。硬塞一個自己加總出來的數字等於偽造文件上沒有的東西。
        """
        rows = []
        for r in sub.get("rows") or []:
            # **合計/小計列要濾掉,用 `normalize_rows()` 那份同一個名單。**
            # 模型還是會把它們當一般列塞進 rows(實測 202302_5843_AI3|Trading
            # 有「小計 49,737,828」「合計 55,717,136」兩列)。`aggregate()` 早就
            # 濾了,這裡漏抄 → 它們進了 facts/、分不到桶、落進 `View.unknown`,
            # 於是同一份資料兩個閘門給出相反答案(agg.ok=True / view.ok=False)。
            if (r.get("name") or "").strip() in _SUBTOTAL_WORDS:
                continue
            v = r.get("amount")
            cols = {} if isinstance(v, bool) or not isinstance(v, int) else {col: v}
            nm = _split_for_facts(r)
            rows.append({"name": nm["name"], "group": nm["group"], "cols": cols})
        if not any(col in r["cols"] for r in rows):
            return None          # 沒有任何一列有值 → total_col 掛不上,不成立
        rec = {"doc": doc, "class": cls,
               "source_kind": kind, "source_page": sub.get("page"),
               "total_col": col, "printed_total": total, "rows": rows,
               "_by": dict(stamp, basis_side=side)}
        if not isinstance(total, bool) and isinstance(total, int):
            rec["printed_totals"] = {col: total}
        return rec

    out = []
    book = (parsed_cls or {}).get("book") or {}
    if book.get("rows"):
        r = _rec(book, _date_col(bs_date), "附註", "book",
                 book.get("printed_subtotal"))
        if r:
            out.append(r)

    cost = (parsed_cls or {}).get("cost") or {}
    if cost.get("rows"):
        r = _rec(cost, _COST_COL, "明細表", "cost", cost.get("total"))
        if r:
            out.append(r)
    return out
