# -*- coding: utf-8 -*-
"""把 extract_v2 結果(當前最新一份,非備份檔)橋接進 data.json 供網站用。

口徑(每桶兩個口徑,對應前端切換鈕):
  - 帳面(值):資產負債表帳面金額 = bucket['值']。Trading/OCI 帳面即公允、AC 帳面為攤銷後成本。
    → 寫入 data.json['wide'](沿用既有欄位,前端既有圖表不動)。
  - 成本:取得成本 = bucket['成本']。半年報附註/ AC 表通常無此欄 → null(前端顯示「—」)。
    → 寫入 data.json['wide_cost'](新增;null 保留,不補 0,以區分『未揭露』vs『0』)。

個體(AI3)vs 合併(AI1)分開存,不混進同一張跨行排行:
  合併報表口徑範圍比個體大(含子公司),數字必然大於個體,混在一起比「誰部位最大」會失真。
  AI1 → 寫進獨立區塊 data.json['wide_consol']/['wide_cost_consol']/['banks_consol'],
  網站另開一個「合併報表」分頁(跟總覽同一套元件,只是吃這個區塊),不進主要 wide/banks。

只更新來源檔涵蓋到的格。單一(銀行,期別,類別)若對帳失敗(_pass=False,桶加總跟BS錨對不起來)
→ 整個類別跳過、保留 data.json 原本該類別的值,不拿明知有缺漏的數字覆蓋掉能用的舊值。
單位:仟元 → 億(÷100000,四捨五入取整,與既有 wide 一致)。

舊管線資料不上網:凡 5 家個體(AI3)銀行,新管線(來源檔)沒涵蓋到的期別 → 直接清空(None),
不用舊管線(unified.py 等)產的數字頂著。前端本來就把 None 當「無資料」處理(灰底斜紋),
跟既有「掃描影像檔無法解析」的顯示邏輯一致,不需要另外改網站。
"""
import json, shutil, datetime

SRC = "extract_v2_results.json"
DATA = "data.json"

BANK = {"5835": "國泰", "5836": "富邦", "5841": "中信", "5843": "兆豐", "5847": "玉山"}
# extract_v2 桶名 → data.json wide 欄位桶名(僅 公債→GB 需改名)
BUCKET_MAP = {"公債": "GB", "公司債": "公司債", "金融債": "金融債",
              "資產基礎": "資產基礎", "貨幣市場": "貨幣市場",
              "可轉讓定存單": "貨幣市場",   # NCD 屬貨幣市場工具,併入貨幣市場(網站無獨立欄)
              "其他": "其他", "股票": "股票"}
WIDE_BUCKETS = ["GB", "公司債", "金融債", "資產基礎", "貨幣市場", "其他", "股票"]
CLASSES = ["Trading", "OCI", "AC"]


def to_yi(thousand):
    """仟元 → 億(1億 = 100000 仟元)。"""
    if thousand is None:
        return None
    return round(thousand / 100000)


