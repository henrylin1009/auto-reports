# -*- coding: utf-8 -*-
"""視覺管線批次跑 + 結果快取 + 待人工彙整。

用法:
  python run_vision.py 2024                 # 跑 2024 年報
  python run_vision.py 2020 2021 2022 2023  # 多年
  python run_vision.py 2024 --h1            # 半年報
快取:output/vision_cache.json（鍵含 pipeline_version，改管線自動失效重跑）。
"""
import os
import sys
import json
import vision_reader as V

PIPELINE_VERSION = "v1"          # 改讀值/對帳邏輯就 +1，舊快取自動失效
BANKS = {"5841": "中信", "5843": "兆豐", "5835": "國泰", "5836": "富邦", "5847": "玉山"}
CLASSES = ("Trading", "OCI", "AC")
PDF_DIR = "pdf_cache"
CACHE = "output/vision_cache.json"


def _pdf(year, code, half):
    p = os.path.join(PDF_DIR, f"{year}{'02' if half else '04'}_{code}_AI3.pdf")
    return p if os.path.exists(p) else None


def _load_cache():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    return {}


def _save_cache(c):
    os.makedirs("output", exist_ok=True)
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def run_batch(years, half=False):
    cache = _load_cache()
    for year in years:
        for code, name in BANKS.items():
            path = _pdf(year, code, half)
            if not path:
                continue
            # 這份文件若有還沒過的格,才做一次 navigate(目錄導覽),三類共用
            todo = [c for c in CLASSES
                    if not cache.get(f"{year}_{name}_{c}_{PIPELINE_VERSION}", {}).get("_pass")]
            nav = None
            if todo:
                try:
                    nav = V.navigate(path)
                except Exception:
                    nav = {}
            for cls in CLASSES:
                key = f"{year}_{name}_{cls}_{PIPELINE_VERSION}"
                if key in cache and cache[key].get("_pass"):
                    continue                        # 過了的不重跑
                print(f"  跑 {year} {name} {cls} ...", flush=True)
                try:
                    r = V.extract_cell(path, cls, nav=nav)
                except Exception as e:
                    r = {"_error": str(e), "_pass": False}
                cache[key] = r
                _save_cache(cache)                   # 隨跑隨存,中斷不丟
    return cache


def review(years, half=False):
    cache = _load_cache()
    lines, total, flagged = [], 0, 0
    for year in years:
        for name in BANKS.values():
            for cls in CLASSES:
                key = f"{year}_{name}_{cls}_{PIPELINE_VERSION}"
                r = cache.get(key)
                if r is None:
                    continue
                total += 1
                if r.get("_pass"):
                    continue
                flagged += 1
                lines.append(f"{year} {name} {cls}")
                if "_error" in r:
                    lines.append(f"    ✗ 錯誤:{r['_error'][:80]}")
                    continue
                k = r.get("class", {})
                lines.append(f"    公允={k.get('公允總額')} 外錨={k.get('外錨')} "
                             f"內部={r.get('_internal_ok')} 外錨交叉={r.get('_cross_ok')}")
                if r.get("_sub_fail"):
                    lines.append(f"    ⚠ 小計不符:{r['_sub_fail']}")
                if r.get("_bucket_mismatch"):
                    lines.append(f"    ? 桶不一致:{r['_bucket_mismatch']}")
    print("\n" + "=" * 52)
    print(f"待人工:{flagged} 格 / 共 {total} 格(乾淨 {total - flagged})")
    print("=" * 52)
    for ln in lines:
        print(ln)
    print("=" * 52)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.isdigit()]
    half = "--h1" in sys.argv
    years = args or ["2024"]
    print(f"開跑視覺管線:{years}({'半年報' if half else '年報'})，pipeline={PIPELINE_VERSION}")
    run_batch(years, half=half)
    review(years, half=half)
