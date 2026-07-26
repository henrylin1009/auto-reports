# -*- coding: utf-8 -*-
"""剝離偵測:連續 N 行「只有名字」後面接連續 N 行「只有數字」。
先用 202104_5835 的 p132(已知剝離)/ p133,p134(已知正常)驗偵測器本身。"""
import sys, os, re, collections
import pypdfium2 as pdf

CJK = re.compile(r"[一-鿿]")
NUMONLY = re.compile(r"^[\s\$＄\d,.\-()%－—–]+$")

def kind(ln):
    s = ln.strip()
    if not s: return None
    if NUMONLY.match(s): return "N"
    if CJK.search(s) and not re.search(r"\d{1,3}(,\d{3})+", s): return "C"
    return None                      # 混合行 → 正常,不參與判定

def delaminated(txt, n=3):
    ks = [k for k in map(kind, txt.split("\n")) if k]
    run = "".join(ks)
    return bool(re.search(r"C{%d,}N{%d,}" % (n, n), run))
