# -*- coding: utf-8 -*-
"""把 `config.BUCKET_RULES` 那段散文編成查得動的表 —— **只產生提案,不自動生效**。

實測發現(10 格之後):`synonyms.py` 能長出來的同義詞比預期稀有 —— 附註與明細表
多半用**完全相同**的名字(玉山、富邦、中信皆是),10 格只長出 2 組。實際擴表的
主力反而是「照 `BUCKET_RULES` 已經寫死的歸屬抄一條進 SYN」,而那件事我一直在手做。
手做的問題不是慢,是**看不出我抄的時候有沒有夾帶自己的判斷**。

所以把規則本身變成資料:

    rules.propose("金融債券")  →  ("金融債", "金融債券")     # 規則裡有,照抄
    rules.propose("國外機構發行債券") → (None, ...)          # 規則裡沒有 → 人審

⚠️ **提案不等於生效。** `buckets.bucket()` 仍然只認 `SYN` 的精確比對,
關鍵字比對**不准**當成分桶的授權來源。理由:關鍵字是**子字串**比對,
它一定會有誤命中,而誤命中在下游沒有任何檢查抓得到(見 memory/checks-must-fail)。
提案要經過 git diff 這道人審才進 SYN —— 那就是本專案的審核介面。

⚠️ **這張表的權威來源是 `config.BUCKET_RULES`,不是這裡。**
規則改了要同步,`test_rules.py` 會檢查每個關鍵字都真的出現在那段散文裡。
"""
import re

from config import DERIVATIVE, VALUATION_ADJ

#: 桶 → 關鍵字。**逐字抄自 `config.BUCKET_RULES`,不得自行擴充。**
#: 想加規則裡沒有的詞(例如「政府債券」),那是新判斷 → 改規則,不要偷改這裡。
KEYS = {
    "公債": ("政府公債", "公債"),
    "貨幣市場": ("國庫券", "商業本票", "承兌匯票", "短期票券"),
    "可轉讓定存單": ("可轉讓定期存單", "可轉讓定存單", "央行定期存單",
                     "銀行定存單", "銀行定期存單"),
    "公司債": ("可轉換公司債", "公司債"),
    "金融債": ("次順位金融債", "金融債券", "金融債"),
    "資產基礎": ("證券化商品", "資產基礎", "擔保證券", "不動產抵押貸款證券", "REITs"),
    "股票": ("上市櫃", "興櫃", "未上市", "股票", "受益憑證", "基金",
             "特別股", "存託憑證"),
    "其他": ("其他",),
    DERIVATIVE: ("利率交換", "遠期外匯", "選擇權", "換匯換利", "期貨",
                 "信用違約交換", "資產交換", "衍生"),
    VALUATION_ADJ: ("金融資產評價調整", "評價調整", "備抵損失", "累計減損",
                    "未攤銷溢折價", "應計利息"),
}

#: **只准出現在名字開頭**的關鍵字。
#: 「其他」若當一般子字串比,會命中「透過**其他**綜合損益按公允價值衡量之債務工具投資」
#: —— 那是兩層附註的**小計列**,正是第 5 道要靠「對不到桶」擋下來的東西。
#: 把它誤判成「其他」桶,等於親手拆掉那道檢查。`BUCKET_RULES` 自己也是這樣寫的:
#: 「其他:表上**真的印著**「其他」的列」。
PREFIX_ONLY = {"其他"}


def _hits(name):
    """(關鍵字長度, 桶, 關鍵字) 的全部命中,長的優先。"""
    out = []
    for b, keys in KEYS.items():
        for k in keys:
            ok = name.startswith(k) if k in PREFIX_ONLY else k in name
            if ok:
                out.append((len(k), b, k))
    return sorted(out, reverse=True)


def propose(name):
    """原名 → (桶, 理由)。推不出來時桶為 None,理由講**為什麼**推不出來。

    多個桶並列最長 → 回 None。這種情況不准挑一個,那就是猜。
    """
    hits = _hits(name)
    if not hits:
        return None, "BUCKET_RULES 沒有任何關鍵字命中"
    top = hits[0][0]
    tied = {b for n, b, _ in hits if n == top}
    if len(tied) > 1:
        return None, f"同長度命中多個桶 {sorted(tied)},不准挑一個"
    return hits[0][1], f"BUCKET_RULES 關鍵字「{hits[0][2]}」"


def audit(rules_text):
    """每個關鍵字都要真的出現在 `BUCKET_RULES` 裡。回傳夾帶進來的詞。

    這是防我自己的:抄散文成表的時候順手多加一個「看起來也對」的詞,
    就是把判斷偷渡進規則層,而且事後看不出來是哪一條多出來的。
    """
    flat = re.sub(r"[\s（）()、,/—:：]", "", rules_text)
    return [k for keys in KEYS.values() for k in keys if k not in flat]
