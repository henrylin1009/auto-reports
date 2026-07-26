# -*- coding: utf-8 -*-
"""定位層:找出「印著某類別合計」的頁,交給 agent 讀。

作法是把 BS 錨的值格式化成千分位字串(518009809 → "518,009,809")在全文 grep。
**零版型知識** —— 不認標題、不認小計、不認欄序,只問「哪一頁印著這個數字」。

為什麼不解析表格結構:曾寫過一個認小計/合計/跨頁的結構解析器,2023+ 只得 61/123,
而失敗全落在 12 個(銀行×分類)組合 —— 那是在重造死規則解析器。
定位與讀值就此分工:**Python 只找頁與驗收,讀表全交給 agent。**
見 docs/plan_v3_2_flow.md。

普查基準(2026-07-26,89 份 × 3 類 = 267 槽):
    錨讀不到 96(全部 ≤2022,2023+ 為 0) / 錨有但無候選頁 2 / 可進 agent 169
"""
import os
import re

import pypdfium2 as pdf

import bs_anchor

CLASSES = ("Trading", "OCI", "AC")

#: 千分位數字。expand() 用它取子錨 —— 只認格式,不認金額大小。
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+")

#: expand() 的回歸基準:手動驗過的 11 格,正確頁必須落在擴張後的候選裡。
#: 每格的正確頁都是用算術證過的(逐項相加 == 錨或其小計),不是關鍵字猜的。
EXPAND_TRUTH = [
    ("202102_5835_AI3", "Trading", 33),   # 跨頁:p33 小計 242,645,908 + p34 45,952,869 = 錨
    ("202102_5847_AI3", "OCI", 24),       # 子附註;此格曾被誤判為「唯一死文件」
    ("202102_5847_AI2", "OCI", 24),
    ("202302_5847_AI3", "OCI", 24),
    ("202402_5847_AI3", "OCI", 23),
    ("202502_5847_AI3", "OCI", 24),
    ("202304_5836_AI3", "Trading", 38),   # 同頁多段
    ("202401_5841_AI1", "OCI", 15),       # 跨頁:債務小計在前一頁
    ("202501_5841_AI1", "OCI", 17),
    ("202502_5841_AI1", "OCI", 17),
    ("202502_5841_AI3", "OCI", 16),
]


class Located:
    """一份 PDF 的定位結果。持有頁文字,S4 不必重讀檔。"""

    def __init__(self, path, bs_page, anchors, pages, texts):
        self.path = path
        self.name = os.path.basename(path)
        self.bs_page = bs_page          # BS 頁 0-based;錨讀不到時為 None
        self.anchors = anchors          # {類別: 仟元};讀不到的類別不出現
        self.pages = pages              # {類別: [候選頁 0-based]},已排除 BS 頁
        self.texts = texts              # 全文,index 對應頁碼

    def text(self, i):
        return self.texts[i]

    def cells(self):
        """逐格產出 (類別, 錨值, 候選頁)。錨讀不到的類別不產出 —— 沉默優於猜。"""
        for c in CLASSES:
            if c in self.anchors:
                yield c, self.anchors[c], self.pages[c]

    def expand(self, cls, level=1):
        """第 1 層抄完 `sum(葉列) != 錨` 時才呼叫:擴張候選頁。

        **由算術驅動,不是由版型驅動。** 對不上就擴,對上就停,
        所以不需要分辨遇到的是哪一種漏抓 —— 實測有三種,同一招都治:

          子附註在另一頁  富邦 202402_5836 OCI p38→p39;玉山 202502_5847 OCI p23→p24
          表格跨頁        國泰 202102_5835 Trading p34→p33;中信 202502_5841 OCI p17→p16
          同頁多段小計    富邦 202304_5836 Trading(108,284,903+31,162,445+492,897=錨)

        **分級,便宜的先來**(level 1→3 逐級放寬,對上就不必往下走):
          1. 鄰頁 ±1        —— EXPAND_TRUTH 11 格全中,平均 2.2 頁
          2. 鄰頁 ±2        —— 平均 4.4 頁
          3. 再加子錨 grep  —— 第 1 層頁上任一數字所在的頁,平均 8.7 頁

        level 3 目前**沒有任何一格用得上**(11 格的正確頁全是鄰頁),留著是因為
        「子附註不在隔壁」在原理上可能發生,但**沒有實例前不要預設開啟** ——
        它的雜訊來源是短數字:中信合併那格 56 個子錨裡,`7,400` 中 5 頁、`3,200` 中 4 頁,
        把 15 個無關頁拉進來,而正確頁 p17 是靠鄰頁規則找到的,不是靠它。

        ⚠️ **試過的較窄判準都失敗,不要退回去**(2026-07-26 實測):
          - 「子錨須標著小計/合計」→ 玉山 p24 合計列是光禿禿的
            `$ 292,943,799 $ ...`,沒有「合計」二字 → 漏抓
          - 「數字須 ≥ N 才當子錨」→ MIN_GROUPS=2 有雜訊、=3 直接歸零
            (小計 144,508,936 只有兩個逗號)。**沒有安全區間 = 判準本身錯**
          雜訊由抄列時 `sum(葉列) == 錨` 濾掉,寧可寬進嚴驗 —— 但也不要無謂地寬。
        """
        l1 = self.pages.get(cls) or []
        if not l1:
            return []
        out = set()
        for i in l1:
            for d in range(1, (2 if level >= 2 else 1) + 1):
                out |= {i - d, i + d}
        if level >= 3:
            subs = set()
            for i in l1:
                subs |= set(_NUM.findall(self.text(i)))
            subs.discard(f"{self.anchors[cls]:,}")
            for i, t in enumerate(self.texts):
                if any(s in t for s in subs):
                    out.add(i)
        return sorted(i for i in out
                      if 0 <= i < len(self.texts) and i not in l1 and i != self.bs_page)

    def __repr__(self):
        got = " ".join(f"{c}:{len(p)}頁" for c, _, p in self.cells())
        return f"<Located {self.name} bs=p{self.bs_page} {got or '無錨'}>"


