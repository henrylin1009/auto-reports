# -*- coding: utf-8 -*-
"""黃金集評分(P0)——重構的唯一驗收依據。

用法:
    python3 score_golden.py                      # 評分現有 extract_v2_results.json
    python3 score_golden.py 某個結果.json         # 評分指定結果檔
    python3 score_golden.py --run                # 重跑黃金集 10 份(會用 API 配額)再評分

三個指標(判斷成敗看後兩個,不要看通過格數):
    總額正確率   讀出來的總額 == 黃金集答案
    錨正確率     BS 錨 == 黃金集答案            ← 直接量「錨到底讀對沒」
    逐桶正確率   逐桶金額 == 黃金集答案          ← 網站畫的就是桶,這是真正重要的
    誠實率       (正確且收下) + (錯誤且拒收)     ← 同時懲罰「錯了還收」與「對了卻拒收」

比較一律【精確相等】。財報精確加平,容差只會藏誤讀。
"""
import json, os, sys, datetime
import yaml

GOLDEN = "golden/golden.yaml"
CLASSES = ("Trading", "OCI", "AC")
FILL = "__FILL__"


def num(v):
    """把人手填的數字正規化:接受 123、'1,234'、'1,234 + 5,678'(多列併一桶)。
    無法解析就原樣回傳,讓後面照舊當成未填/錯誤處理。"""
    if isinstance(v, int):
        return v
    if not isinstance(v, str):
        return v
    s = v.split("#")[0].replace(",", "").replace(" ", "")
    if not s or s == FILL:
        return v
    try:
        return sum(int(p) for p in s.split("+") if p)
    except ValueError:
        return v


def load_golden():
    if not os.path.exists(GOLDEN):
        sys.exit(f"❌ 找不到 {GOLDEN},請先跑 python3 golden/make_template.py")
    g = yaml.safe_load(open(GOLDEN, encoding="utf-8"))
    for doc in g.values():
        for cls in CLASSES:
            c = doc.get(cls)
            if not isinstance(c, dict):
                continue
            for f in ("total", "bs_anchor", "deriv", "adj"):
                if f in c:
                    c[f] = num(c[f])
            if isinstance(c.get("buckets"), dict):
                c["buckets"] = {b: num(v) for b, v in c["buckets"].items()}
    return g


def unfilled(v):
    return v is None or v == FILL or (isinstance(v, str) and v.strip() == FILL)


def completeness(g):
    """回報黃金集填了多少,沒填的格子不計分。"""
    tot = filled = bt = bf = 0
    for key, doc in g.items():
        for cls in CLASSES:
            c = doc.get(cls) or {}
            for f in ("total", "bs_anchor"):
                tot += 1
                filled += not unfilled(c.get(f))
            bk = c.get("buckets")
            if isinstance(bk, dict):
                for b, v in bk.items():
                    bt += 1
                    bf += not unfilled(v)
    return tot, filled, bt, bf


def self_check(g):
    """黃金集內部自洽:sum(buckets) + deriv + adj == total。抓人工抄寫錯誤,在評分前先擋。

    adj = 調整項(備抵損失/評價調整/未攤銷溢折價…),既不入桶也不是衍生,通常是負數。
    """
    bad = []
    for key, doc in g.items():
        for cls in CLASSES:
            c = doc.get(cls) or {}
            bk, tot, dv = c.get("buckets"), c.get("total"), c.get("deriv")
            aj = c.get("adj", 0)
            if not isinstance(bk, dict) or unfilled(tot) or unfilled(dv) or unfilled(aj):
                continue
            vals = [v for v in bk.values() if not unfilled(v)]
            if len(vals) != len(bk):        # 還沒填完,先不查
                continue
            s = sum(vals)
            if s + dv + aj != tot:
                bad.append(f"  ✗ {key} {cls}: 桶合計 {s:,} + 衍生 {dv:,} + 調整 {aj:,} "
                           f"= {s+dv+aj:,} ≠ total {tot:,}(差 {tot-s-dv-aj:,})")
    return bad


def run_golden(g):
    """重跑黃金集 10 份 → golden/run_<時間戳>.json。會消耗 API 配額。"""
    import extract_v2 as E
    from batch_v2 import with_retry
    out = {}
    for i, key in enumerate(g, 1):
        path = f"pdf_cache/{key}.pdf"
        if not os.path.exists(path):
            print(f"  [{i}/{len(g)}] {key} ❌ 找不到 PDF"); continue
        print(f"  [{i}/{len(g)}] {key} …", flush=True)
        try:
            res, loc = with_retry(E.extract_all, path, E.pages_text(path))
            out[key] = {"loc": loc, "cls": res}
        except Exception as e:
            print(f"       ERR {repr(e)[:100]}")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    dst = f"golden/run_{ts}.json"
    os.makedirs("golden", exist_ok=True)
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {dst}")
    return dst


