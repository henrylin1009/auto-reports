# -*- coding: utf-8 -*-
"""agent 面向的抄列 CLI。三個指令,每個都以「下一步做什麼」收尾 —— agent 不必推理流程。

    python3 fill.py next               印出一格待抄的候選頁,或明確的下一步指示
    python3 fill.py submit <path>      驗收剛寫好的 rows,PASS / RETRY / REJECT 三選一
    python3 fill.py status             已完成 / 待抄 / 人審佇列 三行
    python3 fill.py revalidate         用現在的推導/驗收邏輯重跑 rejected/blocked 既有的
                                        submitted.records,不呼叫模型(邏輯改版後撿現成的)

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
import section
import transcribe
from core import derive

WORK_DIR = "work"
PENDING = f"{WORK_DIR}/pending.json"
REJECTED_DIR = f"{WORK_DIR}/rejected"
BLOCKED_DIR = f"{WORK_DIR}/blocked"
PROPOSALS = f"{WORK_DIR}/proposals.jsonl"
INDEX = f"{WORK_DIR}/index.json"
#: 重抄前的舊版快照(`plan_web_usable.md` P3)。不進版控——git 才是最終稽核
#: 軌跡,這裡只是給「還沒 commit 就手滑重抄」一個救回來的機會。
HISTORY_DIR = f"{WORK_DIR}/history"

#: 系統推導的欄位(`core/derive.py`,`docs/plan_schema_derive.md` D1)——
#: **不跟模型要**,填了也會被推導層整個覆蓋。原因:213 份既有 record 實測
#: 「哪一欄的列和 == 錨」全部唯一命中,系統自己算比問模型準
#: (25 格拒收裡 22 格死在這兩個欄位上,模型在它真正的工作——名字、金額——
#: 幾乎不出錯)。跟模型要的欄位清單見 `MODEL_REQUIRED_REC`。
#:
#: `source_page` 不在這裡:一格常有 2+ 個候選頁(實測 49/82 格 candidate pages ≥ 2,
#: `pdf_cache/*.pdf` 抽樣),同一格的「附註」與「明細表」兩份 record 可能落在不同
#: 候選頁 —— 系統知道候選頁**集合**,不知道某一份 record 具體是哪一頁,這件事
#: 仍然只有讀得懂那幾頁的人/模型能回答。
DERIVED_FIELDS = ("total_col", "printed_total")
#: 跟模型要的必要欄位——`facts.REQUIRED_REC` 減去系統自己填的(`doc`/`class`
#: 由本檔的 `_key()` 呼叫端補、`total_col`/`printed_total` 由推導層補)。
MODEL_REQUIRED_REC = tuple(
    f for f in facts.REQUIRED_REC if f not in ("doc", "class") + DERIVED_FIELDS)

RULES = """## 事實層規矩(違反會被退回)
- name 存表上印的原名 —— 不正規化、不翻譯、不分桶、不改錯字
- cols 的 key 存原欄名(「取得成本」「公允價值總額」「帳面金額」…)
- **缺的欄一律不放 key,不准補 0**(不分是不是合計欄)——未揭露與 0 是不同的
  事實。絕大多數缺欄根本不是零,是「這一列本來就沒有那個欄位」(衍生工具無
  取得成本、股票無面額),補 0 會製造假資料。**哪一欄是合計欄由系統事後推導,
  推導出來之後系統會自己把那一欄缺的值補成 0**(因為那一欄的列和已經被錨
  確認過)——你不必先猜哪一欄是合計欄再決定要不要補 0,一律不補就對了。
- 小計 / 合計不是資料列,不進 rows
- **只抄當期那一欄,比較年度欄不要抄。** 它唯一的用途是跨期對帳,而那條路
  已經不做了(使用者裁示,2026-07-31:人工複核台就是承重牆)。少抄一欄有兩個
  實際好處,不只是省事:要抄的數字少一半 → 抄錯的機會少一半;`total_col` 的
  候選欄變少 → 少掉「≥2 個欄命中」的歧義(202502_5847 那格當初就是選到
  比較欄「113年12月31日」而不是當期欄)。
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
- 抄不出來就寫 {"records": []}。不要猜 —— 猜錯比空白糟糕得多

## 一段一份 record,每份填 record_total(最重要的一條)
給你的是**一整個附註章節**,裡面常常不只一張表:主表印大類(權益工具 / 債務工具),
子附註 (一)(二) 各印一類的明細;或同一頁有「指定 / 強制 / 衍生」三段各有小計。

