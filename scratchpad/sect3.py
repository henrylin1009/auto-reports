# -*- coding: utf-8 -*-
"""分層章節切割 v3。標題四層,取「包住錨的最內層」→ 到下一個同層或更淺的標題為止。

  L1  一、           附註主標題
  L1  頁首「…明細表」 年報明細表(它與附註平行,不是誰的子節)
  L2  （一）
  L3  1.  —— 後面必須接非數字,且該行不含 %,否則是表格數字被誤認
"""
import re
CN = "一二三四五六七八九十百"
DUN = r"[、,，'’`．·]"
L1 = re.compile(r"^[ \t　]{0,6}((?:[%s][ 　]{0,2}){1,4})%s" % (CN, DUN))
L2 = re.compile(r"^[ \t　]{0,8}[（(][ 　]{0,2}(?:[%s][ 　]{0,2}){1,3}[ 　]{0,2}[）)]" % CN)
L3 = re.compile(r"^[ \t　]{0,10}\d{1,2}[ 　]{0,2}[.、．][ 　]{0,2}[^\d\s]")
# 年報明細表:頁首前 6 行內,整行以「…表」收尾(可帶（續）)
TBL = re.compile(r"^[ \t　]{0,20}\S{4,40}(明細表|彙總表|變動表|分析表)([（(]續[）)])?[ \t　]*$")

def heads(texts):
    out = []
    for p, t in enumerate(texts):
        lines = [l.rstrip("\r") for l in t.split("\n")]
        for li, ln in enumerate(lines):
            if li < 6 and TBL.match(ln):
                out.append((p, li, 1, ln.strip())); continue
            if L1.match(ln): out.append((p, li, 1, ln.strip())); continue
            if L2.match(ln): out.append((p, li, 2, ln.strip())); continue
            if L3.match(ln) and "%" not in ln: out.append((p, li, 3, ln.strip()))
    return out

def section_of(texts, hs, p, li):
    prev = None
    for h in hs:
        if (h[0], h[1]) <= (p, li): prev = h
        else: break
    if prev is None: return None
    end_p = len(texts) - 1
    for h in hs:
        if (h[0], h[1]) > (prev[0], prev[1]) and h[2] <= prev[2]:
            end_p = h[0]; break
    return (prev[0], end_p, prev[3], prev[2])
