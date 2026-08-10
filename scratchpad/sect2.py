# -*- coding: utf-8 -*-
"""分層章節切割。三層標題,取「包住錨的最內層標題」→ 到下一個同層或更淺的標題為止。"""
import re
CN = "一二三四五六七八九十百"
# 頓號在爛 OCR 裡會變成 ' , ` ．; 一律接受(它只在行首中文數字後才有意義)
DUN = r"[、,，'’`．·]"
L1 = re.compile(r"^[ \t　]{0,6}((?:[%s][ 　]{0,2}){1,4})%s" % (CN, DUN))
L2 = re.compile(r"^[ \t　]{0,8}[（(][ 　]{0,2}((?:[%s][ 　]{0,2}){1,3})[ 　]{0,2}[）)]" % CN)
L3 = re.compile(r"^[ \t　]{0,10}(\d{1,2})[ 　]{0,2}[.、．]")

def heads(texts):
    """→ [(page, line, level, 標題行)] 依文件順序"""
    out = []
    for p, t in enumerate(texts):
        for li, ln in enumerate(t.split("\n")):
            for lv, rx in ((1, L1), (2, L2), (3, L3)):
                if rx.match(ln):
                    out.append((p, li, lv, ln.strip()))
                    break
    return out

def section_of(texts, hs, p, li, min_lines=0):
    """(頁,行) 所在的最內層章節 → (起頁, 迄頁, 標題, 層級)"""
    prev = None
    for h in hs:
        if (h[0], h[1]) <= (p, li):
            prev = h
        else:
            break
    if prev is None:
        return None
    lv = prev[2]
    end = (len(texts) - 1, 10**6)
    for h in hs:
        if (h[0], h[1]) > (prev[0], prev[1]) and h[2] <= lv:
            end = (h[0], h[1]); break
    return (prev[0], end[0], prev[3], lv)