**每一個有自己印出合計(或小計)的段,各輸出一份 record**,並在該份填
`record_total` = **那一段自己印出來的那個數字**。

  ✓ 主表 record_total = 章節總合計;子附註 record_total = 該子附註自己的合計
  ✗ 不要把子附註的列硬塞進主表那一份,湊成一份大的
  ✗ 不要每份都填章節總合計 —— 填該段**自己印的**那個數

⚠️ **章節最外層的總計常常是光禿禿一行金額,沒有「合計」二字**(例如
`小 計 22,708,892` / `小 計 281,909,396` 之後單獨一行 `$ 304,618,288`)。
它仍然是一份 record:rows 就是那幾個段小計,`record_total` 就是那個總數。
漏掉它,底下的段就沒有東西可以掛,整格會被判「沒有任何一份的合計 == 錨」。
(玉山 202102 p24 的合計列同樣是 `$ 292,943,799` 光禿禿一行 —— 不是特例。)

為什麼:系統事後用金額把子附註掛回主表的哪一列(主表「債務工具投資
292,943,799」== 子附註(二)的合計 → 掛上去)。**沒有 record_total 就掛不上**,
每一份都會被判成「逐列相加不等於錨」而整格退回 —— 實測 4 格卡在這裡,
內容其實全對。

## printed_totals(選填,常見漏填的地方)
- **逐欄**的合計,不是總計。key 必須是 cols 裡出現過的**欄名**
  ✓ {"取得成本": 44631513}      ← 「取得成本」是欄名,rows 的 cols 裡有
  ✗ {"小計": 686764055}         ← 「小計」不是欄名,是表上的中間小計
  ✗ {"113年12月31日小計": ...}  ← 同上
  **表上的中間小計(例如備抵損失前的『小計』)不要放這裡。**
  沒有逐欄合計就**整個省略** —— 省略是誠實的「不適用」,填錯會變成失敗。
  ⚠️ 這是**獨立驗證**:系統不會用它來反推,你填的值要是自己讀出來的合計,
  不是自己算出來的 —— 算的話這道檢查就沒有意義了(它是明細表成本欄
  唯一驗得到的來源)。

## 格式
{"records": [{"source_page": 31, "source_kind": "附註", "record_total": 316073868,
  "printed_totals": {"取得成本": ...},
  "rows": [{"name": "公司債", "group": "有價證券", "cols": {"取得成本": ..., "公允價值總額": ...}}]}]}

