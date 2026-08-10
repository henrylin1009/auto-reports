# -*- coding: utf-8 -*-
"""擴頁觸發訊號的白名單。**不在名單上的一律不觸發,也不消耗重試預算。**

**分類狀態不得驅動 PDF expand。** `UNCLASSIFIED` 或 `rules.propose()` 提不出候選,
**不能**推論成「頁沒找全」或「可能是小計」—— 它同樣可能只是個新的真實科目。
只有**來源 / 表內算術 / 跨表 reconciliation** 失敗才有資格觸發 expand。
分類未知一律走「facts 歸檔 + review queue」,最多在工單顯示提示,
**不得消耗重試預算。**

實證(見 docs/plan_clean_core.md M3,不要重新推導):`rules.propose()` 回 None 的
名字裡,玉山「透過其他綜合損益按公允價值衡量之權益/債務工具投資」是**小計**,
兆豐「不動產投資信託受益證券」與玉山「國外機構發行債券」是**真科目**(後來人工
裁示為資產基礎 / 公債)。同一個訊號指向相反處置 → 用它路由等於擲硬幣。

第 3 道(`check_cross`)也在 NEVER 裡:它**混合訊號,今天切不開**
(`transcribe.check_cross(recs, bk=None)` 一跑就 AttributeError,見
`transcribe.py:337/293` —— 潛伏 bug,禁改清單內,本單不修)。保守裁定為
不觸發,代價已量 = 0:`locate.EXPAND_TRUTH` 11 格沒有一格靠它觸發。

⚠️ 2026-07-31:`check_anchor`(逐 record 驗合計 == 錨)換成 `check_closure`
(整格拼樹,根 == 錨,見 `core/closure.py`)。上面提到的玉山兩層附註小計
(「透過其他綜合損益按公允價值衡量之權益/債務工具投資」)現在**根本不會
流到分桶那一關**——建樹時就被識別成子節的父列而排除,不再需要靠
`_taxonomy_gap`/expand 去猜它是不是小計。這段歷史仍留著,是因為同一個
「訊號指向相反處置」的教訓對別的新科目名一樣成立。
"""

# 判準是「哪一道檢查失敗」,**不是比對錯誤訊息字串**。
# (fill._taxonomy_gap 已經踩過訊息比對的坑:同一個根因會在第 3 道長出第二個症狀。)
TRIGGERS = {
    "source",           # source_page 不在候選頁集合內
    "check_identity",   # ①② sum(葉列 total_col) != printed_total
    "check_closure",    # ④  整格拼不成一棵樹(根 != 錨,或子表掛不上任何一列)
    "check_col_totals", # ⑥  逐欄合計對不上
}
NEVER = {
    "check_buckets",    # ⑤ 純分類
    "check_cross",      # ③ 混合訊號,今天切不開(見上)
}


def may_expand(failed_checks):
    """→ (要不要擴頁, 理由)。理由要能直接印在工單上給人看。

    理由只點名 TRIGGERS 裡失敗的那些道;NEVER 裡的失敗(即使同時發生)
    一律不進理由字串 —— 這樣「① + ⑤ 同時失敗」印出來的理由只提 ①,不提 ⑤,
    避免有人誤以為分類也是觸發原因之一。
    """
    failed_checks = set(failed_checks)
    triggered = sorted(failed_checks & TRIGGERS)
    if not triggered:
        return False, f"沒有白名單內的失敗訊號(失敗={sorted(failed_checks)}),不擴頁"
    return True, f"擴頁:{triggered} 失敗"


def consumes_budget(failed_checks):
    """分類造成的失敗**不消耗重試預算**。

    判準與 may_expand 相同:只有白名單內的失敗才消耗預算。純分類失敗
    (⑤,或③ 這種混合但今天保守裁定不觸發的)不得推進 retries 計數。
    """
    return bool(set(failed_checks) & TRIGGERS)
