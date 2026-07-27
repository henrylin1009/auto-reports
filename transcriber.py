# -*- coding: utf-8 -*-
"""抄列器:候選頁純文字 → rows。**唯一的非確定性元件。**

實作走同一個介面,所以「誰去讀表」是部署決定,不是架構決定:
    replay(cells)  重播已抄好的事實庫,給回歸測試用
    submitted(p)   讀 Claude Code 剛寫好的 rows JSON(T3 的 `fill.py submit` 用)

⚠️ 驗收由 `transcribe.verify()` 做,抄列器本身**不做任何檢查、不做任何判斷**。
   抄不出來就回 None,不准猜、不准補 0、不准分桶。

⚠️ **這裡不准出現任何模型 API 呼叫**(使用者指示)。抄列由外部 agent 完成。
"""


def replay(cells):
    def _t(doc, cls, prompt):
        return cells.get(f"{doc}|{cls}")
    return _t
