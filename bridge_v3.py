# -*- coding: utf-8 -*-
"""R6:把 v3 的 `results/verdict.json` 橋接進 `data.json`。

與 `bridge_v2.py` 的差別**不是換個來源檔**,是換了一種可信度:

    bridge_v2  吃 extract_v2 的分桶結論 —— 桶名是 LLM 當場吐的,認不得就丟「其他」
    bridge_v3  吃 rows 算出來的 wide   —— 桶名查表,認不得就**讓那格拒收**

⚠️ **預設不寫檔。** 這支會改到已經發布出去的數字(玉山「國外機構發行債券」
由「其他」改判「公債」,2024 OCI 公債 419.7 億 → 787.7 億),所以預設只印差異。
確認差異是預期的,才加 `--write`。

⚠️ **一格只有兩種下場:有數字,或 null。** 拒收的格子寫 null,**不准保留舊值** ——
bridge_v2 的做法是「對帳失敗就跳過、留著舊數字」,那會讓一個已知有問題的數字
繼續掛在網站上,而且看起來跟正常值一模一樣。留 null 前端會畫成灰底斜紋。

跑法:
    python3 bridge_v3.py            # 只印差異
    python3 bridge_v3.py --write    # 真的寫進 data.json(會先備份)
"""
import datetime
import json
import shutil

from config import BANKS, WIDE_BUCKETS

SRC, DATA = "results/verdict.json", "data.json"


def to_yi(v):
    """仟元 → 億(1 億 = 100,000 仟元),與既有 wide 一致。"""
    return None if v is None else round(v / 100000)


def cell_of(key):
    """`202404_5843_AI3|OCI` → (`2024H2|兆豐`, `OCI`) 或 None(非個體報表)。"""
    doc, cls = key.split("|")
    yr, per, code, kind = doc[:4], doc[4:6], doc[7:11], doc[12:]
    if kind != "AI3" or code not in BANKS or per not in ("02", "04"):
        return None
    return f"{yr}{'H1' if per == '02' else 'H2'}|{BANKS[code]}", cls


def apply(verdict, data):
    """回傳 {格: {欄: (舊, 新)}},只列**有變動**的欄。不動 `data`。"""
    diff = {}
    for key, v in sorted(verdict.items()):
        got = cell_of(key)
        if got is None:
            continue
        cell, cls = got
        for dst, src in (("wide", "wide"), ("wide_cost", "wide_cost")):
            book = v[src]
            cur = (data.get(dst) or {}).get(cell) or {}
            for wb in WIDE_BUCKETS:
                col = f"{cls}_{wb}"
                new = to_yi(book[wb]) if book else None
                old = cur.get(col)
                if old != new:
                    diff.setdefault(f"{dst} {cell}", {})[col] = (old, new)
    return diff


def write(verdict, data):
    for key, v in verdict.items():
        got = cell_of(key)
        if got is None:
            continue
        cell, cls = got
        for dst, src in (("wide", "wide"), ("wide_cost", "wide_cost")):
            book = v[src]
            tgt = data.setdefault(dst, {}).setdefault(cell, {})
            if tgt is None:
                tgt = data[dst][cell] = {}
            for wb in WIDE_BUCKETS:
                tgt[f"{cls}_{wb}"] = to_yi(book[wb]) if book else None
    # 「其他」的成分留在 data.json,前端可展開(R6 規格)。展開的用途是:
    # 「其他」變大時分得出來是真的其他變多,還是混進了認不出來的東西。
    data["others_v3"] = {k: v["others"] for k, v in verdict.items() if v["others"]}
    data["_bridge_v3"] = {
        "source": SRC, "cells": sorted(verdict), "at":
        datetime.datetime.now().isoformat(timespec="seconds"),
        "note": "wide=帳面(公允/攤銷後成本);wide_cost=取得成本;"
                "null=該口徑在文件裡不存在或該格拒收,**不是 0**;"
                "衍生與評價調整不進 7 桶,見 others_v3 與 results/audit.json"}


#: **Phase 1 寫入防護(2026-07-27)。** 這支有一個結構性缺陷:它 `json.load` 落地的
#: `results/verdict.json`,而那個檔的新鮮度沒有任何保證 —— 實測曾落後 25 小時、
#: 缺 22 格,且是在分類表已知有 bug 的時候算出來的。按下 `--write` 就會把它發布。
#: 職責已由 `build.py` 接手(當次由 facts/ 重建,不讀落地檔)。
#: `cell_of()` / `to_yi()` 仍被 `build.py` 引用,所以檔案不刪。
FROZEN = ("data.json 已改由 build.py 建置(唯一寫入者,當次重建不讀落地 verdict)。\n"
          "  下一步:python3 build.py            # dry-run,寫 preview/\n"
          "  規格:docs/plan_phase1_build.md")


def main(do_write=False):
    if do_write:
        raise SystemExit("✗ bridge_v3 已停止寫入 data.json。\n  " + FROZEN)
    verdict = json.load(open(SRC, encoding="utf-8"))
    data = json.load(open(DATA, encoding="utf-8"))
    diff = apply(verdict, data)
    covered = {cell_of(k)[0] for k in verdict if cell_of(k)}
    print(f"{len(verdict)} 格 verdict → {len(covered)} 個網站格:{sorted(covered)}")
    print(f"\n{len(diff)} 個(格 × 口徑)有變動:")
    for cell, cols in sorted(diff.items()):
        print(f"\n  {cell}")
        for col, (old, new) in sorted(cols.items()):
            print(f"      {col:<14} {str(old):>10} → {str(new):>10}")
    if not do_write:
        print("\n（未寫檔。確認差異無誤後加 --write）")
        return 0
    shutil.copy(DATA, DATA + ".pre_bridge_v3")
    write(verdict, data)
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已寫入 {DATA}(備份 {DATA}.pre_bridge_v3)")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main("--write" in sys.argv))
