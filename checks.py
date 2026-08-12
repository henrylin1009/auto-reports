# -*- coding: utf-8 -*-
"""恆等式的**唯一實作**。

在這支之前,「列相加 == 文件印出的合計」這同一個命題被寫了四遍:

    transcribe.check_identity   facts record 形狀,缺欄 → 判死
    v4/witness.check_rowsum     v4 raw 形狀,缺值 → 跳過
    v4/adapter.aggregate        分桶後的 Σ桶+Σ側欄
    wide.View.ok                分桶後的 Σ桶+Σ側欄

四份程式、四種失敗訊息,而且**同一對之內對「缺值」的處置相反**。
後果不是嚴謹,是各驗各的、誰先跑誰決定這格死活 —— 實測
`202004_玉山_個體|Trading` 成本:`aggregate()` 因 6 列 null 判不合格,
`wide.View.ok` 判合格,同一份資料兩個答案(`v4/witness.check_rowsum` 的
docstring 也記著同一種事故)。

## 兩個命題,不是一個

**P1 `sum_matches()`** —— 純算術,不涉分桶。給「(名字, 值)」的序列。
**P2 `bucket_sum_matches()`** —— 分桶之後的版本,額外要求沒有列落在桶外。

P2 成立 ⇒ P1 成立(因為 P2 要求分桶完全),但兩者**失敗的意義不同**:
P1 失敗是抄錯了,P2 失敗可能只是分類表還沒收錄這個名字。所以不合併成一條。

## 缺值一律跳過,由恆等式當裁判

**這是刻意的裁定,不是寬鬆。** 文件印出的合計就是見證人 —— 缺的那幾列若
真的該有數字,等式不會剛好對上。

證據:
· 兆豐明細表 5 種衍生沒揭露取得成本,只有「選擇權」有。7 列相加
  44,631,513 == 印出的欄合計(`transcribe.check_col_totals` 的註記)。
· 玉山 `202004_5847` 成本 6 列未揭露,其餘 686,786,752 + 衍生 481,932
  == 687,268,684 == 文件印的成本合計。
· `wide.view()` 的既有語意本來就是「缺欄 = 未揭露,不是 0」。

實測換成這個語意對既有資料 **0 影響**:`facts/` 203 份 record,
「缺欄判死」與「缺欄跳過」兩種語意的結論 203/203 相同。
"""


def total_of(named_values):
    """Σ(有值的)。**「哪些算一列」的唯一定義** —— 值是 None 的跳過。

    `v4/witness.check_rowsum` 需要的是差額不是通過與否,所以它借這一支而不是
    `sum_matches()`;兩邊共用同一個加總語意,才不會出現「各驗各的」。
    """
    return sum(v for _n, v in named_values if v is not None)


def sum_matches(named_values, printed, col_label="合計"):
    """P1:Σ(有值的) == `printed`。回 None = 通過,回字串 = 失敗原因。

    `named_values` 是 `(名字, 值或 None)` 的序列。值是 None 代表**該列沒有
    揭露這一欄**,跳過 —— 見檔頭「缺值一律跳過」。

    `printed` 是 None 代表**文件沒印合計**,那不是通過也不是失敗,是
    **驗不到** —— 回一個明講的訊息。「沒東西可檢查」被當成「檢查過了」是
    這個專案踩過的坑(`adapter.aggregate` 的 `printed_subtotal is None` 那段)。
    """
    if printed is None:
        return f"文件沒印「{col_label}」,這道驗不到"
    named_values = list(named_values)
    if all(v is None for _n, v in named_values):
        return f"沒有任何一列有「{col_label}」的值"
    s = total_of(named_values)
    if s != printed:
        return (f"列相加 {s:,} != 印出的{col_label} {printed:,}"
                f"(差 {printed - s:,})")
    return None


def bucket_sum_matches(bucketed, unbucketed, printed, col_label="合計"):
    """P2:Σ(分到桶的) == `printed`,且 `unbucketed` 必須是空的。

    `bucketed` 是所有已歸桶金額的序列(含側欄:衍生、評價調整 —— 它們不進
    七桶但**算進恆等式**,否則等式永遠對不上)。
    `unbucketed` 是 `(名字, 值, 原因)` 的序列。

    **有列落在桶外一律不合格**,即使等式湊得起來 —— 那筆錢會悄悄從發布數字
    裡消失,而總額仍然是對的(`adapter.aggregate` 檔頭記的富邦 202404 案例:
    政府公債+公司債被併進「其他」,三個桶同時錯而六道檢查全綠)。
    """
    if unbucketed:
        names = [n for n, _v, _w in unbucketed]
        return f"{len(unbucketed)} 列對不到桶,錢不能悄悄消失:{names}"
    return sum_matches([(None, v) for v in bucketed], printed, col_label)
