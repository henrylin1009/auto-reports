# -*- coding: utf-8 -*-
"""抄列自動化 —— 把 `fill.py next/submit` 的人工來回換成一支迴圈。

**這支程式不發明任何判準。** 工單怎麼組(`fill.RULES` + `transcribe.context_pages`)、
六道檢查怎麼跑(`transcribe.verify`)、格式怎麼驗(`facts.validate`)全部沿用既有模組;
本檔只做三件事:組 prompt → 呼叫模型 → 把回來的 JSON 交給既有驗收。

用法:
    python3 fill_auto.py --golden          # 只跑黃金集,**不寫 facts/**,產出評分用結果
    python3 fill_auto.py --golden --limit 3

⚠️ 目前只實作 `--golden`(乾跑)。全面接手 facts/ 要等黃金集分數證明不比人工差 ——
在那之前不要加 apply 分支,否則等於用沒量過的東西覆蓋量過的結果。

READER 切換(`FILL_READER` 環境變數):
    gemini(預設)   走 extract_v2._gen,復用既有的多 key 輪替與節流
    claude          走 `claude -p` 無頭模式(需另裝 CLI;尚未實作)
"""
import argparse
import json
import os
import re
import sys
import time

import facts
import fill
import locate
import transcribe

GOLDEN = "golden/golden.yaml"
OUT_DIR = "out"
CLASSES = ("Trading", "OCI", "AC")

# 工單本體是文字(`context_pages` 給的是頁文字,不是圖),所以這裡不需要處理 PDF。
#
# ⚠️ **不要在這裡另寫一份 JSON schema**。`fill.RULES` 結尾已經有正確的格式範例,
# 手寫第二份的下場實測過:漏了 `source_kind`,`facts.validate` 當場擋下(2026-07-29)。
# 欄位清單一律從 `facts.REQUIRED_REC` 推導,規矩一律引用 RULES 原文。
_REQ = [f for f in facts.REQUIRED_REC if f not in ("doc", "class")]  # doc/class 由本檔補
OUTPUT_CONTRACT = f"""
## 輸出格式(唯一要求)
**只輸出一個 JSON 物件**,不要說明文字、不要 markdown 圍欄,結構就是上面「## 格式」那個。
每份 record 必須有:{_REQ}(其中 rows 的每列必須有 {list(facts.REQUIRED_ROW)})。

**`cols` 的值一律是整數金額**(`facts.py:79` 就是這樣驗的,不是這裡新加的規矩):
  · 逗號要去掉 —— `"316,036"` 要寫成 `316036`
  · **非金額的欄不要放進 cols**:摘要、到期日、利率（％）、張數這類是敘述不是金額,
    放進去會被格式驗收整格退回。它們不抄不影響對帳。
抄不出來就輸出 {{"records": []}}。

## 逐頁交代(實測最大宗的漏抓)
上面「## 來源頁」給了幾頁,就**逐頁想一次「這頁有沒有一份該抄的表」**。
年報常見「附註」與「明細表」印在不同頁、各自印同一個合計 —— 兩份都要抄成
獨立的 record(RULES 已寫「一份對一個來源頁」)。實測漏第二份是最大宗的失敗:
只交明細表、漏掉附註,單獨看那份是對的,合起來卻少一半。
某頁確實沒有表就跳過,不要硬湊。

## 減項列也是資料列
「減:累計減損」「減:備抵評價」這種**減項**不是小計也不是合計,要照抄進 rows
(金額照表上印的正負號)。漏掉它 sum(葉列) 就對不上印出合計。
"""


def build_prompt(loc, cls, pages):
    """工單 = 既有 RULES + 既有 context_pages + 輸出格式合約。

    RULES 一個字都不改寫 —— 它是實測長出來的(88 列缺欄、同名不同桶、比較年度欄),
    在這裡另寫一份摘要等於偷偷換掉判準。
    """
    return "\n".join([
        f"你在抄一份台灣銀行財報的有價證券明細表。錨(BS 合計)= {loc.anchors[cls]:,} 仟元。",
        "",
        fill.RULES,
        OUTPUT_CONTRACT,
        "",
        "## 自己先對一次",
        f"sum(每列的 total_col 那一欄) == printed_total,且 printed_total == {loc.anchors[cls]:,}",
        "",
        "## 來源頁",
        transcribe.context_pages(loc, cls, pages),
    ])


