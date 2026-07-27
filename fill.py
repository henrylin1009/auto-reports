# -*- coding: utf-8 -*-
"""agent 面向的抄列 CLI。三個指令,每個都以「下一步做什麼」收尾 —— agent 不必推理流程。

    python3 fill.py next               印出一格待抄的候選頁,或明確的下一步指示
    python3 fill.py submit <path>      驗收剛寫好的 rows,PASS / RETRY / REJECT 三選一
    python3 fill.py status             已完成 / 待抄 / 人審佇列 三行

**狀態全在檔案裡,這支程式不持有任何跨呼叫狀態**:正在抄哪一格、抄到第幾級擴張
記在 `work/pending.json`;過關的進 `facts/`;拒收的進 `work/rejected/`。三者
在全新的 session、全新的電腦上都重建得出來 —— 這是 T3 的核心設計性質。

⚠️ 這支程式不放任何檢查邏輯,也不做任何「順手修」(補 0、改名字、刪小計)。
   驗收全部交給 `transcribe.verify()` / `facts.validate()`;抄不過就退回重抄,
   不在這裡新增接受分支。

⚠️ 不准呼叫任何模型 API(使用者已定案)。讀表的是外部的 Claude Code agent,
   這支程式只做確定性的機械工作:找頁、驗收、擴張、歸檔、記進度。
"""
import datetime
import glob
import json
import os
import sys

import buckets
import facts
import locate
import pipeline
import transcribe

WORK_DIR = "work"
PENDING = f"{WORK_DIR}/pending.json"
REJECTED_DIR = f"{WORK_DIR}/rejected"
BLOCKED_DIR = f"{WORK_DIR}/blocked"
PROPOSALS = f"{WORK_DIR}/proposals.jsonl"
INDEX = f"{WORK_DIR}/index.json"

RULES = """## 事實層規矩(違反會被退回)
- name 存表上印的原名 —— 不正規化、不翻譯、不分桶、不改錯字
- cols 的 key 存原欄名(「取得成本」「公允價值總額」「帳面金額」…)
- 缺的欄不放 key,不准補 0 —— 未揭露與 0 是不同的事實。
  **「印了 `-`」怎麼記,看是哪一欄**(實測 88 列缺欄,這條分得開):
    · **total_col(合計欄)印 `-` → 記 0。** 那一欄每列都必須有,缺了第 1 道會擋
      (實測訊息:「有列缺合計欄『114年12月31日』:['政府公債']」)。
    · **其他欄空白或 `-` → 不放 key。** 絕大多數缺欄根本不是零,是「這一列本來就
      沒有那個欄位」(衍生工具無取得成本、股票無面額),補 0 會製造假資料。
- 小計 / 合計不是資料列,不進 rows
- **比較年度那一欄照抄**(如「113年12月31日」),不要只抄當期。
  它是唯一能看出「同一列被改名」的東西 —— 兆豐把「受益憑證」改成
  「不動產投資信託受益證券」、玉山把「上市（櫃）股票」改成「股票及基金」,
  兩次都是靠比較欄金額逐字相同才確認標的沒變。
- **兩個欄名撞名時**(明細表常有「總額」= 面額總額,又有「公允價值總額」),
  取能對到印出合計的那一欄,另一欄可以不抄。不要讓兩個不同意義的欄共用一個 key。
- **註腳記號(（註）、（註一）、（註二）…)列名與欄名都照抄,不要剝掉。**
  「哪個後綴算註腳」是判斷,判斷一律留在判斷層(buckets.SYN),不在抄列做。
  同義詞是機械推得出來的:同一份文件、金額相同 → `synonyms.py` 自動配對
  (玉山 202504:附註「金融債券」== 明細表「金融債券（註二）」131,465,522,零衝突)。
- **表上有分段就每列都要填 group**(段落原名,如「債務工具」「權益工具」「有價證券」)。
  沒有分段才可以不填。兩個理由,都不是格式潔癖:
  ① 段落是唯一分得出**同名不同桶**的東西 —— 富邦 202304 Trading p38 同一份附註裡
     「其他」出現兩次(有價證券段 5,891,015、衍生金融資產段 4,826,250),名字一樣桶不一樣
  ② 段小計是該段**公允價值的唯一來源**。中信/兆豐 OCI 附註逐桶印的是成本,
     公允只出現在段的「小計 / 淨額」那一層(兆豐 202404 權益段淨額 41,701,384
     == 明細表 股票 41,398,782 + 受益憑證 302,602)。沒有 group 就接不回去
- 同一格可能有多份 record(年報通常是「附註」+「明細表」),一份對一個來源頁
- 抄不出來就寫 {"records": []}。不要猜 —— 猜錯比空白糟糕得多

## printed_total 與 printed_totals 的差別(最常填錯的地方)
- printed_total:表上印的**總計**,一個數字,要等於錨值
- printed_totals:**逐欄**的合計。key 必須是 cols 裡出現過的**欄名**
  ✓ {"取得成本": 44631513}      ← 「取得成本」是欄名,rows 的 cols 裡有
  ✗ {"小計": 686764055}         ← 「小計」不是欄名,是表上的中間小計
  ✗ {"113年12月31日小計": ...}  ← 同上
  **表上的中間小計(例如備抵損失前的『小計』)不要放這裡。**
  沒有逐欄合計就**整個省略** —— 省略是誠實的「不適用」,填錯會變成失敗

## 格式
{"records": [{"source_page": 31, "source_kind": "附註", "total_col": "...",
  "printed_total": 9082587, "printed_totals": {"取得成本": ...},
  "rows": [{"name": "公司債", "group": "有價證券", "cols": {"取得成本": ..., "公允價值總額": ...}}]}]}"""


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")


