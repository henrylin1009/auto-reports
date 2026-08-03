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

    if printed_subtotal is not None:
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