def score(g, results):
    tot_n = tot_ok = anc_n = anc_ok = bk_n = bk_ok = hon_n = hon_ok = 0
    problems = []

    for key, doc in g.items():
        got_doc = (results.get(key) or {}).get("cls") or {}
        for cls in CLASSES:
            want = doc.get(cls) or {}
            got = got_doc.get(cls) or {}
            accepted = bool(got.get("_pass"))
            verdict = want.get("verdict", "ok")

            # ── 總額 ──
            w_tot = want.get("total")
            correct = None
            if verdict == "unreadable":
                # 正確行為 = 拒收
                hon_n += 1
                hon_ok += (not accepted)
                if accepted:
                    problems.append(f"✗ {key} {cls}: 黃金集判定 unreadable,但管線收下了 "
                                    f"{got.get('recon_fair')} ← 靜默錯誤,最嚴重")
                continue
            if not unfilled(w_tot):
                tot_n += 1
                g_val = got.get("recon_fair")
                correct = (g_val == w_tot)
                tot_ok += correct
                if not correct:
                    problems.append(f"✗ {key} {cls} 總額: 應={w_tot} 實={g_val} "
                                    f"差={None if g_val is None else abs(g_val-w_tot)}")

            # ── 錨 ──
            w_bs = want.get("bs_anchor")
            if not unfilled(w_bs):
                anc_n += 1
                g_bs = got.get("bs_anchor")
                ok = (g_bs == w_bs)
                anc_ok += ok
                if not ok:
                    problems.append(f"✗ {key} {cls} BS錨: 應={w_bs} 實={g_bs}")

            # ── 逐桶 ──
            wb = want.get("buckets")
            if isinstance(wb, dict):
                gb = got.get("buckets") or {}
                for b, wv in wb.items():
                    if unfilled(wv):
                        continue
                    bk_n += 1
                    gv = (gb.get(b) or {}).get("值") or 0
                    ok = (gv == wv)
                    bk_ok += ok
                    if not ok:
                        problems.append(f"✗ {key} {cls} 桶[{b}]: 應={wv} 實={gv}")

            # ── 誠實率 ──
            if correct is not None:
                hon_n += 1
                hon_ok += (correct and accepted) or ((not correct) and (not accepted))
                if correct and not accepted:
                    problems.append(f"~ {key} {cls}: 讀對了卻拒收(過度保守)")
                if (not correct) and accepted:
                    problems.append(f"✗✗ {key} {cls}: 讀錯了卻收下 ← 靜默錯誤,最嚴重")

    return {
        "總額正確率": (tot_ok, tot_n),
        "錨正確率": (anc_ok, anc_n),
        "逐桶正確率": (bk_ok, bk_n),
        "誠實率": (hon_ok, hon_n),
    }, problems


def pct(ok, n):
    return f"{ok}/{n} ({100*ok/n:.0f}%)" if n else "— (無資料)"


def main():
    args = [a for a in sys.argv[1:]]
    g = load_golden()

    tot, filled, bt, bf = completeness(g)
    print(f"黃金集完成度:總額/錨 {filled}/{tot} · 逐桶 {bf}/{bt}")
    if filled == 0:
        sys.exit("\n❌ 黃金集還沒填,先開 PDF 把 golden/golden.yaml 的 __FILL__ 填掉。")
    if filled < tot or bf < bt:
        print("   ⚠ 未填的格子不計分,分數只反映已填部分。")

    bad = self_check(g)
    if bad:
        print(f"\n❌ 黃金集自身不自洽({len(bad)} 處)——先修好再評分,否則尺本身是歪的:")
        print("\n".join(bad))
        sys.exit(1)
    print()

    if "--run" in args:
        src = run_golden(g)
        args = [a for a in args if a != "--run"]
    else:
        src = args[0] if args else "extract_v2_results.json"

    if not os.path.exists(src):
        sys.exit(f"❌ 找不到結果檔 {src}")
    results = json.load(open(src, encoding="utf-8"))
    print(f"評分對象:{src}\n")

    metrics, problems = score(g, results)
    print("── 指標 ──")
    for k, (ok, n) in metrics.items():
        star = " ★" if k in ("逐桶正確率", "誠實率") else ""
        print(f"  {k:<8} {pct(ok, n)}{star}")
    print("  ★ = 判斷重構成敗看這兩個")

    if problems:
        print(f"\n── 問題 {len(problems)} 則 ──")
        for p in problems:
            print("  " + p)
    else:
        print("\n  (無問題)")

    print(f"\n記錄格式(貼進 docs/plan_refactor_v3.md §8):")
    print(f"  | {datetime.date.today()} | {pct(*metrics['總額正確率'])} | "
          f"{pct(*metrics['逐桶正確率'])} | {pct(*metrics['誠實率'])} |")


if __name__ == "__main__":
    main()
