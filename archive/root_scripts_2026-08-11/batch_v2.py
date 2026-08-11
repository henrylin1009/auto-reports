# -*- coding: utf-8 -*-
"""批次跑 extract_v2 → extract_v2_results.json。對帳當裁判;結束後做跨期面板驗證。
顯示名 / AI1 白名單來自 config(全站唯一設定源)。"""
import glob, json, os, re, time
import extract_v2 as E
from config import BANKS as BANK, AI1_CODES, CLASSES, PANEL_JUMP_REL

OUT = "extract_v2_results.json"

# 收哪些檔:泛用「YYYYMM_代碼_型別」,用參數篩年份/型別,不硬編某銀行前綴。
FILE_RE = re.compile(r"\d{6}_\d{4}_[A-Za-z0-9]+\.pdf$")
YEARS = {"2021", "2022", "2023", "2024", "2025"}   # 近五年;None=全部歷史
KINDS = {"AI3", "AI1"}       # AI3=個體;AI1=合併(白名單見 config.AI1_CODES)


def _is_daily_quota(msg):
    """每日配額(RPD)耗盡:睡再試也沒用。RPM 則通常帶 retry-in 秒數。"""
    m = msg.lower()
    return ("free_tier_requests" in m and "limit: 500" in m) or "per day" in m or "daily" in m


def with_retry(fn, *a, tries=4, **k):
    """暫態錯誤重試。配額:extract_v2._gen 已會換 key;所有 key 都爆且是日配額 → 立刻放棄不空睡。"""
    for t in range(tries):
        try:
            return fn(*a, **k)
        except Exception as e:
            msg = str(e)
            transient = ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
                         or "timed out" in msg.lower() or "closed" in msg.lower()
                         or "disconnect" in msg.lower() or "unreachable" in msg.lower()
                         or "503" in msg or "unavailable" in msg.lower())
            if not transient or t >= tries - 1:
                raise
            if _is_daily_quota(msg):
                raise   # 日配額耗盡:sleep 無意義
            time.sleep(15 * (t + 1))


def run_file(fn):
    pages = E.pages_text(fn)
    res, loc = with_retry(E.extract_all, fn, pages)
    return {"loc": loc, "cls": res}


def panel_validate(results):
    """跨期離群檢查(唯一面板級規則,個體 AI3;v3-P1:拿掉救援寫回,只留唯讀離群標註)。
       對每個(銀行,分類)時間序列:已通過但偏離鄰期中位 > PANEL_JUMP_REL → 標 _needs_review +
       _panel_outlier(不改數字)。不再把 fail 翻成 pass——那是 ±40% 啟發式蓋掉精確對帳的棘輪
       (見 docs/plan_refactor_v3.md D7),精確自證的錨才是唯一的接受依據。
       回標註摘要列表。"""
    # 只看個體:合併是季度軸,不跟個體半年軸混
    keys = sorted(k for k in results if k.endswith("_AI3"))
    by = {}  # (code, cls) → [(period, key, r)]
    for key in keys:
        code = key[7:11]
        period = key[:6]
        for cls in CLASSES:
            r = (results[key].get("cls") or {}).get(cls) or {}
            by.setdefault((code, cls), []).append((period, key, r))

    notes = []
    for (code, cls), series in by.items():
        series.sort(key=lambda x: x[0])
        for i, (period, key, r) in enumerate(series):
            v = r.get("recon_fair")
            if v is None:
                continue
            # 鄰期(前後各最多 2 期)有值者
            nbr = []
            for j in range(max(0, i - 2), min(len(series), i + 3)):
                if j == i:
                    continue
                nv = series[j][2].get("recon_fair")
                if nv is not None and series[j][2].get("_pass"):
                    nbr.append(nv)
            if len(nbr) < 2:
                continue
            med = sorted(nbr)[len(nbr) // 2]
            if med <= 0:
                continue
            rel = abs(v - med) / med
            bank = BANK.get(code, code)

            if r.get("_pass") and rel > PANEL_JUMP_REL and not r.get("_needs_review"):
                # 離群但已過:標待複核,不改數字
                r["_needs_review"] = True
                r["_panel_outlier"] = True
                r["_panel_note"] = f"偏離鄰期中位 {rel:.0%}(中位={med})"
                notes.append(f"~ {period}|{bank} {cls}: 離群 {rel:.0%} → 待複核")
    return notes


if __name__ == "__main__":
    files = []
    for f in sorted(glob.glob("pdf_cache/*.pdf")):
        if not FILE_RE.search(os.path.basename(f)):
            continue
        try:
            meta = E.doc_meta(f)          # 期別碼異常會 raise → 跳過並提示,不讓整批崩
        except ValueError as e:
            print(f"跳過(檔名/期別異常):{e}")
            continue
        if YEARS and meta["year"] not in YEARS:
            continue
        if KINDS and meta["kind"] not in KINDS:
            continue
        if meta["kind"] == "AI1" and meta["code"] not in AI1_CODES:
            continue
        files.append(f)
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    print(f"批次 {len(files)} 份\n")
    for fn in files:
        name = os.path.basename(fn).replace(".pdf", "")
        if name in results and all(c in results[name].get("cls", {}) for c in CLASSES):
            done = results[name]
        else:
            try:
                done = run_file(fn)
            except Exception as e:
                print(f"{name}: FILE-ERR {repr(e)[:120]}"); continue
            results[name] = done
            json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
        code = E.doc_meta(fn)["code"] or name.split("_")[1]
        marks = []
        for cls in CLASSES:
            r = done["cls"].get(cls, {})
            if "_error" in r or r.get("_meta") is None:
                marks.append(f"{cls[:1]}⚠{r.get('_error','')[:24]}")
            elif r.get("_pass"):
                # 弱錨 / 待複核 → 標 ~ ;雙錨全過才 ✅
                tag = "~" if r.get("_weak_anchor") or r.get("_needs_review") else "✅"
                marks.append(f"{cls[:1]}{tag}")
            else:
                why = "cross" if not r.get("_cross_ok") else ("int" if not r.get("_internal_ok") else "?")
                marks.append(f"{cls[:1]}❌{why}")
        print(f"{name} {BANK.get(code, code)}: " + "  ".join(marks))

    # 跨期面板驗證(寫回 results)
    print("\n── 面板驗證 ──")
    notes = panel_validate(results)
    if notes:
        for n in notes:
            print(" ", n)
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
        print(f"已寫回 {len(notes)} 則面板標註 → {OUT}")
    else:
        print("  (無離群/救援)")

    tot = pas = rev = 0
    for name, d in results.items():
        for cls in CLASSES:
            r = d.get("cls", {}).get(cls, {})
            tot += 1
            pas += bool(r.get("_pass"))
            rev += bool(r.get("_needs_review"))
    print(f"\n通過 {pas}/{tot} 格 · 待複核 {rev} 格")
