# -*- coding: utf-8 -*-
"""批次跑 extract_v2 最近兩年 20 份,對帳當裁判。逐份存 JSON、印一行摘要。含速率重試。"""
import glob, json, os, re, time, traceback
import extract_v2 as E

# 顯示用中文名;查不到就回代碼本身(加別家不改程式,不加也能跑)。
BANK = {"5835": "國泰", "5836": "富邦", "5841": "中信", "5843": "兆豐", "5847": "玉山"}
OUT = "extract_v2_results.json"

# 收哪些檔:泛用「YYYYMM_代碼_型別」,用參數篩年份/型別,不硬編某銀行前綴。
FILE_RE = re.compile(r"\d{6}_\d{4}_[A-Za-z0-9]+\.pdf$")
YEARS = {"2021", "2022", "2023", "2024", "2025"}   # 近五年;None=全部歷史
KINDS = {"AI3", "AI1"}       # AI3=個體財報(全部銀行);AI1=合併財報(白名單見 AI1_CODES)
AI1_CODES = {"5841"}  # 合併(AI1)只收中信,避免誤收其他家撐大批次


def with_retry(fn, *a, tries=4, **k):
    for t in range(tries):
        try:
            return fn(*a, **k)
        except Exception as e:
            msg = str(e)
            transient = ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
                         or "timed out" in msg.lower() or "closed" in msg.lower()
                         or "disconnect" in msg.lower() or "unreachable" in msg.lower())
            if transient and t < tries - 1:
                time.sleep(15 * (t + 1))
                continue
            raise


def run_file(fn):
    pages = E.pages_text(fn)
    res, loc = with_retry(E.extract_all, fn, pages)   # 6 呼叫/份(合併共用讀)
    return {"loc": loc, "cls": res}


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
        if name in results and all(c in results[name].get("cls", {}) for c in ("Trading", "OCI", "AC")):
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
        for cls in ("Trading", "OCI", "AC"):
            r = done["cls"].get(cls, {})
            if "_error" in r or r.get("_meta") is None:
                marks.append(f"{cls[:1]}⚠{r.get('_error','')[:24]}")
            elif r.get("_pass"):
                # 弱錨(BS 讀不到、只靠內錨自證)過關 → 標 ~ 待人工複核;雙錨全過才 ✅
                tag = "~" if r.get("_weak_anchor") or r.get("_needs_review") else "✅"
                marks.append(f"{cls[:1]}{tag}")
            else:
                # 真錯:明細表對不上BS(cross)或內部合計不符(int)——與分桶無關。
                why = "cross" if not r.get("_cross_ok") else ("int" if not r.get("_internal_ok") else "?")
                marks.append(f"{cls[:1]}❌{why}")
        print(f"{name} {BANK.get(code, code)}: " + "  ".join(marks))
    # 統計
    tot = pas = 0
    for name, d in results.items():
        for cls in ("Trading", "OCI", "AC"):
            r = d.get("cls", {}).get(cls, {})
            tot += 1; pas += bool(r.get("_pass"))
    print(f"\n通過 {pas}/{tot} 格")