def _key(doc, cls):
    return f"{doc}|{cls}"


def _rejected_path(doc, cls):
    return f"{REJECTED_DIR}/{doc}__{cls}.json"


def _all_docs():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob("pdf_cache/*.pdf"))


def _marked_keys(d):
    keys = set()
    for p in glob.glob(f"{d}/*.json"):
        doc, cls = os.path.basename(p)[:-5].rsplit("__", 1)
        keys.add(_key(doc, cls))
    return keys


def _rejected_keys():
    return _marked_keys(REJECTED_DIR) | _marked_keys(BLOCKED_DIR)


def _taxonomy_gap(recs, loc):
    """只差「分類表沒收錄」時回傳提案清單,否則 None —— **擴頁永遠修不好這種失敗。**

    第 5 道「列皆可分桶」有兩種失敗,長得一樣但處置相反:

      (a) 兩層附註的小計列 —— 名字對不到桶,但**擴頁修得好**。
          玉山 2021H1 OCI 實測:主附註兩列「權益工具投資 / 債務工具投資」相加剛好 == 錨,
          前四道全綠,而明細在子附註 p24。這種一定要擴。
      (b) 分類表缺口 —— 真的新科目名,**擴頁永遠修不好**。
          國泰 202504 Trading 實測:「基金受益憑證」兩表同名同額,擴到 8 頁仍卡住,
          白燒約 8 輪(level 2 的頁文字是 level 0 的 4.7 倍,每輪重讀一次)。

    判準是**模擬**,不是比對錯誤訊息:每一個對不到桶的名字都有 `rules.propose()` 的提案,
    而且**假裝把提案收錄進去之後這一格會通過**,才算分類表缺口。

    ⚠️ 一開始寫成「唯一的 hard failure 是第 5 道」,用真實資料一測就破:
       未收錄的名字會讓第 3 道也跟著報「兩邊都對不到桶」(國泰 202504 Trading 實測,
       附註 p35 + 明細表 p135 兩份 record 都有那個名字)。那是**同一個根因的第二個症狀**,
       不是另一個問題 —— 照訊息比對會漏判,而漏判等於這個修完全沒作用。
       模擬則直接回答對的問題:「收錄之後還過不過?」

    ⚠️ 判錯的後果是可回復的:提案會送到人眼前,看到不像科目名的東西就退掉再 requeue。
       **人審就是這裡的安全網**,所以寧可短路得積極一點,也不要白燒擴頁。
    """
    import rules

    unknown = {row["name"] for rec in recs for row in rec["rows"]
               if buckets.bucket(row) is None}
    if not unknown:
        return None

    props = []
    for name in sorted(unknown):
        if buckets.pending({"name": name}):
            return None              # 已在人審佇列 —— 規則不得代決
        b, why = rules.propose(buckets.norm(name))
        if b is None:
            return None              # 提不出來 → 可能是小計,交給擴張
        props.append({"name": name, "bucket": b, "why": why})

    # 模擬收錄後重驗。**只在這個判斷裡暫時生效,不寫進 buckets.SYN** ——
    # 收錄是人的動作,git diff 就是審核介面(見 buckets.py 開頭)。
    saved = dict(buckets._SYN_N)
    try:
        buckets._SYN_N.update({buckets.norm(p["name"]): p["bucket"] for p in props})
        ok, _ = transcribe.verify(recs, loc)
    finally:
        buckets._SYN_N.clear()
        buckets._SYN_N.update(saved)
    return props if ok else None