def _parse_json(text):
    """模型可能包 markdown 圍欄或前後加話。抓第一個看起來像物件的區段。

    解析失敗回 None(= 這一格算讀不出來),**不要退回猜一個空 records** ——
    「模型壞了」與「表格真的空」是兩件事,混在一起評分會失真。
    """
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


# 明細表一格可能有數十列、每列五六欄,輸出很長。實測 8192 不夠:202304_5836 Trading
# 在第 20 幾列被切斷,JSON 解析失敗(2026-07-29)。截斷長得像「模型不會抄」,
# 但其實是配額問題 —— 調高上限再談準確度。
MAX_OUTPUT_TOKENS = 32768


def read_gemini(prompt):
    import extract_v2
    from google.genai import types
    from config import MODEL
    r = extract_v2._gen(
        model=MODEL, contents=[prompt],
        # temperature=0 與既有呼叫一致:抄列是照抄,不需要任何發散。
        config=types.GenerateContentConfig(temperature=0,
                                           response_mime_type="application/json",
                                           max_output_tokens=MAX_OUTPUT_TOKENS))
    return r.text


# `claude -p` 無頭模式。用**你自己的 Claude Code 訂閱**,不需要另外的 API key。
# `--allowed-tools ""` 是必要的:工單全文已經在 prompt 裡(頁文字,不是檔案路徑),
# 它不需要讀任何檔;不收掉工具的話它是 agent,可能自作主張去翻 repo 或改檔案。
CLAUDE_TIMEOUT_S = 300