def locate(path):
    """回傳 Located。錨完全讀不到時 anchors 為空,pages 亦然。"""
    doc = pdf.PdfDocument(path)
    try:
        texts = [(doc[i].get_textpage().get_text_range() or "") for i in range(len(doc))]
    finally:
        doc.close()

    anchors, bs_page = bs_anchor.read(path)
    pages = {}
    for c, v in anchors.items():
        s = f"{v:,}"
        # 排除 BS 頁本身:它就是錨的出處,不是獨立佐證
        pages[c] = [i for i, t in enumerate(texts) if i != bs_page and s in t]
    return Located(path, bs_page, anchors, pages, texts)


# ── 普查 ───────────────────────────────────────────────────────────────────

#: docs/plan_v3_2_flow.md §1 的基準。改動定位邏輯後這組數字必須仍然成立,
#: 變動就是行為改變,要嘛是 bug 要嘛要更新文件 —— 不准默默通過。
CENSUS_BASELINE = {"錨讀不到": 96, "錨有但無候選頁": 2, "可進agent": 169}


def census(paths):
    """回傳 (計數 dict, 明細 list)。明細只收有問題的槽,方便追查。"""
    counts = {"總槽": 0, "錨讀不到": 0, "錨有但無候選頁": 0, "可進agent": 0}
    detail = []
    for p in paths:
        try:
            loc = locate(p)
        except Exception as e:                      # 壞檔不能讓整場普查中斷
            detail.append((os.path.basename(p), "-", f"讀檔失敗 {e}"))
            continue
        for c in CLASSES:
            counts["總槽"] += 1
            if c not in loc.anchors:
                counts["錨讀不到"] += 1
                detail.append((loc.name, c, "錨讀不到"))
            elif not loc.pages[c]:
                counts["錨有但無候選頁"] += 1
                detail.append((loc.name, c, f"無候選頁 錨={loc.anchors[c]:,}"))
            else:
                counts["可進agent"] += 1
    return counts, detail


def _main():
    import argparse
    import collections
    import glob

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--census", action="store_true", help="全語料普查")
    ap.add_argument("--check", action="store_true", help="普查結果須符合基準,否則 exit 1")
    ap.add_argument("--expand", action="store_true", help="跑 expand() 回歸(11 格),不符 exit 1")
    a = ap.parse_args()

    paths = a.paths or sorted(glob.glob("pdf_cache/*.pdf"))

    if a.expand:
        # level 1 必須就全中。若哪天新增的真值要靠 level 2/3 才中,
        # 那是行為改變,要在這裡看見,不准默默調高預設等級。
        rc = 0
        for lv in (1, 2, 3):
            hit, sizes = 0, []
            for doc, cls, need in EXPAND_TRUTH:
                loc = locate(f"pdf_cache/{doc}.pdf")
                got = loc.expand(cls, lv)
                sizes.append(len(got))
                ok = need in got or need in loc.pages[cls]
                hit += ok
                if lv == 1 and not ok:
                    print(f"  ✗ {doc} {cls:<8} 需 p{need}  得 {got}")
            print(f"  level {lv}: 命中 {hit}/{len(EXPAND_TRUTH)}  "
                  f"候選頁 平均 {sum(sizes)/len(sizes):.1f} 最多 {max(sizes)}")
            if lv == 1 and hit != len(EXPAND_TRUTH):
                rc = 1
        return rc

    if not a.census:
        for p in paths:
            print(locate(p))
        return 0

    counts, detail = census(paths)
    print(f"{len(paths)} 份 × {len(CLASSES)} 類 = {counts['總槽']} 槽")
    for k in ("錨讀不到", "錨有但無候選頁", "可進agent"):
        print(f"  {k:<14}{counts[k]}")

    yr = collections.Counter(n[:4] for n, c, w in detail if w == "錨讀不到")
    print("  錨讀不到 依年份:", dict(sorted(yr.items())))
    for n, c, w in detail:
        if w != "錨讀不到":
            print(f"  ⚠ {n} {c} {w}")

    if a.check:
        bad = {k: (counts[k], v) for k, v in CENSUS_BASELINE.items() if counts[k] != v}
        if bad:
            print("\n✗ 與基準不符(實測, 基準):", bad)
            print("  定位行為變了。修 bug,或確認是改進後更新 CENSUS_BASELINE 與 plan_v3_2_flow.md §1")
            return 1
        print("\n✓ 與基準相符")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