def _pdf_signature():
    """偵測 pdf_cache/ 有沒有變動(新增/刪除/換檔)—— 不比對內容,比 mtime 夠了。"""
    return sorted((os.path.basename(p), int(os.path.getmtime(p)))
                  for p in glob.glob("pdf_cache/*.pdf"))


def _build_index():
    """對每份 PDF 跑一次 locate(),快取「哪個類別有候選頁」。這是唯一的 O(n) 全掃,
    之後 next() 只查表,只對選中的那一格重新 locate() 一次(要拿頁文字)。"""
    sig = _pdf_signature()
    cells = {}
    for doc in _all_docs():
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        cells[doc] = {cls: bool(pages) for cls, _, pages in loc.cells()}
    idx = {"sig": sig, "cells": cells}
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump(idx, open(INDEX, "w", encoding="utf-8"))
    return idx


def _load_index():
    sig = _pdf_signature()
    if os.path.exists(INDEX):
        idx = json.load(open(INDEX, encoding="utf-8"))
        if [tuple(x) for x in idx.get("sig", [])] == sig:
            return idx
    return _build_index()


def _doc_sort_key(doc):
    """T4 §3:2023+ 優先於 ≤2022;同範圍內年報(期別 04)優先於半年報(期別 02,
    第 3 道「雙表互對」只有年報才跑,驗證強度最高,問題早暴露划算);
    同類型內年份新的優先。"""
    yyyy, mm = int(doc[:4]), doc[4:6]
    return (0 if yyyy >= 2023 else 1, 0 if mm == "04" else 1, -yyyy, doc)


def _pick_next(cells, rejected_keys):
    """回傳 (doc, cls, loc),或 None(現有 PDF 裡沒有待辦的格子了)。"""
    index = _load_index()
    for doc in sorted(index["cells"], key=_doc_sort_key):
        avail = index["cells"][doc]
        for cls in locate.CLASSES:
            if not avail.get(cls):
                continue          # 錨有但無候選頁,不是 agent 能抄的格子(見 locate.census)
            key = _key(doc, cls)
            if key in cells or key in rejected_keys:
                continue
            return doc, cls, locate.locate(f"pdf_cache/{doc}.pdf")
    return None


