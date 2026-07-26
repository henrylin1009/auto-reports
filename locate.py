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

import pypdfium2 as pdf

import bs_anchor

CLASSES = ("Trading", "OCI", "AC")


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
    a = ap.parse_args()

    paths = a.paths or sorted(glob.glob("pdf_cache/*.pdf"))

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
