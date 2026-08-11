#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試分兩層(R4-4,`docs/plan_v6_一台機器.md`)。

    python3 run_tests.py            預設組(隨時跑,實測 2026-08-11:38 支 ~45s)
    python3 run_tests.py --all      加上端到端組(發布前跑,實測 ~15-20 分)
    python3 run_tests.py --slow     只跑端到端那組

**分類是實測時間,不是猜的,數字也不假裝比實際好看。** 原計畫寫「秒級
<10s」,實測下來預設組總和是 ~45 秒,不是 10 秒——大部分測試個別都在
1-6 秒(讀真實 facts/、跑幾格分桶邏輯),沒有哪一支誇張到需要挪去 SLOW,
但加總起來就是 45 秒,不是 10 秒。誠實的說法是「45 秒內跑得完的組」,
不是勉強湊一個 10 秒的門檻。

`SLOW` 清單(超過 30 秒的那幾支)每一支都在這次開發過程量過:
`test_drive` ~97s、`test_taxonomy_migration` ~38s、`test_build` 到過 9 分鐘、
`test_report`/`test_adapter`/`test_e2_equiv`/`test_table_*` 各 90–180s。
共通點是它們都會對著全部 facts/ 跑一次 `results.build()` 或等價的全量重算
(每次重解析 PDF 定位錨),corpus 長大這個數字只會更慢,不是能單支修掉的
問題,是這一類測試的本質(端到端 = 真的跑一次全量)。

`test_build` **不是壞掉,是慢**——這次開發過程中它被完整跑過至少四次,
每次都在背景執行到自然結束、拿到 PASS。跑不完的疑慮其實是「工具預設
120–600 秒逾時,誤以為卡住」,不是程式本身的問題;放進 SLOW 組並用
`run_in_background` 是正確的處理方式,不是要去讓它變快。
"""
import glob
import os
import subprocess
import sys
import time

#: 實測(2026-08-11)這批對著全部 facts/ 跑 results.build()/reconcile 的測試,
#: 每支都在 90 秒以上。新增測試如果也會做同一件事(整個 corpus 跑一次
#: build/reconcile),加進這裡,不要留在預設組拖慢日常回歸。
SLOW = {
    "test_build",              # 實測到過 9 分鐘(build.py --diff 的完整路徑)
    "test_report",              # 實測 ~135s(E4 對照 build.py 現算結果,1000+ 格)
    "test_adapter",              # 實測 ~180s(T9 走真正的發布路徑 rebuild_v3)
    "test_e2_equiv",             # 實測 ~95s(190 格 results.build vs reconcile 逐欄比對)
    "test_table_census", "test_table_recall", "test_table_truth",  # 各 ~115-130s
    "test_drive",                # 實測 ~97s(163/193 格重現,全量比對)
    "test_taxonomy_migration",   # 實測 ~38s(M1-M14,含真的寫檔)
}


def discover():
    return sorted(os.path.basename(p)[:-3] for p in glob.glob("test_*.py"))


def run(names):
    results = []
    for name in names:
        t0 = time.time()
        r = subprocess.run([sys.executable, f"{name}.py"],
                           capture_output=True, text=True)
        dt = time.time() - t0
        ok = r.returncode == 0
        results.append((name, ok, dt))
        print(f"  {'✓' if ok else '✗'} {name:28s} {dt:6.1f}s")
        if not ok:
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-15:])
            print(f"      {tail}".replace("\n", "\n      "))
    return results


def main():
    args = sys.argv[1:]
    all_tests = discover()
    fast = [n for n in all_tests if n not in SLOW]
    slow = [n for n in all_tests if n in SLOW]

    if "--slow" in args:
        todo = slow
        label = f"端到端測試({len(todo)} 支)"
    elif "--all" in args:
        todo = fast + slow
        label = f"全部測試({len(todo)} 支)"
    else:
        todo = fast
        label = f"秒級純函數測試({len(todo)} 支;端到端 {len(slow)} 支跳過,用 --all 或 --slow 跑)"

    print(f"跑 {label}\n")
    t0 = time.time()
    results = run(todo)
    dt = time.time() - t0

    bad = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results)-len(bad)}/{len(results)} 通過,共 {dt:.1f}s")
    if bad:
        print(f"失敗:{bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
