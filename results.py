# -*- coding: utf-8 -*-
"""S7 拆職:一份 rows → **事實 / 判定 / 稽核** 三份產物。

舊的 `extract_v2_results.json` 把三種東西混在一個檔:抄到的數字、分桶的結論、
檢查的過程。混在一起的代價是**改一個就得重跑全部** —— 分桶表改一個名字,
就得把 PDF 重讀一遍;而重讀是要花錢的那一步,也是唯一可能引入新錯的那一步。

拆開之後:

    rows.json      事實。抄一次,除非發現抄錯否則永不重跑
    verdict.json   判定。分桶表一改就重算,**純 Python,零 IO 成本**
    audit.json     稽核。五道檢查逐格的結果,是拒收的證據,不是給網站看的

⚠️ **只有 verdict 進網站,audit 不進。** 稽核細節上網會變成雜訊角標
(幾乎每期都會亮),而真正該擋的東西應該直接讓那格拒收,不是畫個角標放行。

跑法:
    python3 results.py scratchpad/rows_v3.json          # 產生三份到 results/
    python3 results.py scratchpad/rows_v3.json --print  # 只印摘要不寫檔
"""
import json
import os

import buckets
import facts
import holdout
import locate
import transcribe
import wide

OUT = "results"


def build(cells):
    """{格: recs} → (verdict, audit)。rows 是 facts/,不是這裡的產物。"""
    verdict, audit = {}, {}
    for key, recs in cells.items():
        loc = locate.locate(f"pdf_cache/{recs[0]['doc']}.pdf")
        ok, checks = transcribe.verify(recs, loc)
        views = wide.cell(recs)
        # 拒收的格子**也要留 verdict**,但把數字留空 —— 讓下游看得到「這格被拒收了」,
        # 而不是靜靜地不存在。不存在與被拒收在畫面上長得一樣,但意義完全不同。
        verdict[key] = {
            "doc": recs[0]["doc"], "class": recs[0]["class"], "pass": ok,
            "wide": views["帳面"].book if ok and views["帳面"].ok else None,
            "wide_cost": views["成本"].book if ok and views["成本"].ok else None,
            "side": {b: views["帳面"].side.get(b) for b in wide.SIDE} if ok else None,
            "others": views["帳面"].others if ok else [],
            "anchor": loc.anchors.get(recs[0]["class"]),
        }
        audit[key] = {
            "sources": [{"page": r["source_page"], "kind": r.get("source_kind"),
                         "rows": len(r["rows"]), "basis": buckets.basis_of(r)}
                        for r in recs],
            "checks": {k: (v if v else "通過") for k, v in checks.items()},
            "pass": ok,
            # 兩個口徑各自為什麼沒有值 —— 這是最常被問的問題,先答在這裡
            "basis_gap": {b: v.reason for b, v in views.items() if v.book is None},
            "unknown": [{"name": n, "amount": a, "why": w}
                        for v in views.values() for n, a, w in v.unknown],
        }
    return verdict, audit


def summary(verdict, audit):
    ok = [k for k, v in verdict.items() if v["pass"]]
    print(f"{len(verdict)} 格:{len(ok)} 通過、{len(verdict) - len(ok)} 拒收")
    nb = [k for k, v in verdict.items() if v["pass"] and v["wide"] is None]
    nc = [k for k, v in verdict.items() if v["pass"] and v["wide_cost"] is None]
    print(f"  通過但**帳面**在文件裡不存在(wide=null):{len(nb)} 格 {nb}")
    print(f"  通過但**成本**在文件裡不存在(wide_cost=null):{len(nc)} 格")
    for k, v in verdict.items():
        if not v["pass"]:
            bad = [f"{c}:{m}" for c, m in audit[k]["checks"].items() if m != "通過"
                   and not m.startswith(("N/A", transcribe.PARTIAL))]
            print(f"  ✗ {k} —— {'; '.join(bad)}")


def main(path=None, write=True, use_holdout=False):
    cells = json.load(open(path, encoding="utf-8")) if path else facts.load()
    train, leak = holdout.split(cells)
    if leak and not use_holdout:
        # 擋在這裡而不是只印警告:保留集一旦混進日常回歸,它就悄悄變成訓練資料了,
        # 而且沒有人會發現 —— 那正是保留集要防的事情本身。
        print(f"✗ 保留集有 {len(leak)} 格混進來:{sorted(leak)}")
        print("  保留集只能用一次,而且用完要作廢換新的。真的要用請加 --holdout。")
        return 1
    cells = cells if use_holdout else train
    verdict, audit = build(cells)
    summary(verdict, audit)
    if not write:
        return 0
    os.makedirs(OUT, exist_ok=True)
    for name, obj in (("verdict", verdict), ("audit", audit)):
        p = f"{OUT}/{name}.json"
        json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  → {p}")
    return 0


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(main(args[0] if args else None, "--print" not in sys.argv,
                          "--holdout" in sys.argv))
