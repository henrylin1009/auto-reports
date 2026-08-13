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


def arithmetic_matches(bucketed, unbucketed, printed, col_label="合計"):
    """**抄寫對不對**:Σ(已歸桶) + Σ(未歸桶) == `printed`。回 None = 通過。

    ⚠️ 未歸桶的列**算進等式**。這一支問的是「這張表有沒有抄漏、抄錯」,
    而「央行票據 7,345,878 屬於哪個桶」跟「它有沒有被抄對」是兩件事 ——
    後者由這一支管,前者由 `unbucketed_reason()` 管(v9,見
    `docs/plan_v9_不擋人.md` §三)。

    在此之前兩者綁在同一支 `bucket_sum_matches()` 裡,所以少一個字典詞條
    會讓「抄寫」這道也一起判死,整格資料被丟掉 —— 實測 2026-08-12
    富邦 202402 OCI:8 列全對、逐列相加 == 錨,只因 `央行票據` 不在
    `buckets.SYN` 而整格不歸檔,重抄還必然撞同一道(失敗點在模型下游)。
    """
    named = [(None, v) for v in bucketed] + [(n, v) for n, v, _w in unbucketed]
    return sum_matches(named, printed, col_label)


def unbucketed_reason(unbucketed):
    """**歸桶齊不齊**:有列落在桶外就回一句話,否則回 None。

    這是 `arithmetic_matches()` 的另一半。**它不再是歸檔的閘門**(v9),
    只是一個標記:錢沒有消失,它站在網站上「未歸桶」那一行。

    原本的理由是「那筆錢會悄悄從發布數字裡消失,而總額仍然是對的」
    (`adapter.aggregate` 檔頭的富邦 202404 案例:政府公債+公司債被併進
    「其他」,三個桶同時錯而六道檢查全綠)。那個危害**現在由畫面擋**:
    未歸桶永遠自己站一行、即使是 0 也顯示,所以它不再是「悄悄」的。
    ⚠️ 那一行要是被藏起來,這道就必須變回閘門 —— 兩者只能存在一個。
    """
    if unbucketed:
        names = [n for n, _v, _w in unbucketed]
        return f"{len(unbucketed)} 列對不到桶:{names}"
    return None


def bucket_sum_matches(bucketed, unbucketed, printed, col_label="合計"):
    """P2(**嚴格版**):抄寫對 **且** 每一列都歸得到桶。

    保留原語意給還需要「全齊才算數」的呼叫端(發布資格)。**實作由上面兩支
    組出來,不另寫一份判斷** —— 同一道規則兩個實作是這個 repo 反覆長 bug
    的形狀(memory/two-implementations-one-rule)。
    """
    return (unbucketed_reason(unbucketed)
            or arithmetic_matches(bucketed, unbucketed, printed, col_label))
