# -*- coding: utf-8 -*-
"""座標式切表 —— 用 PDF 自己帶的 x/y 把表格結構重建回來。

**為什麼不是從 `loc.text()` 的攤平字串下手**(2026-07-29 實測,不要重新推導):
`get_text_range()` 丟掉座標,而財報表格正是靠 x 座標對齊的。實測
`202104_國泰_個體` p133 的攤平字串裡名字擠成一區、數字擠成另一區,任何
regex 都救不回來;同一頁用 y 分列 + x 分欄,col4 逐列相加 281,821,324
與表上印出合計逐字相同 —— 連文字層壞掉的 `20,114299` 都不影響。

這支**不做任何判斷**:不認欄名、不認科目、不認銀行、不認版型。
只有兩件幾何事實 + 一件算術事實:
  · 同一條基線(y)上的字 = 同一列
  · 右緣(x1)相近的數字 = 同一欄        ← 財報金額右對齊
  · 哪一欄是要的欄:**加起來等於錨的那一欄**  ← 判準只有這一個
"""
import collections
import re
import statistics

import pdfplumber

#: 一個 token 算不算金額。要求有千分位逗號或至少 4 位數 —— 年份(114)、
#: 序號、利率(0.30) 不算。**這不是版型知識**:它是「什麼字串長得像仟元金額」。
_NUM = re.compile(r'^\(?[\$＄]?\s*-?(\d[\d,]*)\)?$')

#: 欄的分群距離(pt)。金額右緣落在 12pt 內視為同一欄。
X_GAP = 12
#: 列的分群距離(pt)。同一列的字基線差在此之內。
Y_TOL = 5


def _val(tok):
    """token → 金額。括號 = 負。不像金額回 None。"""
    t = tok.replace(' ', '')
    m = _NUM.match(t)
    if not m:
        return None
    body = m.group(1)
    if ',' not in body and len(body) < 4:
        return None                      # 年份 / 序號 / 短數字
    v = int(body.replace(',', ''))
    return -v if t.startswith('(') or t.endswith(')') else v


def rows(page):
    """一頁 → [(名字, [(右緣x, 金額), ...]), ...],照 y 由上而下。"""
    ws = page.extract_words(x_tolerance=1.5, y_tolerance=2)
    lines = collections.defaultdict(list)
    for w in ws:
        lines[round((w['top'] + w['bottom']) / 2 / Y_TOL)].append(w)
    out = []
    for k in sorted(lines):
        seq = sorted(lines[k], key=lambda w: w['x0'])
        nums, other = [], []
        for w in seq:
            v = _val(w['text'])
            if v is None:
                if w['text'] not in ('$', '＄'):
                    other.append((w['x1'], w['text']))
            else:
                nums.append((w['x1'], v))
        out.append((other, nums))
    return out


def columns(rs):
    """所有金額的右緣分群 → 欄心清單(由左而右)。"""
    xs = sorted(x for _, ns in rs for x, _ in ns)
    if not xs:
        return []
    groups = [[xs[0]]]
    for x in xs[1:]:
        (groups[-1] if x - groups[-1][-1] <= X_GAP else groups.append([x]) or groups[-1]).append(x)
    return [statistics.mean(g) for g in groups]


def grid(rs, cols):
    """[(名字, {欄索引: 金額})]。"""
    left = min(cols) - X_GAP if cols else 0
    out = []
    for other, ns in rs:
        # 名字 = 落在最左欄左邊的非金額 token。利率(0.30%-0.39%)、備註都在欄內或右邊。
        name = ''.join(t for x, t in other if x <= left).strip()
        cell = {}
        for x, v in ns:
            j = min(range(len(cols)), key=lambda i: abs(cols[i] - x))
            cell[j] = v
        out.append((name, cell))
    return out


def reconcile(g, ncols, anchor, min_rows=2, allow_minus=True):
    """找「哪一欄 + 哪一段連續列」加起來等於錨。

    這一個函式同時完成了原本要模型判斷的四件事:選欄、對帳、破折號當 0
    (沒有值就是沒進和)、小計辨識(小計列會讓和變兩倍,自然被連續區間排除)。

    `allow_minus`:允許區間內**恰好一列**取負號。理由不是調參,是財報結構 ——
    「減:備抵損失 / 減:累計減損」印的是正數但語意是減項(實測 202502_5836 AC:
    葉列和 786,795,709 - 備抵損失 543,513 = 錨 786,252,196)。限定「恰好一列」
    而不是任意符號組合,才不會變成拿 2^n 種組合去湊錨。

    ⚠️ **取列數最多的解,不是第一個解。** 實測 202502_5836 AC:第一個解是
    「小計 786,795,709 − 備抵損失 543,513 = 錨」—— 算術全對,抓到的卻是小計列,
    明細一列都沒有。這就是「驗收全綠但產出是廢的」。列數最多 = 挖到最細那一層。

    回傳 (欄索引, 用到的列索引清單, 減項的列索引或 None) 或 None。
    """
    best = None
    for j in range(ncols):
        idx = [i for i, (_, c) in enumerate(g) if j in c]
        vals = [g[i][1][j] for i in idx]
        for a in range(len(vals)):
            s, used = 0, []
            for b in range(a, len(vals)):
                # 小計辨識,純算術:一列若等於「到目前為止的累計和」,它就是小計,
                # 跳過不加。實測 202502_5836 AC 明細 6 列和 786,795,709 之後正好
                # 印一列「小 計 786,795,709」,不跳過就永遠湊不到扣掉備抵損失的錨。
                if allow_minus and s and vals[b] == s:
                    continue      # 小計:跳過(嚴格模式不跳,見 test_table_truth)
                s += vals[b]
                used.append(b)
                if len(used) < min_rows:
                    continue
                n = len(used)
                if s == anchor:
                    if best is None or n > best[0]:
                        best = (n, j, [idx[u] for u in used], None)
                elif allow_minus:
                    # 恰好一列取負:s - 2*v == anchor
                    for k in used:
                        if s - 2 * vals[k] == anchor:
                            if best is None or n > best[0]:
                                best = (n, j, [idx[u] for u in used], idx[k])
                            break
    return best[1:] if best else None


def extract(pdf_path, page_no, anchor, min_rows=2, allow_minus=True):
    """一頁 + 一個錨 → 對得上就回 (欄索引, 該欄的 [(名字, 金額)]),否則 None。"""
    with pdfplumber.open(pdf_path) as pf:
        if not 0 <= page_no < len(pf.pages):
            return None
        rs = rows(pf.pages[page_no])
    cols = columns(rs)
    if not cols:
        return None
    g = grid(rs, cols)
    hit = reconcile(g, len(cols), anchor, min_rows, allow_minus)
    if not hit:
        return None
    j, picked, m = hit
    return j, [(g[i][0], -g[i][1][j] if i == m else g[i][1][j]) for i in picked]
