# -*- coding: utf-8 -*-
"""BS 錨:純文字層讀取,不呼叫任何模型。

用金管會統一的會計科目代碼定位,不比對中文標籤——標籤會被排版斷行
(兆豐把「透過損益按公允價值衡量之金融資產」斷成兩行),文字比對必敗。
實測(2026-07-26):2023 年起 126/126 與經自證的既有錨完全相符。

限制:BS 頁必須在文字層裡。2018–2022 有 29/89 份的 BS 是掃描影像,
locate() 會回 None,此時得走視覺路徑(見 docs/plan_refactor_v3.md P1.0c)。
"""
import re

import pypdfium2 as pdf

# 金管會統一科目代碼 → 本專案分類
CODE = {"12000": "Trading", "12100": "OCI", "12200": "AC"}

# 一定要有千分位逗號:排除頁碼、百分比欄、附註編號(六(三))、科目代碼本身
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+")
_ROW = re.compile(r"\s*(\d{5})\b")
_MAX_SCAN = 45          # BS 一定在前段;掃太深會撞到附註裡的同名表


def locate(doc):
    """回傳 BS 頁的 0-based index;文字層裡找不到回 None。"""
    for i in range(min(_MAX_SCAN, len(doc))):
        t = re.sub(r"\s", "", doc[i].get_textpage().get_text_range() or "")
        if ("資產總計" in t or "資產合計" in t) and "金融資產" in t:
            return i
    return None


def _grab(lines):
    """從 BS 頁的文字行抓三類當期金額。

    中文標籤會換行成 2~3 行,數字落在標籤最後一行之後,所以要往下找;
    但撞到下一個 5 位科目代碼就必須停,否則會抓到別的科目的數字。"""
    out = {}
    for n, line in enumerate(lines):
        m = _ROW.match(line)
        if not m or m.group(1) not in CODE:
            continue
        seg, j = line[m.end():], n
        while True:
            hit = _NUM.search(seg)
            if hit:
                # 截斷偵測:完整千分位數字後面不可能再接數字或逗號。
                # OCR 過的文字層會掉逗號(281,821324)或把尾數認成標點(32,776,03。),
                # 兩種都會讓上面的 regex 只吃到前半段而回一個小几個數量級的值——
                # 靜默的錯值比 None 危險得多,寧可整份退給視覺路徑。
                nxt = seg[hit.end():hit.end() + 1]
                if nxt.isdigit() or nxt == ",":
                    break
                out[CODE[m.group(1)]] = int(hit.group().replace(",", ""))
                break
            j += 1
            if j >= len(lines) or _ROW.match(lines[j]):
                break
            seg = lines[j]
    return out


def read(path):
    """回傳 ({Trading/OCI/AC: 仟元}, bs_page)。讀不到回 ({}, None)。

    當期金額 = 標籤後的第一個千分位數字(BS 欄序固定為 當期金額/當期%/前期金額/前期%)。"""
    doc = pdf.PdfDocument(path)
    try:
        i = locate(doc)
        if i is None:
            return {}, None
        lines = (doc[i].get_textpage().get_text_range() or "").splitlines()
    finally:
        doc.close()
    return _grab(lines), i


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        vals, page = read(p)
        if page is None:
            print(f"{p}: BS 不在文字層(需視覺路徑)")
        else:
            got = "  ".join(f"{k}={vals[k]:,}" for k in ("Trading", "OCI", "AC") if k in vals)
            print(f"{p}: p{page}  {got or '(頁找到但沒抓到科目)'}")
