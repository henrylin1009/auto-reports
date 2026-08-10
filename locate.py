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
import collections
import os
import re
import threading

import pypdfium2 as pdf

import bs_anchor

CLASSES = ("Trading", "OCI", "AC")

#: pypdfium2 包的 PDFium 不是 thread-safe 的 —— server.py 用 ThreadingHTTPServer,
#: 一個文件頁面同時打出 /api/doc、/page.png、加上背景輪詢,並發開檔會讓整個
#: process 直接死掉(不是丟例外,是 C 層級崩潰),連帶讓所有路由跟著斷線。
#: 所有 pdfium 呼叫(這裡跟 server.render_png)共用同一把鎖,序列化存取。
PDFIUM_LOCK = threading.Lock()

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

    @property
    def basis(self):
        """報表口徑(個體/合併),從封面判 —— 見 `basis_of`。"""
        return basis_of(self.texts[0] if self.texts else "")

    def text(self, i):
        return self.texts[i]

    def cells(self):
        """逐格產出 (類別, 錨值, 候選頁)。錨讀不到的類別不產出 —— 沉默優於猜。"""
        for c in CLASSES:
            if c in self.anchors:
                yield c, self.anchors[c], self.pages[c]

    def expand(self, cls, level=1):
        """第 `level` 個(由小到大)附註章節的頁 —— 見 `section.pages_at`。

        ⚠️ **2026-07-31 換過語意,回傳值是「取代」不是「追加」。** 舊版回傳
        「要加進候選頁的鄰頁」,呼叫端做 `set(pages) | set(more)`;現在回傳的
        就是下一輪要用的完整頁集合。理由與實測見 `section.py` 檔頭 ——
        擴頁的三種漏抓全是「頁不是文件的單位」的症狀,章節一次涵蓋
        (`EXPAND_TRUTH` 11 格 11/11 不必逐級放寬)。

        方法留在 `Located` 上而不是讓呼叫端直接呼叫 `section` —— 它是
        `fill` / `core.ingest` / `fill_auto` 與測試替身共用的接縫,換成
        模組函式的話每個 `_FakeLoc` 都得跟著長出 `texts`。
        """
        import section
        return section.pages_at(self, cls, level)

    def __repr__(self):
        got = " ".join(f"{c}:{len(p)}頁" for c, _, p in self.cells())
        return f"<Located {self.name} bs=p{self.bs_page} {got or '無錨'}>"


#: 報表口徑。**從封面讀,不從檔名推。**
#: `resolve.download()` 一律把抓到的檔改名存成 `_AI3`(resolve.py:37),所以檔名裡的
#: AI 代碼已經不帶任何意義 —— 舊資料裡 `_AI1` 剛好是合併、`_AI2`/`_AI3` 是個體,
#: 那是舊腳本留下的巧合,不是規律。實測 202404_5841:AI1 錨 1,017,934,513(合併)
#: vs AI3 錨 950,762,131(個體),是兩份不同的報表。
#: 兩種口徑的期別本來就不同(個體只有半年報/年報,合併有四季),混在同一個網格
#: 才會長出一堆永遠空著的欄。
SOLO, CONSOLIDATED, UNKNOWN = "個體", "合併", "?"


def basis_of(text):
    """從封面文字判口徑。**合併優先比對** —— 合併報告封面印「及子公司…合併財務報告」,
    個體報告印「個體財務報告」;兩者都含「財務報告」四字,順序寫反會誤判。"""
    # 攤平空白再比:2002 那批封面把字距拉開印成「財 務 報 告」,原樣比對必敗。
    head = re.sub(r"\s", "", (text or "")[:400])
    if "合併財務報" in head or "及子公司" in head:
        return CONSOLIDATED
    if "個體財務報" in head or "個別財務報" in head:
        return SOLO
    # **2015 以前的封面不印「個體」二字**,只印「財務報告」/「財務報表」。
    # 實測封面:2012 兆豐個體「兆豐國際商業銀行股份有限公司 財務報告」,
    # 同期合併「…股份有限公司及子公司 合併財務報表」。合併那邊一定會印
    # 「及子公司」或「合併」,已在上面攔掉,所以走到這裡的無修飾封面就是母公司財報。
    if "財務報告" in head or "財務報表" in head:
        return SOLO
    return UNKNOWN


#: `locate()` 的結果快取。**純粹是效能,語意不變** —— key 帶 (mtime, size),
#: 檔案一換就自動失效,所以抓到新 PDF 不會拿到舊結果。
#:
#: 為什麼需要:一次 `/api/doc` 會對同一份檔呼叫 `locate()` 三次(三個類別各一次),
#: 每次 1.8s 全花在重抽 170 頁的文字 —— 實測 doc_detail 5.4s 裡 100% 是這個。
#:
#: **有界**(而且很小):`Located` 抓著全文(一份約 0.3 MB),而
#: `fill._build_index()` 會一口氣掃過 89 份檔 —— 無上限的話那一趟就把全部吞進記憶體。
#: 工作台一次只看一份文件,4 份的窗口已經足夠。
_CACHE = collections.OrderedDict()
_CACHE_MAX = 4


def locate(path, _cache=True):
    """回傳 Located。錨完全讀不到時 anchors 為空,pages 亦然。

    回傳值**視為唯讀** —— 快取會把同一個物件交給多個呼叫者(現況全是讀取)。
    """
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    if _cache and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    got = _locate_uncached(path)
    if _cache:
        _CACHE[key] = got
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return got


def _locate_uncached(path):
    with PDFIUM_LOCK:
        doc = pdf.PdfDocument(path)
        try:
            texts = [(doc[i].get_textpage().get_text_range() or "") for i in range(len(doc))]
        finally:
            doc.close()
        # bs_anchor.read() 也開同一份 PDF —— 併在同一段鎖裡,不要放開鎖再搶第二次
        # (bs_anchor 只有這裡呼叫,不會有其他呼叫者需要獨立拿鎖)。
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
        # 章節模式下沒有「逐級放寬」了:正確頁必須落在**最小的那個章節**裡
        # (level 0)。要靠 level 1/2 才中的話是行為改變,要在這裡看見。
        rc, hit, sizes = 0, 0, []
        for doc, cls, need in EXPAND_TRUTH:
            loc = locate(f"pdf_cache/{doc}.pdf")
            got = loc.expand(cls, 0)
            sizes.append(len(got))
            ok = need in got
            hit += ok
            if not ok:
                print(f"  ✗ {doc} {cls:<8} 需 p{need}  得 {got}")
                rc = 1
        print(f"  level 0(最小章節): 命中 {hit}/{len(EXPAND_TRUTH)}  "
              f"頁數 平均 {sum(sizes)/len(sizes):.1f} 最多 {max(sizes)}")
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