def _render(doc, cls, loc, pages):
    anchor = loc.anchors[cls]
    print(f"# {doc} | {cls}      錨(BS 合計)= {anchor:,} 仟元")
    print()
    print("把下面來源頁裡的表格逐列抄成 JSON,寫到 work/current.json,然後跑")
    print("    python3 fill.py submit work/current.json")
    print()
    print(RULES)
    print()
    print("## 自己先對一次(對得上就不必來回一輪)")
    print(f"每份 record:sum(每列的 total_col 那一欄) == printed_total,"
          f"且 printed_total == {anchor:,}")
    print()
    print("## 來源頁")
    print(transcribe.context_pages(loc, cls, pages))
    print()
    print("下一步:讀完上面的表格,寫 work/current.json,再跑 "
          "python3 fill.py submit work/current.json")


def cmd_next():
    if os.path.exists(PENDING):
        p = json.load(open(PENDING, encoding="utf-8"))
        loc = locate.locate(f"pdf_cache/{p['doc']}.pdf")
        print(f"(這一格上一輪還沒交,重印同一份工單)")
        _render(p["doc"], p["cls"], loc, p["pages"])
        return

    # 空 pdf_cache/ 與「全做完了」在畫面上長得一模一樣,一定要先分開講清楚。
    if not glob.glob("pdf_cache/*.pdf"):
        print("pdf_cache/ 是空的 —— 還沒有 PDF 可抄,不是全部做完了。")
        print("下一步:跑 python3 resolve.py 抓財報 PDF(需要台灣網路環境),"
              "完成後重跑 python3 fill.py next")
        return

    cells = facts.load()
    picked = _pick_next(cells, _rejected_keys())
    if picked is None:
        print("ALL DONE")
        return

    doc, cls, loc = picked
    pages = list(loc.pages[cls])
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump({"doc": doc, "cls": cls, "level": 0, "pages": pages, "retries": 0},
               open(PENDING, "w", encoding="utf-8"))
    _render(doc, cls, loc, pages)