## total_col / printed_total 不要填
**這兩個欄位系統會自己算,你不必填,填了也會被覆蓋。**
（`total_col` = 哪一欄的列和等於錨,`printed_total` = 錨本身——兩者都是
系統已經知道或推導得出來的東西,問模型只會多一個出錯的地方。）
你只要專心把 rows 抄對:名字、當期金額、group。"""


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


def unit_pages(loc, cls, level):
    """→ `locate.Located.expand`(2026-07-31 起回傳的是第 `level` 個附註章節)。
    留一層別名是因為 `fill` 是 agent 面向的入口,「工單怎麼取頁」屬於這支的敘事。"""
    return loc.expand(cls, level)


#: **`_taxonomy_gap()` 已於 2026-07-31 移除。** 它整支的存在理由是「⑤ 分桶失敗會
#: 擋住歸檔,所以要分辨這次失敗擴頁救不救得回來」。⑤ 移到發布閘之後,分桶未知
#: 不再擋歸檔 —— 那個問題連同它的答案一起消失了。
#:
#: 分桶未知現在走 `core.ingest` 的 **FILED** 出口:照樣寫進 `facts/`,同時把
#: 未定的列丟進 `review/queue.jsonl` 等人審(實測:1 列未知 → facts 有寫、
#: 佇列 1 筆)。**保護沒有變弱,只是從「擋住」變成「記下來」** ——
#: `core/publish_gate.py` 仍然擋著發布(未知列 ⇒ `wide.View.ok` 為 False)。
#:
#: `work/blocked/` 的**讀取端**刻意留著(`core/queue.py`、`core/webdata.py`):
#: 目錄裡還有舊機制留下的檔,刪掉讀取端會讓它們變成沒有人看得到的孤兒。
#: 寫入端已經沒有任何呼叫點,那個目錄只會變空,不會再長大。


def _pdf_signature():
    """偵測 pdf_cache/ 有沒有變動(新增/刪除/換檔)—— 不比對內容,比 mtime 夠了。"""
    return sorted((os.path.basename(p), int(os.path.getmtime(p)))
                  for p in glob.glob("pdf_cache/*.pdf"))


def _build_index():
    """對每份 PDF 跑一次 locate(),快取「哪個類別有候選頁」。這是唯一的 O(n) 全掃,
    之後 next() 只查表,只對選中的那一格重新 locate() 一次(要拿頁文字)。"""
    sig = _pdf_signature()
    cells, basis = {}, {}
    for doc in _all_docs():
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        # 有沒有東西可抄 = 切不切得出附註章節(明細表落不進編號章節,自動排除)
        cells[doc] = {cls: bool(section.units(loc, cls)) for cls, _, _ in loc.cells()}
        # 口徑順便一起判:這裡本來就要讀完整份的頁文字,再開一次檔純屬浪費。
        basis[doc] = loc.basis
    idx = {"sig": sig, "cells": cells, "basis": basis}
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump(idx, open(INDEX, "w", encoding="utf-8"))
    return idx


def basis_map():
    """`{doc: 個體/合併/?}` —— **唯一該問「這份報表是什麼口徑」的地方。**

    值是 `locate.basis_of()` 從**封面**判出來的,建索引時順便算好存進快取。
    任何地方要判口徑都走這裡,不准自己看 doc 名字裡的 AI 編號:抓檔一律存成
    `_AI3`,合併的舊檔叫 `_AI1`,編號各家各年不一、早就不帶意義
    (`core/webdata.py:203`、`resolve.py` 檔頭)。
    """
    return _load_index().get("basis") or {}


def _load_index():
    sig = _pdf_signature()
    if os.path.exists(INDEX):
        idx = json.load(open(INDEX, encoding="utf-8"))
        # `basis` 是後加的欄位。簽章相同但缺這欄 = 舊版快取,要重建 ——
        # 否則下游拿到的是「所有文件口徑未知」,而那看起來跟真的判不出來一樣。
        if [tuple(x) for x in idx.get("sig", [])] == sig and "basis" in idx:
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
    print(f"把每一欄各自加總,應該有一欄的和等於錨 {anchor:,}"
          f"(哪一欄是合計欄不必你判斷,系統事後會自己挑)。"
          f"沒有任何一欄對得上,通常是漏抄了一列或抄錯一個數字。")
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
    pages = unit_pages(loc, cls, 0)
    os.makedirs(WORK_DIR, exist_ok=True)
    json.dump({"doc": doc, "cls": cls, "level": 0, "pages": pages, "retries": 0},
               open(PENDING, "w", encoding="utf-8"))
    _render(doc, cls, loc, pages)


def _attempt(doc, cls, loc, recs, log=print):
    """驗收核心:推導 → 分類 → 六道,doc/cls/loc/recs 就位後不必問模型。

    跟 `cmd_submit` 拆開是因為 `cmd_revalidate` 要對 `work/rejected/*.json`
    裡**已經存在**的 `submitted.records` 重跑同一套(pipeline 換版後常有格子
    當初卡住,現在其實過得了),那條路徑不經過 `work/pending.json`、不必問模型,
    走一樣的驗收邏輯即可,不該複製一份。

    回傳 (ok, reason, recs, hard)——`recs` 是通過推導後的版本(ok 時才有效,
    已補好 total_col/printed_total,可以直接寫進 facts/)。`hard` 區分兩種
    「沒過」:推導/分類失敗(`hard=True`,列本身有問題,`_taxonomy_gap` 不該
    模擬)vs 六道核對失敗(`hard=False`,才輪到判斷是不是分類表缺口)——
    跟 `cmd_submit` 原本 `problems`/`reason` 分開判斷是同一件事,搬進這支
    共用函式後用 `hard` 明講,不靠「problems 是不是 None」猜。
    """
    # 推導層(`docs/plan_schema_derive.md` D1)——`total_col` / `printed_total` /
    # 破折號列一律系統算,不問模型。**推導失敗直接算「沒過」,不進 facts.validate
    # 也不進 _taxonomy_gap**:0 個欄命中代表列本身抄錯了,那不是分類問題,
    # 硬塞進分桶模擬只會產生一個查不到根因的假警報。
    #
    # 2026-08-12:這一整段搬進 `core.derive.prepare()` —— **自動路徑
    # (`core.ingest.classify_outcome`)整段沒有這一步**,導致自動抄列每一格
    # 必然失敗。收成一份、兩邊都呼叫,見 `prepare()` 的說明。
    recs, derive_err = derive.prepare(recs, loc, cls, log=log)
    if derive_err:
        return False, derive_err, recs, True

    problems = facts.validate({_key(doc, cls): recs})
    if problems:
        return False, "; ".join(problems), recs, True

    ok, res = transcribe.verify(recs, loc)
    if not ok:
        return False, "; ".join(f"{k}:{v}" for k, v in res.items() if v), recs, False
    return True, None, recs, False


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
    ok, reason, recs, hard = _attempt(doc, cls, loc, recs)
    problems = [reason] if (reason and hard) else None

    if ok:
        cells = facts.load()
        key = _key(doc, cls)
        old = cells.get(key)
        if old:
            # 重抄整格覆蓋(見下面 `cells[key] = recs`)——如果這格本來就有內容
            # (包含人工列,`row._src` 不是機器抄的),覆蓋前先留一份快照。
            # git log 是最終稽核軌跡沒錯,但那要求「先 commit」;這裡是給
            # 還沒 commit 就手滑重抄的那個當下一個救回來的機會(plan_web_usable.md P3)。
            os.makedirs(HISTORY_DIR, exist_ok=True)
            snap = f"{HISTORY_DIR}/{doc}__{cls}__{_now().replace(':', '')}.json"
            json.dump(old, open(snap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for r in recs:
            # 稽核欄位,不是事實 —— wide / buckets / verify 一律不准讀它(facts.py 已把
            # 它列為已知選填欄位,不會被 T1 的「未知欄位」檢查擋下來)。
            # `via`/`at` 由 `file_cell()` 補上,這裡只放它不知道的 retries/level。
            r["_by"] = {"retries": retries, "level": level}
        # **走 `webdata.file_cell()`,不自己 `facts.save()`。** 那是機器寫進事實庫的
        # 唯一一道門,帶著 append-only 保護:人工裁示過的格(帶 `_src`)機器不准覆蓋。
        # 上面那份快照留著 —— 快照是「手滑救回」,守衛是「根本不讓它發生」,兩件事。
        # (webdata 在模組層 import fill,所以這裡只能區域 import,不能提到檔頭。)
        from core import webdata as _webdata
        try:
            _webdata.file_cell(doc, cls, recs, via="claude-code")
        except _webdata.EditError as e:
            print(f"REJECT    {e}")
            return
        os.remove(PENDING)
        print(f"PASS      已歸檔進 facts/{doc}.json({cls})。")
        print("下一步:python3 fill.py next")
        return

    # 存的是 `recs`,不是原始 `data` —— 推導成功時 `recs` 已經是補好
    # total_col/printed_total 的版本,人工裁示台(`core/webdata.ratify`)
    # 打開這格才不必再手動點一次欄位選擇器。推導失敗時兩者相同(沒被覆寫)。
    submitted_out = {"records": recs}

    level += 1
    new_pages = unit_pages(loc, cls, level)

    if not new_pages or new_pages == pages:
        os.makedirs(REJECTED_DIR, exist_ok=True)
        json.dump({"doc": doc, "cls": cls, "reason": reason, "level": level - 1,
                   "submitted": submitted_out},
                  open(_rejected_path(doc, cls), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        os.remove(PENDING)
        print(f"REJECT    章節都試過了仍對不上,已進 work/rejected/{doc}__{cls}.json。")
        print(f"          理由:{reason}")
        print("下一步:python3 fill.py next")
        return

    json.dump({"doc": doc, "cls": cls, "level": level, "pages": new_pages,
               "retries": retries + 1},
              open(PENDING, "w", encoding="utf-8"))
    print(f"RETRY     沒過:{reason}")
    print(f"          換下一個章節試(頁 {[i + 1 for i in new_pages]})。")
    print("下一步:重讀下面的頁再抄一次,寫回 work/current.json,"
          "再跑 python3 fill.py submit work/current.json(不要跳過,不要回 next)")
    print()
    _render(doc, cls, loc, new_pages)


def cmd_revalidate():
    """把 `work/rejected/` 與 `work/blocked/` 裡已經存過的 `submitted.records`
    拿現在的推導/驗收邏輯重跑一次,**不呼叫模型**——過了就直接歸檔,標記檔刪掉。

    存在的理由:`core/derive.py` 這類推導/驗收邏輯改版後,舊的拒收檔案不會
    自動重新受益,得靠人手動一格一格「退回重抄」才會重跑,而重抄會重新
    燒一次 LLM。但 `submitted.records` 早就存在檔裡了 —— 邏輯改版當下能不能
    通過,重驗一次(純計算,不必問模型)就知道,不必浪費一次模型呼叫去問
    「這次還一樣嗎」。

    仍然過不了的**不是原樣留著**,而是把 `reason` 與 `submitted.records`
    一起更新成這次重驗的結果。理由是使用者實測抓到的(2026-07-31,
    `202502_玉山_個體|Trading`):舊 reason 是舊管線寫的字串,裡面
    `total_col` 指著錯的欄(「113年12月31日」)、`printed_total` 是那一欄的
    和(275,226,180)、頁碼還是 0-based(`@p22`)—— 但推導層現在自己就選對了
    (「114年6月30日」= 錨 252,890,908),複核台的欄位選擇器也早就打勾在對的
    那一欄。**畫面上「已經是對的」與紅字「卡在欄位」互相矛盾,而矛盾的那一半
    是死掉的字串**,人會照著紅字去找一個根本不存在的問題。

    """
    n_pass, n_stay, n_fresh = 0, 0, 0
    # 兩個目錄都掃:`blocked/` 的寫入端已經退場,但舊檔還在,重驗一樣要撿。
    paths = [p for d in (REJECTED_DIR, BLOCKED_DIR)
             for p in sorted(glob.glob(f"{d}/*.json"))]
    for path in paths:
        data = json.load(open(path, encoding="utf-8"))
        doc, cls = data["doc"], data["cls"]
        key = _key(doc, cls)
        recs = list(data.get("submitted", {}).get("records") or [])
        for r in recs:
            r.setdefault("doc", doc)
            r.setdefault("class", cls)
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        ok, reason, derived, hard = _attempt(
            doc, cls, loc, recs, log=lambda s: print(f"  {key}{s}"))
        if ok:
            for r in derived:
                r["_by"] = {"retries": data.get("level", 0),
                            "level": data.get("level", 0)}
            from core import webdata as _webdata      # 同上,循環 import
            try:
                _webdata.file_cell(doc, cls, derived, via="revalidate")
            except _webdata.EditError as e:
                n_stay += 1
                print(f"SKIP      {key} {e}")
                continue
            os.remove(path)
            n_pass += 1
            print(f"PASS      {key} 重驗通過,已歸檔進 facts/{doc}.json({cls})。")
            continue

        n_stay += 1
        # 還是沒過。把這次真正的失敗理由寫回去蓋掉舊的 —— `derived` 是推導
        # 過的版本(total_col/printed_total 已經是系統選的),複核台打開這格
        # 看到的就跟重驗看到的是同一件事。
        stale = (data.get("reason") or "") != (reason or "")
        data["reason"] = reason
        data["submitted"] = {"records": derived}
        # 仍然沒過的一律留在 `rejected/` —— 分類表缺口那條分支已經沒有了。
        data.pop("proposals", None)
        new_path = f"{REJECTED_DIR}/{doc}__{cls}.json"
        os.makedirs(REJECTED_DIR, exist_ok=True)
        json.dump(data, open(new_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        if new_path != path:
            os.remove(path)
            print(f"MOVED     {key} → rejected/(舊 blocked 檔已改路由)")
        if stale:
            n_fresh += 1
            print(f"STALE     {key} 舊理由已過時,換成這次重驗的:")
            print(f"          {reason}")

    print(f"{n_pass} 格重驗通過並歸檔,{n_stay} 格仍未過"
          f"(其中 {n_fresh} 格的理由是過時的,已更新)。")
    if n_pass or n_fresh:
        print("下一步:python3 fill.py status 確認進度")


def cmd_requeue():
    """把 BLOCKED / REJECT 的格子放回待抄佇列 —— 分類表更新後用。

    只刪標記檔,不動 `facts/`:那些格子從來沒被歸檔過,重跑一次是乾淨的。
    """
    n = 0
    for d, label in ((BLOCKED_DIR, "舊 blocked 殘留"), (REJECTED_DIR, "拒收")):
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
        total += sum(1 for cls, _, _ in loc.cells() if section.units(loc, cls))
    todo = max(total - len(cells) - len(rejected) - len(blocked), 0)
    print(f"已完成 {len(cells)} / 待抄 {todo} / 舊 blocked 殘留 {len(blocked)} / 人審佇列 {len(rejected)}")
    if blocked:
        print(f"  ⚠ {len(blocked)} 格是舊分類表缺口機制留下的 —— 跑 "
              f"python3 fill.py revalidate 重驗(多半現在就過得了)")


def _main():
    if len(sys.argv) < 2 or sys.argv[1] not in (
            "next", "submit", "status", "requeue", "revalidate"):
        print("用法: python3 fill.py next | submit <path> | status | requeue | revalidate")
        return 2
    cmd = sys.argv[1]
    if cmd == "next":
        cmd_next()
    elif cmd == "status":
        cmd_status()
    elif cmd == "requeue":
        cmd_requeue()
    elif cmd == "revalidate":
        cmd_revalidate()
    else:
        if len(sys.argv) < 3:
            print("用法: python3 fill.py submit <path>")
            return 2
        cmd_submit(sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
