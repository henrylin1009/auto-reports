# -*- coding: utf-8 -*-
"""Camelot(stream flavor)版的切表器 —— 與 `table.py` 同介面,可對照量測。

**為什麼要有第二個引擎**(2026-07-29 實測,不要重新推導):
手刻的 `table.py` 在附註(三期對照的簡單表)上失敗率 8%,一碰到明細表
(面額/利率/取得成本/備抵損失/公允價值/備註 多欄、參差列、基線飄移)就掉到 40%。
`arXiv 2410.09871` 的比較研究結論是「沒有一個工具完美,但常常一個失敗另一個成功」
—— 所以這裡不是要取代 `table.py`,是要能量出「哪個引擎在哪種表上比較行」。

`flavor='stream'` 是唯一可用的:財報沒有格線,`lattice` 抓到 0 張表;
`network`/`hybrid` 會把「取得成本」與「公允價值總額」併成一欄(實測
202104_5835 p133),那正是我們要分開的兩個口徑。
"""
import camelot

import pdf_norm
from table import _val

_CACHE = {}


def grid_of(doc, page_idx):
    """(doc, 0-based 頁碼) → ([(名字, {欄索引: 金額})], 欄數)。

    欄索引用 Camelot 自己的 DataFrame 欄號 —— 它在整張表裡是穩定的,
    正好就是候選列舉需要的「同一欄」概念。
    """
    key = (doc, page_idx)
    if key in _CACHE:
        return _CACHE[key]
    try:
        # 走正規化副本 —— 原檔有半數帶「不允許文字擷取」旗標,Camelot 會拒讀。
        tables = camelot.read_pdf(pdf_norm.norm_path(doc), pages=str(page_idx + 1),
                                  flavor='stream')
    except Exception:
        _CACHE[key] = ([], 0)
        return _CACHE[key]

    grid, ncol = [], 0
    for t in tables:
        df = t.df
        ncol = max(ncol, df.shape[1])
        for _, row in df.iterrows():
            name_parts, cells, seen_num = [], {}, False
            for j, cell in enumerate(row):
                txt = str(cell).strip().replace('\n', '')
                if not txt:
                    continue
                v = _val(txt)
                if v is None:
                    # 數字出現之後的非數字(利率、備註)不算名字的一部分
                    if not seen_num:
                        name_parts.append(txt)
                else:
                    seen_num = True
                    cells[j] = v
            grid.append((''.join(name_parts), cells))
    _CACHE[key] = (grid, ncol)
    return _CACHE[key]