def doc_period(key):
    yr, per = key[:4], key[4:6]
    return f"{yr}H1" if per == "02" else f"{yr}H2"


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    d = json.load(open(DATA, encoding="utf-8"))
    shutil.copy(DATA, DATA + ".pre_bridge")

    wide = d.setdefault("wide", {})
    wide_cost = d.setdefault("wide_cost", {})
    wide_c = d.setdefault("wide_consol", {})
    wide_cost_c = d.setdefault("wide_cost_consol", {})

    # 清掉舊版曾誤植進主 wide 的合併報表列(如「中信(合併)」):改走獨立區塊,見上面說明
    for cell in [c for c in list(wide) if "(合併)" in c]:
        del wide[cell]
    for cell in [c for c in list(wide_cost) if "(合併)" in c]:
        del wide_cost[cell]
    d["banks"] = [b for b in d.get("banks", []) if "(合併)" not in b]

    def process(key, bank, wide_dst, cost_dst):
        """處理單一文件,回傳 (cell, cell_touched)。skipped_cls 用外層 list 累積。"""
        cls_data = src[key]["cls"]
        cell = f"{doc_period(key)}|{bank}"
        book = dict(wide_dst.get(cell) or {})
        cost = dict(cost_dst.get(cell) or {})
        cell_touched = False
        for cls in CLASSES:
            cb = cls_data.get(cls, {})
            if cb.get("_pass") is False:
                skipped_cls.append(f"{cell} {cls}(對帳失敗:桶加總={cb.get('bucket_sum')} vs BS錨={cb.get('bs_anchor')})")
                continue
            buckets = cb.get("buckets", {})
            for wb in WIDE_BUCKETS:
                book[f"{cls}_{wb}"] = 0
            for wb in WIDE_BUCKETS:
                cost[f"{cls}_{wb}"] = None
            for bname, bv in buckets.items():
                wb = BUCKET_MAP.get(bname)
                if wb is None:
                    print(f"  ⚠ {cell} {cls} 未知桶名『{bname}』→ 丟進『其他』")
                    wb = "其他"
                book[f"{cls}_{wb}"] = (book.get(f"{cls}_{wb}") or 0) + (to_yi(bv.get("值")) or 0)
                c = None if cls == "AC" else to_yi(bv.get("成本"))
                if c is not None:
                    prev = cost.get(f"{cls}_{wb}")
                    cost[f"{cls}_{wb}"] = (prev or 0) + c
            cell_touched = True
        if cell_touched:
            wide_dst[cell] = book
            cost_dst[cell] = cost
        return cell, cell_touched

    touched, touched_c, skipped_cls = [], [], []
    for key in sorted(src):
        code = key[7:11]
        kind = key[12:]
        bank = BANK.get(code)
        if not bank:
            print(f"跳過未知代碼:{key}")
            continue
        if kind == "AI3":
            cell, ok = process(key, bank, wide, wide_cost)
            if ok:
                touched.append(cell)
        elif kind == "AI1":
            cell, ok = process(key, bank, wide_c, wide_cost_c)
            if ok:
                touched_c.append(cell)
                if bank not in d.get("banks_consol", []):
                    d.setdefault("banks_consol", []).append(bank)
        else:
            print(f"跳過未知型別:{key}")

    # 舊管線資料不上網:5 家個體銀行、來源檔沒涵蓋到的期別 → 清空,不用舊數字頂著。
    covered_periods = {c.split("|", 1)[0] for c in touched}
    blanked = []
    for period in d.get("periods", []):
        if period in covered_periods:
            continue
        for bank in BANK.values():
            cell = f"{period}|{bank}"
            if wide.get(cell) is not None or wide_cost.get(cell) is not None:
                wide[cell] = None
                wide_cost[cell] = None
                blanked.append(cell)

    d["_bridge"] = {"source": SRC, "cells": touched, "cells_consol": touched_c,
                    "blanked_no_new_data": blanked,
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "note": "wide=個體帳面;wide_consol=合併帳面(獨立分頁,不進跨行排行);"
                            "wide_cost*=取得成本(null=未揭露);_pass=False 類別已跳過,保留舊值;"
                            "來源檔未涵蓋的個體期別已清空,不用舊管線數字"}

    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已更新 {len(touched)} 格個體 + {len(touched_c)} 格合併 → {DATA}(備份 {DATA}.pre_bridge)")
    for c in touched:
        print("  ", c)
    for c in touched_c:
        print("  [合併]", c)
    if skipped_cls:
        print(f"\n跳過 {len(skipped_cls)} 個對帳失敗的類別(保留原值):")
        for s in skipped_cls:
            print("  ✗", s)
    if blanked:
        print(f"\n清空 {len(blanked)} 格(來源檔未涵蓋,不用舊管線數字):")
        for c in blanked:
            print("  ○", c)


if __name__ == "__main__":
    main()
