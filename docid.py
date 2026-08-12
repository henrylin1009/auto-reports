# -*- coding: utf-8 -*-
"""doc id 的**唯一**解析 / 組裝入口。

    新格式:`{YYYYMM}_{銀行名}_{個體|合併}`      例:`202504_玉山_個體`
    舊格式:`{YYYYMM}_{代碼}_AI{n}`              例:`202504_5847_AI3`

換掉代碼與 AI 編號的理由:**兩者都已經不帶意義**。`resolve.download()` 一律
把抓到的檔存成 `_AI3`(resolve.py:37),AI 編號各家各年不一,早就只是固定
後綴;而代碼要再查一次 `config.BANKS` 才知道是哪一家。檔名直接寫銀行名與
口徑,人翻 `pdf_cache/` 就看得懂。

⚠️ **檔名裡的「個體/合併」是給人看的標籤,不是判準。**

口徑的唯一權威是封面(`locate.basis_of`)。這條規則有事故背書:舊版拿檔名裡
的 AI 編號當判準(`kind != "AI3"` 就跳過),後果是**整張合併網格永遠是空的**,
而「永遠空的」跟「還沒抄」在畫面上長得一模一樣,沒有任何檢查抓得到
(見 `core/report.cell_of` 的註解)。

把口徑寫進檔名之後,這個風險回來了:下游可能圖方便去讀檔名而不讀封面。
`verify_basis()` 就是為此存在 —— 兩者不一致時**大聲報錯**,不靜靜選一個。
不一致通常代表抓錯檔或上傳時填錯,那是要人看的事,不是程式該替人決定的事。
(鐵律 9:「兩種原因,一種結果」就是 bug。)
"""
import re

import config

#: 口徑標籤。與 `locate.SOLO` / `locate.CONSOLIDATED` 的字面值相同 —— 刻意的,
#: 這樣 `verify_basis()` 可以直接比對,不需要再維護一張對照表(那就是第二個實作)。
SOLO, CONSOLIDATED = "個體", "合併"
BASES = (SOLO, CONSOLIDATED)

#: `{YYYYMM}_{銀行名}_{口徑}`。銀行名用非底線字元,期別固定 6 位數字。
_RE = re.compile(r"^(\d{6})_([^_]+)_(%s)$" % "|".join(BASES))

#: 舊格式,只有 `migrate_docid.py` 與相容層會用到。
_RE_OLD = re.compile(r"^(\d{6})_(\d{4})_AI(\d)$")


class BadDocId(ValueError):
    """doc id 不符合命名慣例。獨立型別,讓呼叫端能跟其他 ValueError 分開處理。"""


def parse(doc):
    """`202504_玉山_個體` → `("202504", "玉山", "個體")`。不合格式丟 `BadDocId`。

    **不接受舊格式** —— 靜靜接受兩種格式等於讓兩套慣例並存,那是這個 repo
    反覆出過事的形狀(鐵律 7:不准長第二條路徑)。舊格式的轉換只在
    `migrate_docid.py` 裡發生一次。
    """
    m = _RE.match(doc or "")
    if not m:
        raise BadDocId(
            f"doc id {doc!r} 不符合命名慣例 {{YYYYMM}}_{{銀行名}}_{{個體|合併}}"
            f"(例:202504_玉山_個體)")
    return m.group(1), m.group(2), m.group(3)


def is_valid(doc):
    """純檢查,不丟例外 —— 給要過濾一批名字的呼叫端用。"""
    return bool(_RE.match(doc or ""))


def make(period, bank, basis):
    """`("202504", "玉山", "個體")` → `202504_玉山_個體`。組裝前先驗,不生出爛名字。"""
    if not re.fullmatch(r"\d{6}", str(period)):
        raise BadDocId(f"期別 {period!r} 要是 6 位數字(YYYYMM)")
    if not bank or "_" in str(bank):
        raise BadDocId(f"銀行名 {bank!r} 不得為空、不得含底線")
    if basis not in BASES:
        raise BadDocId(f"口徑 {basis!r} 要是 {SOLO} 或 {CONSOLIDATED}")
    return f"{period}_{bank}_{basis}"


def period_of(doc):
    """`202504_玉山_個體` → `"202504"`。"""
    return parse(doc)[0]


def bank_of(doc):
    """`202504_玉山_個體` → `"玉山"`(**名字,不是代碼**)。"""
    return parse(doc)[1]


def basis_label_of(doc):
    """檔名上標的口徑。**這是標籤不是判準** —— 要判準請用 `locate.basis_of(封面)`。

    函式名刻意帶 `label`,讓呼叫端在讀程式碼時就看得出自己拿到的是哪一種東西。
    """
    return parse(doc)[2]


def code_of(doc):
    """`202504_玉山_個體` → `"5847"`;認不得的銀行名回 None。

    `resolve.py` 要拿代碼去 TWSE 抓檔,是目前唯一需要反查的地方。
    """
    bank = bank_of(doc)
    for code, name in config.BANKS.items():
        if name == bank:
            return code
    return None


def verify_basis(doc, cover_basis):
    """檔名標的口徑 vs 封面判出來的口徑。一致回 `None`,不一致回**訊息字串**。

    刻意回字串而不是丟例外:呼叫端有兩種情境 —— 上傳時要擋下來(當成錯誤),
    盤點時要列出來(當成報告)。回值讓兩種都寫得出來,而丟例外只服務前者。

    `cover_basis` 是 `locate.UNKNOWN`(封面判不出來)時**不算不一致** ——
    那是「不知道」,不是「打架」,兩者塌成同一個結果正是鐵律 9 要防的事。
    """
    label = basis_label_of(doc)
    if not cover_basis or cover_basis not in BASES:
        return None
    if label != cover_basis:
        return (f"{doc}:檔名標「{label}」但封面是「{cover_basis}」—— "
                f"可能抓錯檔或改名時填錯。封面是權威,檔名要改成 {cover_basis}。")
    return None
