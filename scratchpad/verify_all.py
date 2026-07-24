#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量驗證:每家×每期,對帳(bucket 加總 vs 財報自己的小計/合計)。
   4 家用 extract3.checksum(三層驗算);兆豐用 parse_megabank_main 的 ok。"""
import pdfplumber, extract3 as E, extract_megabank as M
from pathlib import Path

BANKS = [("5841","中信"),("5843","兆豐"),("5835","國泰"),("5836","富邦"),("5847","玉山")]
CACHE = Path("pdf_cache")
def periods():
    for roc in range(109, 115):            # 民109(2020)~114(2025)
        for mth,h in (("02","H1"),("04","H2")):
            yield roc, mth, f"{roc+1911-1911+2020-109}"  # placeholder
# 直接列期別
PERS = []
for yr in range(2020, 2026):
    for mth,h in (("02","H1"),("04","H2")):
        PERS.append((yr, mth, f"{yr}{h}"))

def cell(code, name, yr, mth):
    p = CACHE/f"{yr}{mth}_{code}_AI3.pdf"
    if not p.exists() or p.stat().st_size < 100000:
        return "—"                     # 無檔(未出/未抓)
    t = "\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
    if len(t) < 2000:
        return "N/A(掃描檔)"
    if name == "兆豐":
        mn = M.parse_megabank_main(str(p))
        oc, ac = mn["ok"]["OCI"], mn["ok"]["AC"]
        # Trading 由 fvtpl
        fv = M.parse_megabank_fvtpl(str(p)); tr = bool(fv and fv.get("_ok"))
        marks = {"T": tr, "O": oc, "A": ac}
        # 半年報無 FVTPL 附錄、AC 舊年錯行→退 override(年報有)
        ok = sum(marks.values())
        return "✅3/3" if ok==3 else f"⚠️{ok}/3(" + ",".join(k for k,v in marks.items() if not v) + "缺)"
    res = {}
    for cls in ("Trading","OCI","AC"):
        it, st, ok = E.checksum(t, cls)
        res[cls] = ok
    ok = sum(res.values())
    return "✅3/3" if ok==3 else f"⚠️{ok}/3(" + ",".join({'Trading':'T','OCI':'O','AC':'A'}[k] for k,v in res.items() if not v) + "缺)"

# 表頭
w = 16
print("期別".ljust(6), end="")
for _, nm in BANKS: print(nm.center(w), end="")
print()
for yr, mth, lbl in PERS:
    print(lbl.ljust(8), end="")
    for code, nm in BANKS:
        print(cell(code, nm, yr, mth).center(w), end="")
    print()
