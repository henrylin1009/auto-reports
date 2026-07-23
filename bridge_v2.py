# -*- coding: utf-8 -*-
"""把 extract_v2 結果(當前最新一份,非備份檔)橋接進 data.json 供網站用。

口徑(每桶兩個口徑,對應前端切換鈕):
  - 帳面(值):資產負債表帳面金額 = bucket['值']。Trading/OCI 帳面即公允、AC 帳面為攤銷後成本。
    → 寫入 data.json['wide'](沿用既有欄位,前端既有圖表不動)。
  - 成本:取得成本 = bucket['成本']。半年報附註/ AC 表通常無此欄 → null(前端顯示「—」)。
    → 寫入 data.json['wide_cost'](新增;null 保留,不補 0,以區分『未揭露』vs『0』)。

只更新來源檔涵蓋到的格,舊期別/未涵蓋的格保留原樣。
單一(銀行,期別,類別)若對帳失敗(_pass=False,桶加總跟BS錨對不起來)→ 整個類別跳過、
保留 data.json 原本該類別的值,不拿明知有缺漏的數字覆蓋掉能用的舊值。
單位:仟元 → 億(÷100000,四捨五入取整,與既有 wide 一致)。
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

    touched, skipped_cls = [], []
    for key in sorted(src):
        code = key[7:11]
        bank = BANK.get(code)
        if not bank:
            print(f"跳過未知代碼:{key}")
            continue
        period = doc_period(key)
        cell = f"{period}|{bank}"
        cls_data = src[key]["cls"]

        # 從既有值出發(merge),而非整格重建:被跳過的類別保留 data.json 原值
        book = dict(wide.get(cell) or {})
        cost = dict(wide_cost.get(cell) or {})
        cell_touched = False
        for cls in CLASSES:
            cb = cls_data.get(cls, {})
            if cb.get("_pass") is False:
                skipped_cls.append(f"{cell} {cls}(對帳失敗:桶加總={cb.get('bucket_sum')} vs BS錨={cb.get('bs_anchor')})")
                continue   # 整類跳過,保留舊值
            buckets = cb.get("buckets", {})
            # 帳面:每個 wide 桶預設 0(沿用既有慣例:無此桶=0)
            for wb in WIDE_BUCKETS:
                book[f"{cls}_{wb}"] = 0
            # 成本:預設 None(未揭露),有值才填
            for wb in WIDE_BUCKETS:
                cost[f"{cls}_{wb}"] = None
            for bname, bv in buckets.items():
                wb = BUCKET_MAP.get(bname)
                if wb is None:
                    print(f"  ⚠ {cell} {cls} 未知桶名『{bname}』→ 丟進『其他』")
                    wb = "其他"
                book[f"{cls}_{wb}"] = (book.get(f"{cls}_{wb}") or 0) + (to_yi(bv.get("值")) or 0)
                # AC 攤銷成本表無『取得成本』欄,extract 以 0 佔位 → 視為未揭露(null),不進成本檢視。
                c = None if cls == "AC" else to_yi(bv.get("成本"))
                if c is not None:
                    prev = cost.get(f"{cls}_{wb}")
                    cost[f"{cls}_{wb}"] = (prev or 0) + c
            cell_touched = True

        if cell_touched:
            wide[cell] = book
            wide_cost[cell] = cost
            touched.append(cell)

    d["_bridge"] = {"source": SRC, "cells": touched,
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "note": "wide=帳面(值);wide_cost=取得成本(null=未揭露);_pass=False 類別已跳過,保留舊值"}

    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已更新 {len(touched)} 格 → {DATA}(備份 {DATA}.pre_bridge)")
    for c in touched:
        print("  ", c)
    if skipped_cls:
        print(f"\n跳過 {len(skipped_cls)} 個對帳失敗的類別(保留 data.json 原值):")
        for s in skipped_cls:
            print("  ✗", s)


if __name__ == "__main__":
    main()