def cmd_submit(path):
    if not os.path.exists(PENDING):
        print("沒有正在抄的格子(work/pending.json 不存在)。")
        print("下一步:python3 fill.py next")
        raise SystemExit(1)

    p = json.load(open(PENDING, encoding="utf-8"))
    doc, cls, level, pages, retries = p["doc"], p["cls"], p["level"], p["pages"], p["retries"]

    data = json.load(open(path, encoding="utf-8"))
    recs = data.get("records") or []
    for r in recs:
        r.setdefault("doc", doc)
        r.setdefault("class", cls)

    loc = locate.locate(f"pdf_cache/{doc}.pdf")

    ok, reason, res, problems = False, "抄不出來(records 為空)", {}, None
    if recs:
        problems = facts.validate({_key(doc, cls): recs})
        if problems:
            reason = "; ".join(problems)
        else:
            ok, res = transcribe.verify(recs, loc)
            if not ok:
                reason = "; ".join(f"{k}:{v}" for k, v in res.items() if v)

    if ok:
        cells = facts.load()
        for r in recs:
            # 稽核欄位,不是事實 —— wide / buckets / verify 一律不准讀它(facts.py 已把
            # 它列為已知選填欄位,不會被 T1 的「未知欄位」檢查擋下來)。
            r["_by"] = {"at": _now(), "retries": retries, "level": level, "via": "claude-code"}
        cells[_key(doc, cls)] = recs
        facts.save(cells)
        os.remove(PENDING)
        print(f"PASS      已歸檔進 facts/{doc}.json({cls})。")
        print("下一步:python3 fill.py next")
        return

    # 擴頁前先問:這是不是「擴頁永遠修不好」的那一種?
    gap = _taxonomy_gap(recs, loc) if recs and not problems else None
    if gap:
        os.makedirs(BLOCKED_DIR, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": reason, "level": level,
                   "proposals": gap, "submitted": data},
                  open(f"{BLOCKED_DIR}/{doc}__{cls}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        seen = set()
        if os.path.exists(PROPOSALS):
            seen = {json.loads(l)["name"] for l in open(PROPOSALS, encoding="utf-8") if l.strip()}
        with open(PROPOSALS, "a", encoding="utf-8") as f:
            for g in gap:
                if g["name"] not in seen:
                    seen.add(g["name"])
                    f.write(json.dumps({**g, "key": _key(doc, cls), "at": _now()},
                                       ensure_ascii=False) + "\n")
        os.remove(PENDING)
        print(f"BLOCKED   這格卡在**分類表缺口**,不是你抄錯 —— 擴頁修不好這種失敗,所以不擴了。")
        for g in gap:
            print(f"          未收錄:「{g['name']}」→ 建議「{g['bucket']}」({g['why']})")
        print(f"          提案已寫入 {PROPOSALS},請使用者審核後收錄進 buckets.SYN,")
        print(f"          再跑 python3 fill.py requeue 把這格放回佇列。")
        print("下一步:python3 fill.py next(先做別格,不要停在這裡)")
        return

    level += 1
    more = loc.expand(cls, level) if level <= pipeline.MAX_LEVEL else []
    new_pages = sorted(set(pages) | set(more))

    if level > pipeline.MAX_LEVEL or not more or new_pages == pages:
        os.makedirs(REJECTED_DIR, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": reason, "level": level - 1,
                   "submitted": data},
                  open(_rejected_path(doc, cls), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        os.remove(PENDING)
        print(f"REJECT    擴張到上限仍對不上,已進 work/rejected/{doc}__{cls}.json。")
        print(f"          理由:{reason}")
        print("下一步:python3 fill.py next")
        return

    json.dump({"doc": doc, "cls": cls, "level": level, "pages": new_pages,
               "retries": retries + 1},
              open(PENDING, "w", encoding="utf-8"))
    added = sorted(set(new_pages) - set(pages))
    print(f"RETRY     沒過:{reason}")
    print(f"          已擴張加入鄰頁 {added}。")
    print("下一步:重讀下面的頁再抄一次,寫回 work/current.json,"
          "再跑 python3 fill.py submit work/current.json(不要跳過,不要回 next)")
    print()
    _render(doc, cls, loc, new_pages)


def cmd_requeue():
    """把 BLOCKED / REJECT 的格子放回待抄佇列 —— 分類表更新後用。

    只刪標記檔,不動 `facts/`:那些格子從來沒被歸檔過,重跑一次是乾淨的。
    """
    n = 0
    for d, label in ((BLOCKED_DIR, "分類表缺口"), (REJECTED_DIR, "拒收")):
        for p in glob.glob(f"{d}/*.json"):
            print(f"  放回({label}):{os.path.basename(p)[:-5]}")
            os.remove(p)
            n += 1
    print(f"{n} 格放回佇列。" if n else "沒有可放回的格子。")
    print("下一步:python3 fill.py next")


def cmd_status():
    cells = facts.load()
    rejected = _marked_keys(REJECTED_DIR)
    blocked = _marked_keys(BLOCKED_DIR)
    total = 0
    for doc in _all_docs():
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        total += sum(1 for _, _, pages in loc.cells() if pages)
    todo = max(total - len(cells) - len(rejected) - len(blocked), 0)
    print(f"已完成 {len(cells)} / 待抄 {todo} / 分類表缺口 {len(blocked)} / 人審佇列 {len(rejected)}")
    if blocked:
        print(f"  ⚠ {len(blocked)} 格卡在分類表缺口 —— 審核 {PROPOSALS} 收錄後跑 "
              f"python3 fill.py requeue")


def _main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("next", "submit", "status", "requeue"):
        print("用法: python3 fill.py next | submit <path> | status | requeue")
        return 2
    cmd = sys.argv[1]
    if cmd == "next":
        cmd_next()
    elif cmd == "status":
        cmd_status()
    elif cmd == "requeue":
        cmd_requeue()
    else:
        if len(sys.argv) < 3:
            print("用法: python3 fill.py submit <path>")
            return 2
        cmd_submit(sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
