# -*- coding: utf-8 -*-
"""回測跑批 + 待人工彙整。

做兩件事,都不碰數字:
  1. run_batch():對指定年份的五家×三類跑 auto_extract_dual,收集結果。
  2. review_list():把結果掃一遍,挑出「有問題的格」列成人看得懂的清單(體檢報告)。

用法:
  python backtest.py 2020 2021 2022 2023        # 跑這些年的年報(04)
  python backtest.py 2024                        # 單年
輸出:output/backtest_<年>.json(原始結果)+ 螢幕印待人工清單。
"""
import os
import sys
import json
import universal as U

BANKS = {"5841": "中信", "5843": "兆豐", "5835": "國泰", "5836": "富邦", "5847": "玉山"}
CLASSES = ("Trading", "OCI", "AC")
PDF_DIR = "pdf_cache"


def pdf_path(year, code, half=False):
    """年報=04、半年報=02。回傳檔案路徑(不存在回 None)。"""
    tag = "02" if half else "04"
    p = os.path.join(PDF_DIR, f"{year}{tag}_{code}_AI3.pdf")
    return p if os.path.exists(p) else None


def run_batch(years, half=False):
    """對每年×每家×每類跑 auto_extract_dual,回傳巢狀結果 dict。"""
    out = {}
    for year in years:
        out[year] = {}
        for code, name in BANKS.items():
            path = pdf_path(year, code, half)
            if not path:
                out[year][name] = {"_error": "缺檔"}
                continue
            out[year][name] = {}
            for cls in CLASSES:
                print(f"  跑 {year} {name} {cls} ...", flush=True)
                try:
                    out[year][name][cls] = U.auto_extract_dual(path, cls)
                except Exception as e:
                    out[year][name][cls] = {"_error": str(e)}
    return out


def _cell_issues(cls, cell):
    """單格 → 問題清單(list of str);沒問題回 []。"""
    if "_error" in cell:
        return [f"錯誤:{cell['_error']}"]
    m = cell.get("_meta", {})
    issues = []
    if not m.get("book_pass"):
        issues.append(f"✗ 帳面對帳未過(頁{m.get('book_page')}, {m.get('book_model')})")
    # 公允只有 Trading 會跑;被跳過的類不算問題。
    if not m.get("fair_pass_skipped") and not m.get("fair_pass"):
        issues.append(f"✗ 公允對帳未過(頁{m.get('fair_page')})")
    if m.get("book_subtotal_fail"):
        for f in m["book_subtotal_fail"]:
            issues.append(f"⚠ 小計不符(帳面·{f['section']} 差{f['diff']}仟元)")
    if m.get("fair_subtotal_fail"):
        for f in m["fair_subtotal_fail"]:
            issues.append(f"⚠ 小計不符(公允·{f['section']} 差{f['diff']}仟元)")
    if m.get("book_source_type_ok") is False:
        issues.append(f"? 表型疑誤(自報「{m.get('book_source_type')}」頁首「{m.get('book_source_header')}」)")
    if m.get("book_unknown"):
        issues.append(f"+ 新品名(帳面):{m['book_unknown']}")
    if m.get("fair_unknown"):
        issues.append(f"+ 新品名(公允):{m['fair_unknown']}")
    return issues


def review_list(results):
    """掃全結果 → 待人工清單。回傳 (清單行[], 統計 dict)。不重算、只挑旗標。"""
    lines, total, flagged, new_names = [], 0, 0, set()
    for year, banks in results.items():
        for name, classes in banks.items():
            if "_error" in classes:
                lines.append(f"{year} {name}  缺檔")
                continue
            for cls, cell in classes.items():
                total += 1
                issues = _cell_issues(cls, cell)
                if issues:
                    flagged += 1
                    lines.append(f"{year} {name} {cls}")
                    lines += [f"    {t}" for t in issues]
                for t in issues:
                    if t.startswith("+ 新品名"):
                        new_names.update(cell.get("_meta", {}).get("book_unknown") or [])
                        new_names.update(cell.get("_meta", {}).get("fair_unknown") or [])
    stats = {"total": total, "flagged": flagged, "clean": total - flagged,
             "new_names": sorted(new_names)}
    return lines, stats


def print_review(results):
    lines, stats = review_list(results)
    print("\n" + "=" * 56)
    print(f"待人工清單:{stats['flagged']} 格需看 / 共 {stats['total']} 格"
          f"(乾淨 {stats['clean']})")
    print("=" * 56)
    for ln in lines:
        print(ln)
    if stats["new_names"]:
        print("\n冒出的新品名(考慮補進 schema.SYNONYMS/EQUITY_KW):")
        for n in stats["new_names"]:
            print(f"  - {n}")
    print("=" * 56)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.isdigit()]
    half = "--h1" in sys.argv
    years = args or ["2024"]
    print(f"開跑回測:{years}({'半年報' if half else '年報'})")
    results = run_batch(years, half=half)
    os.makedirs("output", exist_ok=True)
    tag = "h1" if half else "annual"
    fp = f"output/backtest_{tag}_{'_'.join(years)}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n原始結果已存:{fp}")
    print_review(results)
