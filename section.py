# -*- coding: utf-8 -*-
"""附註章節切分:錨落在哪一個附註章節裡,那一章就是工單。

取代 `locate.expand()` 的分級擴頁。**擴頁三種漏抓(子附註 / 跨頁 / 同頁多段)
全部是「頁不是文件的單位,章節才是」的症狀** —— 章節一次涵蓋,不必分辨遇到的
是哪一種,也不必逐級放寬。實測(2026-07-31,155 格已驗收的答案當真值):

    每一份附註 record 都落在某個章節內   144/144
    章節頁數                             中位 2 頁  90% 3 頁
    locate.EXPAND_TRUTH 的 10 格          10/10 不必擴頁就涵蓋

⚠️ **只認財報統一的編號體例,不認任何標題文字。** 三層編號(`一、` / `（一）` /
`1.`)是金管會格式,五家共用;而「明細表」三個字是版型。**明細表落不進編號章節,
自動被排除** —— 這正是要的(只抓附註,見下方)。

## 為什麼不抓明細表

一格原本有兩個來源(附註 + 明細表),兩者互對是舊的第 3 道。改成只抓附註的
代價與收穫都量過了(155 格):

    明細表區的章節極大(中位 14 頁),而附註區中位 2 頁 —— 上一版把章節機器
    套在明細表上,那 62 個大命中點全出在那裡。明細表本來就是「一頁一張表、
    表尾印合計」的自足單位,它從來不需要章節。
    12 格當初只抄了明細表,但那 12 格**都有附註頁**(候選頁裡就有),
    所以只抓附註不會少格子。

放棄的是「同期雙來源互對」,承重牆改成人工複核台(使用者裁示,2026-07-31)。
**兩道機器檢查驗的是金額總和,不驗名字掛在哪個金額上** —— 兩列名字互換、
附註把跨桶科目併成一列,兩者都全綠。那是人眼的職責,不要假裝機器擋得住。
"""
import re

#: 三層編號。分隔符放寬:2022 前的 OCR 會把頓號糊成 `'` `’` `` ` `` `,` `.`
#: (實測「八 ' 透過 損 益…」),只認全形頓號會讓舊檔整批切不出章節。
_CN = "一二三四五六七八九十"
_L1 = re.compile(rf"^[ \t　]*([{_CN}]{{1,4}})[ \t　]*[、,.'’`·．，]")
_L2 = re.compile(rf"^[ \t　]*[（(][ \t　]*([{_CN}]{{1,3}})[ \t　]*[）)]")
_L3 = re.compile(r"^[ \t　]*(\d{1,2})[ \t　]*[.、．]\s*\S")
_LEVELS = ((1, _L1), (2, _L2), (3, _L3))

#: 目錄頁把每一個章節標題再印一次,整頁都是假標題 —— 放進索引會讓每一章
#: 的邊界都落在目錄上。判準只看頁首,不掃全頁(附註內文提到「目錄」不算)。
_TOC = re.compile(r"目\s*錄|索\s*引")


def headings(text):
    """一頁 → [(層級, 行號)]。目錄頁回空。"""
    if _TOC.search(text[:200]):
        return []
    out = []
    for n, line in enumerate(text.splitlines()):
        for lv, rx in _LEVELS:
            if rx.match(line):
                out.append((lv, n))
                break
    return out


def index(texts):
    """全文 → [(頁, 層級, 行號)],依頁序。切一份文件算一次,不要逐頁重算。"""
    return [(i, lv, ln) for i, t in enumerate(texts) for lv, ln in headings(t)]


def section_of(texts, page, needle, idx=None):
    """`needle` 出現在 `page` 上時,回傳包住它的**最內層**章節 `(起頁, 迄頁)`(含兩端)。

    不在任何編號章節內回 None —— 明細表區就是這種,而那正是我們要排除的。
    """
    idx = index(texts) if idx is None else idx
    line = next((n for n, l in enumerate(texts[page].splitlines()) if needle in l), None)
    if line is None:
        return None
    before = [h for h in idx if h[0] < page or (h[0] == page and h[2] <= line)]
    if not before:
        return None
    start = before[-1]                       # 最內層 = 錨之前最後一個標題
    after = [h for h in idx
             if (h[0], h[2]) > (start[0], start[2]) and h[1] <= start[1]]
    end = after[0][0] if after else len(texts) - 1
    return start[0], max(end, start[0])


def units(loc, cls):
    """一格 → 工單清單,`[(起頁, 迄頁), ...]`,**由小到大排**。

    ⚠️ **不設頁數上限。** 上限是魔術常數,而這裡有更好的判準:錨值的雜訊命中
    (印在「信用風險集中度」「主要股東」那種表上)落在沒有細分標題的大章裡,
    切出來就是 100+ 頁;真正的附註章節中位 2 頁。**由小到大試,對上就停**,
    大的自然永遠輪不到 —— 跟擴頁一樣由算術收斂,不由常數卡死。
    """
    a = loc.anchors.get(cls)
    if a is None:
        return []
    needle, idx, out = f"{a:,}", index(loc.texts), []
    for p in loc.pages.get(cls, []):
        s = section_of(loc.texts, p, needle, idx)
        if s and s not in out:
            out.append(s)
    return sorted(out, key=lambda s: (s[1] - s[0], s[0]))


def pages(unit):
    """`(起頁, 迄頁)` → 頁碼清單(0-based),餵給 `transcribe.context_pages`。"""
    return list(range(unit[0], unit[1] + 1))


def pages_at(loc, cls, level):
    """第 `level` 小的章節 → 頁碼清單;沒有那麼多章節回 []。

    **抄列迴圈的唯一取頁入口**(`fill` / `fill_auto` / `core.ingest` 三邊共用)——
    取代 `locate.Located.expand(cls, level)`。`level` 仍然沿用「對不上就 +1」,
    但語意換了:不是把範圍放寬一圈鄰頁,而是**換下一個章節試**。

    ⚠️ 回傳的是**取代**用的頁集合,不是要跟舊的聯集起來。舊的擴頁是
    `pages | expand(level)`(愈擴愈大),這裡每一級是各自獨立的一個章節 ——
    聯集起來只會把不相干的章節混進同一份工單。
    """
    us = units(loc, cls)
    return pages(us[level]) if level < len(us) else []