def read_claude(prompt):
    import subprocess
    r = subprocess.run(
        ["claude", "-p", "--allowed-tools", "", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S)
    if r.returncode != 0:
        # **stdout 也要印**。實測 claude -p 失敗時 stderr 可能是空的、訊息在 stdout,
        # 只印 stderr 會得到「rc=1 但沒有任何線索」(2026-07-29 整批 21 格都這樣)。
        raise RuntimeError(f"claude -p 失敗(rc={r.returncode}) "
                           f"stderr={r.stderr[:300]!r} stdout={r.stdout[:300]!r}")
    return r.stdout


READERS = {"gemini": read_gemini, "claude": read_claude}


def read_cell(doc, cls, loc, pages, reader):
    """回 (records, raw_text)。records 為 None 代表模型輸出解析不了。"""
    prompt = build_prompt(loc, cls, pages)
    raw = READERS[reader](prompt)
    data = _parse_json(raw)
    if data is None or "records" not in data:
        return None, raw
    recs = data["records"] or []
    for r in recs:
        r.setdefault("doc", doc)
        r.setdefault("class", cls)
    return recs, raw


def judge(recs, loc, doc, cls):
    """走**既有**驗收:facts.validate(格式) → transcribe.verify(六道)。

    這裡不下「通過與否」的新定義 —— 與 `fill.cmd_submit` 同一套,
    差別只在不寫檔。
    """
    if recs is None:
        return {"outcome": "PARSE_FAIL", "reason": "模型輸出不是合法 JSON"}
    if not recs:
        return {"outcome": "EMPTY", "reason": "records 為空"}
    problems = facts.validate({f"{doc}|{cls}": recs})
    if problems:
        return {"outcome": "INVALID", "reason": "; ".join(problems)}
    ok, res = transcribe.verify(recs, loc)
    if ok:
        return {"outcome": "PASS", "reason": ""}
    return {"outcome": "FAIL",
            "reason": "; ".join(f"{k}:{v}" for k, v in res.items() if v),
            "checks": {k: v for k, v in res.items() if v}}


def golden_cells(limit=None):
    """黃金集 ∩ 有 PDF 的格子。優先跑**已有人工 facts** 的那些 ——
    它們能雙重比對(對黃金集總額、對人工逐列),資訊量最大。"""
    import yaml
    g = yaml.safe_load(open(GOLDEN, encoding="utf-8"))
    human = facts.load()
    out = []
    for doc, spec in g.items():
        if not os.path.exists(f"pdf_cache/{doc}.pdf"):
            continue
        for cls in CLASSES:
            c = spec.get(cls)
            if not isinstance(c, dict) or c.get("verdict") != "ok":
                continue
            out.append({"doc": doc, "cls": cls,
                        "golden_total": c.get("total"),
                        "golden_anchor": c.get("bs_anchor"),
                        "has_human": f"{doc}|{cls}" in human})
    out.sort(key=lambda e: (not e["has_human"], e["doc"], e["cls"]))
    return out[:limit] if limit else out


def run_golden(reader, limit=None, out_path=None):
    cells = golden_cells(limit)
    print(f"黃金集待跑 {len(cells)} 格(其中 {sum(c['has_human'] for c in cells)} 格有人工 facts 可對照)")
    print(f"READER = {reader}   ⚠️ 乾跑:不寫 facts/\n")

    results, t0 = [], time.time()
    loc_cache = {}
    for n, c in enumerate(cells, 1):
        doc, cls = c["doc"], c["cls"]
        print(f"[{n}/{len(cells)}] {doc} | {cls} ...", end=" ", flush=True)
        try:
            if doc not in loc_cache:
                loc_cache[doc] = locate.locate(f"pdf_cache/{doc}.pdf")
            loc = loc_cache[doc]
            if cls not in loc.anchors:
                print("跳過(錨讀不到)")
                results.append({**c, "outcome": "NO_ANCHOR"})
                continue
            pages = list(loc.pages[cls])
            recs, raw = read_cell(doc, cls, loc, pages, reader)
            v = judge(recs, loc, doc, cls)
            total = recs[0].get("printed_total") if recs else None
            v["total_match"] = (total == c["golden_total"]) if total is not None else False
            v["anchor_match"] = (loc.anchors[cls] == c["golden_anchor"])
            results.append({**c, **v, "pages": pages, "read_total": total,
                            "anchor": loc.anchors[cls], "records": recs,
                            # 原文留著:EMPTY 與 PARSE_FAIL 不看原文就只能猜是誰的錯。
                            # **失敗時留全文** —— 截斷過的原文會讓「模型被切斷」與
                            # 「模型自己停」長得一模一樣(2026-07-29 實測踩過)。
                            "raw": raw if v["outcome"] != "PASS" else raw[:500]})
            print(f'{v["outcome"]}  總額{"✓" if v["total_match"] else "✗"}'
                  f'  錨{"✓" if v["anchor_match"] else "✗"}')
            if v["reason"]:
                print(f"        {v['reason'][:160]}")
        except Exception as e:                                  # noqa: BLE001
            print(f"ERROR {type(e).__name__}: {e}")
            results.append({**c, "outcome": "ERROR", "reason": f"{type(e).__name__}: {e}"})

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = out_path or f"{OUT_DIR}/fill_auto_golden_{reader}.json"
    json.dump({"reader": reader, "elapsed_s": round(time.time() - t0, 1),
               "results": results},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _summary(results, out_path, time.time() - t0)
    return results


def _summary(results, out_path, elapsed):
    n = len(results)
    by = {}
    for r in results:
        by[r["outcome"]] = by.get(r["outcome"], 0) + 1
    print(f"\n{'─' * 52}")
    print(f"共 {n} 格,耗時 {elapsed:.0f} 秒")
    for k in sorted(by, key=lambda k: -by[k]):
        print(f"  {k:12s} {by[k]}")
    print(f"  總額正確     {sum(1 for r in results if r.get('total_match'))}/{n}")
    print(f"  錨正確       {sum(1 for r in results if r.get('anchor_match'))}/{n}")
    print(f"\n結果 → {out_path}")
    print("⚠️ facts/ 未被寫入。分數要跟人工基準(逐桶 86/96、誠實 30/30)比過才談接手。")


# ═══════════ 生產模式 ═══════════
#
# 與 `--golden` 的差別只有兩件事:跑的是**真的待辦佇列**、結論交給
# `core.ingest.apply_outcome` **真的落地**。判準一個字都沒變 ——
# `classify_outcome` 就是 `fill.cmd_submit` 的同一套(PASS/FILED/BLOCKED/RETRY/REJECT),
# 擴頁預算與 Gate1/Gate2 的邊界一律由 `core.expand_policy` 決定,不在這裡另寫。
#
# `use_policy=True`:Gate 1 過了就歸檔,分桶問題進 review 佇列等人裁示 ——
# 這正是自動化要的行為(分類未知不該讓一整格重跑,見 expand_policy 檔頭)。


def run_cell(doc, cls, loc, reader, max_level, verbose=True):
    """跑一格到終局。回傳最後那個 outcome dict(已落地)。

    重試迴圈的形狀完全由 `classify_outcome` 的 RETRY 回傳值決定 ——
    要擴哪幾頁、要不要消耗預算都是它算好的,本函式只負責照做並重讀。
    """
    from core import ingest

    pages = list(loc.pages[cls])
    level, retries = 0, 0
    while True:
        recs, raw = read_cell(doc, cls, loc, pages, reader)
        out = ingest.classify_outcome(doc, cls, recs, loc, level, pages, retries,
                                      max_level, use_policy=True)
        if out["outcome"] != "RETRY":
            ingest.apply_outcome(out, {"records": recs or []}, fill.PENDING)
            return out
        if verbose:
            print(f"        RETRY level={out['level']} 加頁 {out['added']}"
                  f"({out['reason'][:80]})")
        pages, level, retries = out["pages"], out["level"], out["retries"]


def run_queue(reader, limit=None, max_level=None):
    import pipeline
    max_level = max_level or pipeline.MAX_LEVEL

    cells = facts.load()
    rejected = fill._rejected_keys()
    todo = []
    while True:
        picked = fill._pick_next(cells, rejected)
        if picked is None:
            break
        doc, cls, loc = picked
        todo.append((doc, cls, loc))
        cells[f"{doc}|{cls}"] = []          # 佔位,讓 _pick_next 往下走
        if limit and len(todo) >= limit:
            break

    if not todo:
        print("ALL DONE —— 沒有待抄的格子。")
        return []

    print(f"待抄 {len(todo)} 格   READER={reader}   max_level={max_level}")
    print("⚠️ 這是生產模式:通過驗收的格子**會寫進 facts/**。\n")

    tally, results = {}, []
    for n, (doc, cls, loc) in enumerate(todo, 1):
        print(f"[{n}/{len(todo)}] {doc} | {cls} ...")
        try:
            out = run_cell(doc, cls, loc, reader, max_level)
            k = out["outcome"]
        except Exception as e:                                  # noqa: BLE001
            print(f"        ERROR {type(e).__name__}: {e}")
            k = "ERROR"
            out = {"outcome": k, "doc": doc, "cls": cls, "reason": str(e)}
        tally[k] = tally.get(k, 0) + 1
        results.append(out)

    print(f"\n{'─' * 52}")
    for k in sorted(tally, key=lambda k: -tally[k]):
        print(f"  {k:10s} {tally[k]}")
    filed = tally.get("PASS", 0) + tally.get("FILED", 0)
    print(f"\n已歸檔 {filed}/{len(todo)} 格。")
    if tally.get("BLOCKED"):
        print(f"{tally['BLOCKED']} 格卡分類表缺口 → 開複核台裁示:python3 server.py")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="抄列自動化(目前只支援黃金集乾跑)")
    ap.add_argument("--golden", action="store_true", help="乾跑黃金集,不寫 facts/")
    ap.add_argument("--run", action="store_true",
                    help="生產模式:跑真的待抄佇列,**會寫進 facts/**")
    ap.add_argument("--limit", type=int, help="只跑前 N 格(省 API 配額)")
    ap.add_argument("--reader", default=os.environ.get("FILL_READER", "gemini"),
                    choices=sorted(READERS))
    ap.add_argument("--out", help="結果輸出路徑")
    a = ap.parse_args(argv)
    if a.golden == a.run:
        ap.error("要嘛 --golden(乾跑),要嘛 --run(會寫 facts/),擇一。")
    if a.golden:
        run_golden(a.reader, a.limit, a.out)
    else:
        run_queue(a.reader, a.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
