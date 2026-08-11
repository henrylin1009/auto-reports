# -*- coding: utf-8 -*-
"""複核台的**資料層**:純函式,不碰 HTTP、不碰任何 UI 框架。

`server.py` 只負責把這裡的回傳值轉成 JSON。這樣切的理由不是潔癖 ——
UI 換過兩次了(Streamlit → 自刻網站),每換一次都重寫一遍取數邏輯,
就是每換一次都要重驗一遍「35 已抄 / 90 可抄」對不對。

⚠️ **`source_page` 存的是 0-based**,與 `locate.Located.pages` 的候選頁
直接對應,不是印在紙上的頁碼。這點踩過一次(抄列模板 +1、核對讀值 -1,
兩邊都錯),所以在這裡集中處理,呼叫端一律不要自己加減。
"""
import datetime
import glob
import json
import os

import buckets
import config
import facts as facts_mod
import fill
import locate
import transcribe
from core import acquire
from core import derive
from core import queue as queue_mod

#: 只做 2023+。≤2022 那些四大表被掃成影像、文字層沒有科目代碼,定位不到,
#: 且已裁示不在範圍內(docs/plan_ui_redesign.md §一裁示①)。
CUTOFF_YEAR = 2023


def docs_in_scope():
    return sorted(d for d in fill._all_docs() if int(d[:4]) >= CUTOFF_YEAR)


def split_doc(doc):
    """`202504_5847_AI3` → (`202504`, `5847`, `AI3`)。"""
    period, bank, code = doc.split("_")
    return period, bank, code


def _marked_keys(work_dir):
    """`{doc}__{cls}.json` 檔名 → `{"doc|cls", ...}`。`overview()` 與 `doc_detail()`
    共用同一份轉換,避免兩處各自 glob 一次卻算出不一致的鍵集合。"""
    return {os.path.basename(p)[:-5].replace("__", "|")
            for p in glob.glob(f"{work_dir}/*.json")}


#: 格層級的人工裁示(`plan_web_complete.md` W3)——**跟 `facts/` 分開存**,
#: 因為它管的不是「這一格抄了什麼」,是「這一格該怎麼抄 / 要不要抄」,
#: 概念上更接近 `work/blocked/`、`work/rejected/` 那一層,不是事實本身。
CELLMETA_PATH = "work/cellmeta.json"


def load_cellmeta(path=None):
    """→ `{"doc|cls": {field: {"value","by","at","why"}, ...}, ...}`。

    公開函式(不是 `_load_xxx`)——`overview()`/`doc_detail()`/`server.py` 的
    背景抄列都要讀它,不是只有本模組內部用。
    """
    p = path or CELLMETA_PATH
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8"))


class EditError(ValueError):
    """裁示類函式共用的錯誤——訊息直接給使用者看,不要外洩 traceback。
    `edit_row()` 也拋這個,兩者是同一種「人工裁示格式不對」。"""


def set_cellmeta(doc, cls, field, value, why, by=None, today=None, path=None):
    """人工對「一格」(不是一列)下的裁示,`why` 必填——跟 `edit_row()` 同一個
    模式:沒有理由的覆寫跟沒有覆寫一樣危險。

    `field`:
      "pages"   → value = 頁碼清單(0-based,與 facts 的 source_page 同制)。
                  解掉兩種卡住:①錨有但候選頁是空的(grep 找不到,今天 2 格)
                  ②候選頁都在,但模型抄到彙總層不是明細層(今天 ~15 筆,
                  例如 202502_5836_AI3 OCI 那個「透過…權益/債務工具投資」
                  小計)。設完之後照舊點「重抄」,`fill_auto.run_key()` 會
                  自動吃到這個覆寫(見該函式的 `cellmeta` 參數)。
      "no_data" → value = true。**不是「還沒抄」**,是人已經翻過原始頁面、
                  確認這份文件真的沒有這項揭露。

    `path` 只給測試用(注入 tmp 檔案)。
    """
    if field not in ("pages", "no_data"):
        raise EditError(f"不認得的 cellmeta 欄位:{field!r}(只有 pages / no_data)")
    if not why or not why.strip():
        raise EditError("一定要填理由(why)——這是唯一的品質控制,不能空白。")
    if field == "pages":
        if (not isinstance(value, list) or not value
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
            raise EditError("pages 要是非空的頁碼(整數)清單。")
        if doc is not None:
            # 上界檢查——沒這一道,實測存進超出範圍的頁碼會回 {"saved": true},
            # 圖裂在後面(/page.png)才炸,使用者看到的是裂圖,不是「頁碼錯」。
            n = _pdf_page_count(doc)
            if n is not None and any(v < 0 or v >= n for v in value):
                raise EditError(f"頁碼超出範圍——{doc}.pdf 共 {n} 頁"
                                 f"(可用 0 到 {n - 1})。")

    p = path or CELLMETA_PATH
    meta = load_cellmeta(p)
    key = f"{doc}|{cls}"
    meta.setdefault(key, {})[field] = {
        "value": value, "by": by or "henrylin",
        "at": today or datetime.datetime.now().isoformat(timespec="seconds"),
        "why": why.strip(),
    }
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    json.dump(meta, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    return {"saved": True}


def _pdf_page_count(doc):
    """`loc.texts` 已經是全文,長度就是頁數——不必另開 pdfium,`locate()` 本來就
    有快取(`locate.py:168`),這裡是白吃的午餐。檔案不在就回 None,呼叫端跳過檢查
    而不是報錯——「PDF 不見」是另一個問題,不該借這支函式的名義冒出來。"""
    path = f"pdf_cache/{doc}.pdf"
    if not os.path.exists(path):
        return None
    return len(locate.locate(path).texts)


def clear_cellmeta(doc, cls, field, path=None):
    """撤銷一個 cellmeta 裁示。不強制填理由——撤銷不是新判斷,是承認上一個
    判斷是錯的,git log(或這次 HTTP 呼叫本身)已經留著原本那筆的紀錄。"""
    p = path or CELLMETA_PATH
    meta = load_cellmeta(p)
    key = f"{doc}|{cls}"
    if key in meta and field in meta[key]:
        del meta[key][field]
        if not meta[key]:
            del meta[key]
        json.dump(meta, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        return {"cleared": True}
    return {"cleared": False}


def effective_pages(loc, doc, cls, cellmeta):
    """`loc.pages[cls]` 的手動覆寫版。覆寫優先,沒有就退回原本的候選頁
    (`loc.pages.get(cls, [])`——用 `.get` 不用 `[cls]`,因為 `na` 的格子
    可能根本沒有這個 key)。"""
    entry = (cellmeta.get(f"{doc}|{cls}") or {}).get("pages")
    if entry:
        return entry["value"]
    return loc.pages.get(cls, [])


def cell_status(cells, blocked_keys, rejected_keys, index, doc, cls, cellmeta=None):
    """一格(文件 × 類別)的六種狀態。`na` = 錨讀不到或無候選頁;2023+ 的基準
    是 0,但欄位仍保留 —— 假設會過期,沉默地跳過比顯示 `na` 危險。

    ⚠️ **`rejected` 曾經跟 `todo`長得一模一樣**(2026-07-30 修):`work/rejected/`
    的格子過去沒被任何 `cell_status` 分支認出來,所以顯示成「還沒抄」——
    使用者看不出這格其實已經抄過、擴頁到上限、六道還是不過。網頁上因此
    完全沒有路徑可以看理由或退回重抄,只能重新手動貼一次。

    `no_data`(`plan_web_complete.md` W3,2026-07-30 加):**跟「還沒抄」是
    兩件事,必須分得開**——這是人翻過原始頁面後確認「這份文件真的沒有
    這項揭露」,不是排隊等抄。判斷順序放第一位,因為它是人下的最終判斷,
    優先於任何機器算出來的狀態(即使剛好也 `done` 了,那也是矛盾,要人自己
    去解,不該讓機器狀態偷偷贏)。

    `cellmeta` 帶 `pages` 覆寫時,即使 `index` 說候選頁是空的(今天 2 格:
    錨有、grep 找不到頁)也算 `todo`——那正是這個覆寫存在的理由。
    """
    key = f"{doc}|{cls}"
    cellmeta = cellmeta or {}
    if (cellmeta.get(key) or {}).get("no_data"):
        return "no_data"
    if key in cells:
        return "done"
    # 2026-08-02:拿掉了「v4 GREEN/RATIFIED 也算 done」的捷徑 —— 那條路每次
    # 呼叫都要重新對整份 PDF 跑 witness(重抽全部頁面文字,零快取),矩陣一次
    # 90 格 × 3 類最壞情況即被拖到 5 秒;而且 v4 目前完全不進 `build.py` 的
    # 發布路徑,`done`(=已核對、將會發布)在這裡不能代表一格其實發不出去
    # 的資料(docs/plan_v5_統一.md §0.3/§0.4)。v4 何時算「已完成」要等 P1
    # 把它接進發布路徑後再回來決定,不在這裡用查詢期的旁路偷接。
    if key in blocked_keys:
        return "blocked"
    if key in rejected_keys:
        return "rejected"
    if index["cells"].get(doc, {}).get(cls):
        return "todo"
    if (cellmeta.get(key) or {}).get("pages"):
        return "todo"
    return "na"


def overview(basis=None):
    """矩陣:期別(列) × 銀行(欄)。**代碼集合從資料推導,不寫死列舉** ——
    寫死過兩次,兩次都讓某一份檔無聲消失(先漏 AI1、修完又漏 AI2)。

    `basis` = 個體 / 合併,**口徑分開畫兩張表**(使用者 2026-07-29 裁示)。
    兩者的期別本來就不同(個體只有半年報 02 / 年報 04,合併有四季),
    混在同一個網格會長出一整排永遠空著的季報欄。跨行比較只用個體。

    欄名用**銀行代碼**,不再串 AI 編號:`resolve.download()` 一律把檔改名存成
    `_AI3`(resolve.py:37),AI 編號已經不帶意義。口徑改由封面判(`locate.basis_of`)。
    """
    cells = facts_mod.load()
    blocked_keys = set(queue_mod.by_cell())
    rejected_keys = _marked_keys(fill.REJECTED_DIR)
    cellmeta = load_cellmeta()
    index = fill._load_index()
    bmap = index.get("basis") or {}
    basis = basis or locate.SOLO

    docs = [d for d in docs_in_scope() if bmap.get(d) == basis]
    present = set(docs)

    # **列與欄來自日曆規則,不是來自現有檔案。** 原本兩者都由 pdf_cache 反推,
    # 所以新年度那一列根本不會出現,使用者沒有地方可以說「這期我要」。
    # 現有檔案現在只決定每格的狀態,不決定格子存不存在。
    periods = acquire.expected_periods(basis)
    cols = acquire.expected_banks(basis, present)
    # 已經抓到但不在預期清單裡的(例如手動放進來的舊檔)仍要看得到 —— 補進去,
    # 不然它會從畫面上無聲消失,那正是「寫死列舉」踩過兩次的坑。
    for d in docs:
        p, b, _ = split_doc(d)
        if p not in periods:
            periods.append(p)
        if b not in cols:
            cols.append(b)
    periods.sort(reverse=True)
    cols.sort()

    # (期別, 代碼) → 實際檔名。**不准用 `acquire.doc_name()` 組出來的名字反查現有檔**:
    # 那個函式回的一律是 `_AI3`(抓檔存檔用),但合併的舊檔叫 `_AI1`,
    # 組名比對會讓整張合併矩陣變成「一份都沒有」(2026-07-29 實測踩過)。
    by_pos = {(split_doc(d)[0], split_doc(d)[1]): d for d in docs}

    log = acquire.load_log()
    grid = {}
    stats = {"done": 0, "todo": 0, "blocked": 0, "rejected": 0, "no_data": 0, "na": 0}
    fetch_stats = {"missing": 0, "absent": 0, "failed": 0}
    for period in periods:
        for bank in cols:
            doc = by_pos.get((period, bank))
            if doc:
                states = {}
                for cls in locate.CLASSES:
                    s = cell_status(cells, blocked_keys, rejected_keys, index, doc, cls, cellmeta)
                    states[cls] = s
                    stats[s] += 1
                grid[f"{period}|{bank}"] = {"doc": doc, "classes": states,
                                            "fetch": None}
                continue
            st = acquire.cell_fetch_state(period, bank, present, log)
            fetch_stats[st] = fetch_stats.get(st, 0) + 1
            grid[f"{period}|{bank}"] = {"doc": None, "classes": None,
                                        "fetch": st, "period": period, "code": bank}

    avail = sorted({bmap.get(d) for d in docs_in_scope()} - {None, locate.UNKNOWN})
    return {"periods": periods, "cols": cols, "grid": grid, "stats": stats,
            "fetch_stats": fetch_stats, "basis": basis, "bases": avail,
            "can_fetch": basis == locate.SOLO}


def cell_detail(key):
    """一格已抄好的內容,給核對畫面用。每列附上算好的桶,
    `bucket=None` 代表分類表沒收錄(**不准填「其他」頂替** —— 「其他」是
    表上真的存在的科目,拿來當「不知道」的收容所會讓錯誤看起來像正常值)。

    ⚠️ `cols` 現在整包給(2026-07-30 加,`plan_web_complete.md` W2)——舊版
    只給 `total_col` 那一欄的 `value`,可編輯的欄位就只剩一個,沒辦法讓人
    在網頁上改比較年度那幾欄。`value` 仍然保留(舊欄位,舊版前端還在用)。

    `checks`:對這一格**現算** `transcribe.verify()`,不存進 facts —— 存了
    就會跟事實漂移(改一列之後,舊的存檔結果就是假的)。**不阻擋顯示,
    只標黃**:人工列可能永遠過不了機器的六道語意檢查(例如文字層本身壞掉,
    ⑥ 永遠會抓到一個湊不出來的欄位合計),那不是這一列的錯,是機器檢查
    本來就管不到人已經看過原始頁面確認的事實。
    """
    cells = facts_mod.load()
    if key not in cells:
        return None
    doc, cls = key.split("|", 1)
    loc = locate.locate(f"pdf_cache/{doc}.pdf")

    ok, problems = transcribe.verify(cells[key], loc)
    checks = {"ok": ok, "problems": {k: v for k, v in problems.items() if v}}

    records = []
    for ri, rec in enumerate(cells[key]):
        rows = []
        for rj, row in enumerate(rec["rows"]):
            rows.append({
                "row_index": rj,
                "name": row["name"],
                "group": row.get("group") or "",
                "cols": dict(row["cols"]),
                "value": row["cols"].get(rec["total_col"]),
                "bucket": buckets.bucket(row),
                "manual": bool(row.get("_src")),
                "src": row.get("_src"),
            })
        records.append({
            "record_index": ri,
            "source_page": rec["source_page"],      # 0-based
            "source_kind": rec["source_kind"],
            "total_col": rec["total_col"],
            "printed_total": rec["printed_total"],
            "cols": sorted({c for row in rec["rows"] for c in row["cols"]}),
            "rows": rows,
        })

    return {
        "key": key, "doc": doc, "cls": cls,
        "anchor": loc.anchors.get(cls),
        "pages": sorted({r["source_page"] for r in records}),
        "records": records,
        "checks": checks,
    }


def edit_row(doc, cls, record_index, row_index, row, why, by=None, today=None,
            facts_dir=None):
    """人工改 / 增 / 刪一列(`docs/plan_web_complete.md` W2)。

    三種動作看 `row_index`/`row` 的組合:
      · row_index=None, row=給值      → 新增一列(附加到 rows 尾端)
      · row_index=給值,  row=給值      → 改那一列
      · row_index=給值,  row=None      → 刪那一列

    **`why` 是必填,不是格式潔癖**——它是這整個機制唯一的品質控制:
    沒有理由的覆寫跟沒有覆寫一樣危險(`plan_web_complete.md` §6②)。

    `facts.validate()` 的格式檢查(名字非空字串、cols 是 int…)**不因為
    `_src` 而放寬**——那一層是格式衛生,人工列一樣要守。放寬的只有
    `transcribe.verify()` 那一層**語意**檢查:結果算出來附在回傳值裡
    給前端標黃,**不阻擋這次寫入**(fill.cmd_submit 的六道全過閘門只管
    機器抄的路徑,這裡是另一個合法的落地路徑,見 `webdata.py` 檔頭的
    S3 裁示與本函式所屬的 W2 計畫)。

    刪除沒有「這一列」可以掛 `_src` 了——稽核軌跡是 `git diff facts/{doc}.json`
    (與 `buckets.SYN`、`taxonomy` 同一套慣例),`why` 只在這次呼叫裡走一遍,
    不必另外存一份。

    `facts_dir` 只給測試用(注入 tmp 目錄)——production 呼叫一律用預設值。
    """
    if not why or not why.strip():
        raise EditError("一定要填理由(why)——這是唯一的品質控制,不能空白。")
    if row_index is None and row is None:
        raise EditError("row_index 與 row 不能同時是 None(不知道要做哪個動作)。")

    key = f"{doc}|{cls}"
    cells = facts_mod.load(facts_dir)
    if key not in cells:
        raise EditError(f"{key} 還沒有任何事實資料——這格還沒抄過,不能編輯列。")
    recs = cells[key]
    if not 0 <= record_index < len(recs):
        raise EditError(f"record_index {record_index} 超出範圍(這格只有 {len(recs)} 份 record)。")
    rec = recs[record_index]
    rows = rec["rows"]

    stamp = {"by": by or "henrylin",
             "at": today or datetime.datetime.now().isoformat(timespec="seconds"),
             "why": why.strip()}

    if row_index is None:
        new_row = dict(row)
        new_row["_src"] = stamp
        rows.append(new_row)
    elif row is None:
        if not 0 <= row_index < len(rows):
            raise EditError(f"row_index {row_index} 超出範圍(這份 record 只有 {len(rows)} 列)。")
        rows.pop(row_index)
    else:
        if not 0 <= row_index < len(rows):
            raise EditError(f"row_index {row_index} 超出範圍(這份 record 只有 {len(rows)} 列)。")
        new_row = dict(row)
        new_row["_src"] = stamp
        rows[row_index] = new_row

    problems = facts_mod.validate({key: recs})
    if problems:
        raise EditError("格式不合規,沒有寫入:\n" + "\n".join(problems))

    facts_mod.save(cells, facts_dir)

    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    ok, res = transcribe.verify(recs, loc)
    return {"saved": True, "checks": {"ok": ok,
                                      "problems": {k: v for k, v in res.items() if v}}}


def human_ratified(recs):
    """這格**已經被人工裁示過**了嗎 —— 判準是任何一列帶 `_src`。

    `_src` 只有 `ratify()`/`edit_row()` 這些人工出口會蓋(見 `facts.py`
    OPTIONAL_ROW 的說明),機器抄列的路徑一律不蓋。所以它就是「有人動過」
    的唯一標記,不需要另外發明一個狀態欄位。
    """
    return any("_src" in row
               for rec in (recs or [])
               for row in (rec.get("rows") or []))


def revoke(doc, cls, why=None, by=None, facts_dir=None):
    """撤銷一格的人工裁示 —— **顯式操作**,不是任何動作的副作用。

    語意照搬 `v4/ledger.requeue()`:把該格移出事實庫,讓它回到「還沒抄」的
    狀態,之後機器或人都可以重新填。`facts/` 全部在 git 裡(58 檔),所以
    這個移除是可還原的,git log 就是撤銷的稽核軌跡。

    為什麼要有這支:`ratify()` 現在拒絕覆蓋人工裁示過的格(2026-08-10 裁示,
    選項 1)。沒有撤銷口的話,人一旦裁示錯就永遠改不回來 —— 那不是保護,
    是把自己鎖在門外。
    """
    key = f"{doc}|{cls}"
    cells = facts_mod.load(facts_dir)
    if key not in cells:
        return {"revoked": False, "reason": f"{key} 不在事實庫裡"}
    was_human = human_ratified(cells[key])
    facts_mod.remove(key, facts_dir)     # 不能只 del + save,見 facts.remove()
    return {"revoked": True, "was_human_ratified": was_human,
            "why": (why or "").strip() or None, "by": by or "henrylin"}


def ratify(doc, cls, records, why=None, by=None, today=None, facts_dir=None,
           force=False):
    """人工裁示放行一格被拒收的資料(`plan_web_usable.md` P4)。

    **為什麼需要這支**:`fill.cmd_submit` 的六道全過閘門保護了機器抄的品質,
    但它同時把「我看過原始頁面了,雖然某一道對不上,事實就是這樣」變成一句
    在系統裡說不出口的話(`plan_web_complete.md` §1 的根因)。W2 的 `edit_row`
    只解了「已經在 facts/ 裡的列」,被擋在 facts/ 外面的格子仍然是死路。

    實測的兩種假拒收(2026-07-30,202502_5835_AI3):
      · 破折號列 —— Trading 逐列相加 296,338,628 正好 == 錨,唯一的問題是
        `基金受益憑證` 那列在合計欄印的是「—」,閘門①②要求每列都有值
      · total_col 挑錯 —— OCI 的 `114年6月30日` 欄列和 330,763,870 正好 == 錨,
        模型只是把 `total_col` 填成比較期那欄
    兩格的**數字都是對的**,錯的是 schema 的表達方式。

    `_src` 蓋在每一列上、`facts.validate()` 的格式檢查照擋(格式衛生不因人工
    而放寬)、`transcribe.verify()` 的語意檢查**照跑、結果照記、但不阻止歸檔**
    (`plan_web_complete.md` §2 規則 2)。

    ⚠️ `why` **不強制填**(2026-07-30 使用者裁示,推翻 `plan_web_complete.md`
    §6② 原本「why 必填」的決定)——這格拒收的內容(欄位挑選、破折號列)
    本身就是稽核軌跡,逼著每次都打一行字反而會被訓練成隨便填一句話應付,
    跟沒有理由一樣。稽核軌跡改成:`_src.by`/`_src.at` 一定有(標記「有人動過」),
    `why` 有給就存、沒給就是 `None`——git log 加上這格內容本身足夠回答
    「這格為什麼是這樣」。`edit_row()`/`set_cellmeta()` 的 `why` 必填**不受
    影響**,那两支動的是「已經在 facts/ 裡的既有列」,情境不同,沒人要求
    連動放寬。

    放行後清掉 `work/rejected/` 或 `work/blocked/` 的標記檔——不清的話
    `cell_status` 雖然會因為 `done` 優先而顯示正常,標記檔卻會一直躺著,
    等哪天這格被刪掉就會詐屍(P2 已經把這種殘留顯示出來了)。
    """
    if not records:
        raise EditError("沒有任何 record 可以歸檔。")

    key = f"{doc}|{cls}"
    stamp = {"by": by or "henrylin",
             "at": today or datetime.datetime.now().isoformat(timespec="seconds")}
    if why and why.strip():
        stamp["why"] = why.strip()

    recs = json.loads(json.dumps(records))       # 深拷貝,不動呼叫端的物件
    for i, rec in enumerate(recs):
        # 0. 欄位清洗與相容:相容舊模型或 LLM 產出的 record_total,並確保必要欄位存在
        if "record_total" in rec:
            if "printed_total" not in rec or rec["printed_total"] is None:
                rec["printed_total"] = rec["record_total"]
            del rec["record_total"]
        if "total_col" not in rec or not rec["total_col"]:
            # 若無 total_col,預設抓 rows 裡的第一個欄位 key
            cols = [c for r in rec.get("rows", []) for c in r.get("cols", {})]
            rec["total_col"] = cols[0] if cols else "合計"
        if "printed_total" not in rec or rec["printed_total"] is None:
            total_col = rec["total_col"]
            rec["printed_total"] = sum((r.get("cols") or {}).get(total_col, 0) for r in rec.get("rows", []))

        # 破折號列補 0 / 丟掉對不上的 printed_totals——**跟自動路徑共用同一套
        # 推導層**(`core/derive.py`),不是另一套規矩。這裡不呼叫
        # `derive.derive_record()` 整套(那支會**重新發現** total_col,
        # 人工裁示不需要,也不該覆蓋人已經選定的欄)——只借它的兩個子步驟。
        rec = derive.fill_zero_for_col(rec, rec.get("total_col"))
        rec = derive.drop_mismatched_printed_totals(rec)
        recs[i] = rec
        rec.setdefault("doc", doc)
        rec.setdefault("class", cls)
        for row in rec.get("rows") or []:
            row["_src"] = stamp

    problems = facts_mod.validate({key: recs})
    if problems:
        raise EditError("格式不合規,沒有寫入:\n" + "\n".join(problems))

    cells = facts_mod.load(facts_dir)
    if human_ratified(cells.get(key)) and not force:
        raise EditError(
            f"{key} 已經人工裁示過(帶 `_src` 標記),不能直接覆蓋。\n"
            f"  要改請先撤銷:`revoke({doc!r}, {cls!r}, why=...)`,再重新裁示。\n"
            f"  這條是刻意的 —— 見 `human_ratified()` 的說明。")
    cells[key] = recs
    facts_mod.save(cells, facts_dir)

    for d in (fill.REJECTED_DIR, fill.BLOCKED_DIR):
        p = f"{d}/{doc}__{cls}.json"
        if os.path.exists(p):
            os.remove(p)

    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    ok, res = transcribe.verify(recs, loc)
    return {"saved": True, "checks": {"ok": ok,
                                      "problems": {k: v for k, v in res.items() if v}}}


def todo_cells():
    """還沒抄、且有候選頁可抄的格。排序沿用 `fill._doc_sort_key`
    (2023+ 優先、年報優先),讓網站的順序與 `fill.py next` 一致。"""
    cells = facts_mod.load()
    rejected = fill._rejected_keys()
    index = fill._load_index()
    out = []
    for doc in sorted(docs_in_scope(), key=fill._doc_sort_key):
        for cls in locate.CLASSES:
            key = f"{doc}|{cls}"
            if key in cells or key in rejected:
                continue
            if index["cells"].get(doc, {}).get(cls):
                out.append({"key": key, "doc": doc, "cls": cls})
    return out


def pagetext(doc, q):
    """全文搜尋一份 PDF——`plan_web_usable.md` P1,解「找不到圖」。

    走 `locate.locate()`(有快取,`loc.texts` 已經是逐頁全文),**零新抽取**。
    回傳每個命中頁 ± 一小段上下文,讓人不必自己數頁碼——直接貼錨值的
    千分位字串(例如 `12,216,100`)就能跳到含那個數字的頁。
    """
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    q = (q or "").strip()
    if not q:
        return {"n_pages": len(loc.texts), "hits": []}
    hits = []
    for i, text in enumerate(loc.texts):
        pos = text.find(q)
        if pos < 0:
            continue
        lo, hi = max(0, pos - 20), min(len(text), pos + len(q) + 20)
        hits.append({"page": i, "snippet": text[lo:hi]})
    return {"n_pages": len(loc.texts), "hits": hits}


def fill_context(doc, cls, cellmeta=None):
    """抄列台要的:錨值、候選頁、規矩全文、一份空白模板。

    `pages` 走 `effective_pages()`,不直接讀 `loc.pages[cls]`——**兩個理由**:
    ① `cls` 若沒有anchor,`loc.pages` 根本沒有這個 key,直接下標會炸;
    ② 手動指定候選頁(`plan_web_complete.md` W3)要在這裡就生效,不然
    畫面上看不到覆寫有沒有真的算進候選頁清單。
    """
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    pages = effective_pages(loc, doc, cls, cellmeta or {})
    return {
        "doc": doc, "cls": cls,
        "anchor": loc.anchors.get(cls),
        "pages": pages,                              # 0-based
        "rules": fill.RULES,
        "template": {"records": [{
            "source_page": pages[0] if pages else 0, # 0-based,不要 +1
            "source_kind": "附註",
            # total_col / printed_total 不填——系統推導(`core/derive.py`,
            # `docs/plan_schema_derive.md` D1),手動貼 JSON 也一樣不必給。
            "rows": [{"name": "", "group": "", "cols": {}}],
        }]},
    }


def doc_detail(doc):
    """**一份文件的三類一起給**。這是使用者實際的工作單位 —— 你是「處理這份
    財報」,不是「處理 202504_5847_AI3|OCI 這一格」(2026-07-29 裁示)。

    每類的形狀依狀態而定,前端不必再自己判斷要打哪支 API:
      done      → `cell`(逐列 + 桶),核對用
      todo      → `fill`(錨、候選頁、模板),抄列用
      blocked   → `fill` + `reason`(分類表缺口,擴頁修不好,見 fill._taxonomy_gap)
      rejected  → `fill` + `reason`(擴到上限仍對不上,見 fill.cmd_submit)
      no_data   → `meta`(人工標記「文件真的沒有」的紀錄,`plan_web_complete.md` W3)
      na        → 其餘都 None,但 `anchor` 仍給(有錨、只是候選頁是空的那
                  2 格需要它,才有東西可以在畫面上顯示「指定候選頁」的入口)
    `pages` 一律拉到最上層,因為三類共用同一個頁圖檢視器。
    """
    cells = facts_mod.load()
    blocked = _marked_keys(fill.BLOCKED_DIR)
    rejected = _marked_keys(fill.REJECTED_DIR)
    cellmeta = load_cellmeta()
    index = fill._load_index()
    loc = locate.locate(f"pdf_cache/{doc}.pdf")

    # `v4.ledger.classify(doc)` 內部一次對整份 PDF 重跑三類 witness(見
    # `v4/witness.py:run_witness`,零快取,一次要重抽全部頁面文字)。
    # 呼叫它一次拿三類的結果,不要在下面的 per-cls 迴圈裡各叫一次
    # `v4_ledger.get_cell`——那等於把同一份 PDF 重抽三遍(2026-08-02 實測
    # 這支從 6.6s 掉到有 v4 資料時仍要跑一次 witness 的合理耗時)。
    from v4 import ledger as v4_ledger
    v4_cells = v4_ledger.classify(doc) or {}

    out, pages = {}, []
    for cls in locate.CLASSES:
        st = cell_status(cells, blocked, rejected, index, doc, cls, cellmeta)
        anchor = loc.anchors.get(cls)
        d = {"status": st, "cell": None, "fill": None, "reason": None,
            "meta": None, "anchor": anchor}
        v4c = v4_cells.get(cls)
        d["v4_cell"] = v4c
        if v4c and (v4c.get("book") or {}).get("page"):
            pages.append(v4c["book"]["page"] - 1)

        # 2026-08-02:拿掉了「v4 GREEN/RATIFIED 就自動轉譯成已完成 cell」那段 ——
        # 它寫死 `checks: {"ok": True}`、每列的桶寫死字串 `"v4"`(不是真的分桶),
        # 而 v4 目前完全不進 `build.py` 的發布路徑。結果是一格沒有真檢查、
        # `build.py` 永遠不會採用的資料,在畫面上跟真的已核對格長得一模一樣
        # (docs/plan_v5_統一.md §0.3)。`v4_cell` 原始資訊仍然給前端(上面已存
        # `d["v4_cell"]`),前端要不要顯示、怎麼標「這是 v4 初稿,不是已核可」
        # 是 P1/P4 的事,這裡不再假裝它已經 done。

        if st == "done":
            if d["cell"] is None:
                d["cell"] = cell_detail(f"{doc}|{cls}")
            if d["cell"]:
                pages += d["cell"].get("pages") or []
        elif st == "no_data":
            d["meta"] = (cellmeta.get(f"{doc}|{cls}") or {}).get("no_data")
        elif st in ("todo", "blocked", "rejected") or (st == "na" and anchor is not None):
            # `na` 但有錨:候選頁是空的那 2 格,一樣算 fill_context,讓前端
            # 有「0 個候選頁」可以顯示,並掛上「指定候選頁」的入口
            # (沒有錨的 na 今天沒有任何工具幫得上忙,見 W3 §6③ 待裁示)。
            d["fill"] = fill_context(doc, cls, cellmeta)
            if d["fill"]:
                pages += d["fill"].get("pages") or []
            if st in ("blocked", "rejected"):
                path = f"{fill.BLOCKED_DIR if st == 'blocked' else fill.REJECTED_DIR}/{doc}__{cls}.json"
                mark = json.load(open(path, encoding="utf-8"))
                d["reason"] = mark.get("reason")
                d["submitted"] = None
        out[cls] = d
    valid_pages = [p for p in pages if isinstance(p, int) and p >= 0]
    return {"doc": doc, "classes": out, "pages": sorted(set(valid_pages))}


def pending_entries():
    """待人裁示的科目名。合流兩個佇列,見 `core/queue.py`。"""
    return queue_mod.pending()


def queue_view():
    """裁示台:待裁示佇列**按名字批次**(2026-07-30 加,`plan_web_complete.md` W1)。

    `pending_entries()` 給的是每個「出現處」一筆(今天 75 筆),但裁示一次
    對整個名字生效(`confirm_bucket()` 寫的是全域 `buckets.SYN`,查表時看的
    是 `norm(name)`,不分是哪一格出現的)——所以人真正要做的決定數是
    **不重複名字數**(今天 31),不是出現次數。這支把 `pending()` 按名字
    分組,一組一個決定,並附上 `rules.propose()` 的建議讓人一眼判斷,
    不必先跳去 `buckets.py` 找。

    排序:**沒有建議的排最前面**——那才是真正需要人從零判斷的;
    有建議的省得下滑,但仍要人按過才算數(提案不等於生效,見 `rules.py` 檔頭)。
    """
    import rules

    groups = {}
    for e in pending_entries():
        name = e["name"]
        if not name:
            continue
        g = groups.setdefault(name, {"name": name, "n": 0, "cells": [],
                                     "why": set(), "source": set()})
        g["n"] += 1
        # 帶頁碼(0-based)——不然這個判斷點只給得出裸的 cell_key,人點不進去
        # 看證據(`docs/plan_schema_derive.md` §5/D4)。裁示改的是**全域規則**
        # (`buckets.SYN`),證據應該是「這個名字實際出現的那幾頁」,不是一句話。
        page = _pending_entry_page(e)
        doc, cls = e["cell_key"].split("|", 1)
        g["cells"].append({"cell_key": e["cell_key"], "doc": doc, "cls": cls, "page": page})
        if e.get("why"):
            g["why"].add(e["why"])
        g["source"].add(e["source"])

    out = []
    for name, g in groups.items():
        suggested, why = rules.propose(buckets.norm(name))
        # dedupe:同一個 (cell_key, page) 可能因為多個 occurrence 被加進來兩次
        seen, cells = set(), []
        for c in g["cells"]:
            k = (c["cell_key"], c["page"])
            if k not in seen:
                seen.add(k); cells.append(c)
        out.append({
            "name": name, "n": g["n"],
            "cells": sorted(cells, key=lambda c: c["cell_key"]),
            "source": sorted(g["source"]),
            "seen_why": sorted(g["why"])[:3],
            "suggested": suggested, "suggested_why": why,
        })
    out.sort(key=lambda g: (g["suggested"] is not None, -g["n"]))
    return {"buckets": config.BUCKETS, "groups": out,
            "occurrences": sum(g["n"] for g in out)}


def _pending_entry_page(e):
    """待裁示一筆的來源頁(0-based),找不到回 None——**不擋畫面**,只是那筆
    沒有頁級證據可以跳(`plan_schema_derive.md` §5 規矩 1:給不出證據要明講,
    不准沉默)。

    兩種來源分開找:
      · blocked  —— 這格還沒歸檔,頁在 `work/blocked/*.json` 的
                     `submitted.records[].rows[]` 裡(ref.path 已經指到那個檔)
      · review   —— 這格已經歸檔,頁在 `facts/` 裡(用 `_facts_name_page` 查)
    """
    if e.get("source") == "blocked":
        path = (e.get("ref") or {}).get("path")
        if path and os.path.exists(path):
            data = json.load(open(path, encoding="utf-8"))
            for rec in (data.get("submitted") or {}).get("records") or []:
                for row in rec.get("rows") or []:
                    if row.get("name") == e["name"]:
                        return rec.get("source_page")
        return None
    return _facts_name_page(e["cell_key"], e["name"])


def _facts_name_page(cell_key, name):
    """`facts/` 裡,`cell_key` 這格的 `name` 這個科目名出現在哪一頁(0-based)。
    找不到(改名過、或還沒歸檔)回 None。"""
    cells = facts_mod.load()
    for rec in cells.get(cell_key) or []:
        for row in rec.get("rows") or []:
            if row.get("name") == name:
                return rec.get("source_page")
    return None


def confirm_bucket(name, bucket_name, reason, today=None, path="buckets.py",
                   blocked_dir=None):
    """把人工裁示寫進 `buckets.SYN`。

    **這是唯一的寫入點**,而且對應的是 `fill.py` 自己印出來的指示
    (「提案已寫入 …,請使用者審核後收錄進 buckets.SYN」)—— 不是為了 UI
    方便新開的接受分支。收錄後仍要 `git diff` 審過再 commit,
    git 就是這裡的審核介面(見 buckets.py 檔頭)。

    `blocked_dir` 只給測試用(見 `_requeue_fully_resolved_blocked`)——
    不傳就是 production 路徑,測試傳 tmp 目錄以完全不碰真實 `work/blocked/`。
    """
    if bucket_name not in config.BUCKETS:
        raise ValueError(f"「{bucket_name}」不是 config.BUCKETS 裡的桶")
    norm = buckets.norm(name)
    if norm in buckets._SYN_N:
        return {"written": False, "why": "已收錄"}

    today = today or datetime.date.today().isoformat()
    text = open(path, encoding="utf-8").read()
    marker = "SYN = {"
    idx = text.index(marker) + len(marker)
    insertion = (f"\n    # {reason}(複核台裁示,{today})\n"
                 f"    {name!r}: {bucket_name!r},")
    open(path, "w", encoding="utf-8").write(text[:idx] + insertion + text[idx:])
    buckets._SYN_N[norm] = bucket_name       # 本次 process 立刻生效,不必重啟
    unstuck = _requeue_fully_resolved_blocked(blocked_dir)
    return {"written": True, "unstuck": unstuck}


def _requeue_fully_resolved_blocked(blocked_dir=None):
    """`confirm_bucket()` 收工前呼叫:一個 `work/blocked/` 檔可能同時列了
    好幾個提案名字,**全部**都能在 `buckets.SYN` 查到桶了,那格才算真的解套。

    這就是 `fill.py` 自己印出來的手動流程(「收錄後…再跑 requeue 把這格放回
    佇列」),差別只是不必再手動跑一次 CLI——裁示台按一次「收錄」,
    卡住的格子該不該放行由這裡現算,不是另外存一份「解套了嗎」的旗標。

    `blocked_dir` 只給測試用(注入 tmp 目錄),production 呼叫一律用預設值。
    """
    d = blocked_dir or fill.BLOCKED_DIR
    cleared = []
    for p in glob.glob(f"{d}/*.json"):
        data = json.load(open(p, encoding="utf-8"))
        names = [g.get("name") for g in (data.get("proposals") or [])]
        if names and all(buckets.bucket({"name": n}) is not None for n in names):
            os.remove(p)
            cleared.append(os.path.basename(p)[:-5].replace("__", "|"))
    return cleared


def bucket_view():
    """十個桶 × 收進去的科目名。**看的是 Decision 不是 buckets.SYN** ——
    SYN 是規則,Decision 是「這一列實際落在哪」,兩者可能不同(規則改過、
    人裁示過單一格)。畫面要呈現的是後者,否則你看到的是應然不是實然。

    同名不同桶是**真的會發生**的(富邦 202304 Trading 同一份附註裡「其他」
    出現兩次、桶不同),所以聚合鍵是 (bucket, name),不是 name。

    `state` 取該組裡**最弱**的一個:只要有一列還沒 CONFIRMED,整組就不算確認 ——
    「大部分確認了」在這裡等於沒確認。
    """
    from core import decision_store

    RANK = {"UNCLASSIFIED": 0, "PROVISIONAL": 1, "CONFIRMED": 2}
    groups = {}
    for cell_key, decs in decision_store.load().items():
        for d in decs:
            k = (d.get("mapping"), d["name"])
            g = groups.setdefault(k, {"bucket": d.get("mapping"), "name": d["name"],
                                      "n": 0, "state": "CONFIRMED", "cells": {}})
            g["n"] += 1
            # `locator.source_page` 每個 Decision 都有(0-based)——帶出去讓
            # 拖曳改桶這種**改全域規則**的判斷點也點得到證據頁,不只是一句
            # cell_key 文字(`docs/plan_schema_derive.md` §5/D4)。
            doc, cls = cell_key.split("|", 1)
            page = (d.get("locator") or {}).get("source_page")
            g["cells"][cell_key] = {"cell_key": cell_key, "doc": doc, "cls": cls, "page": page}
            if RANK[d["state"]] < RANK[g["state"]]:
                g["state"] = d["state"]

    cols = {b: [] for b in config.BUCKETS}
    loose = []                       # mapping is None → 還沒有桶可以放
    for g in groups.values():
        g["cells"] = sorted(g["cells"].values(), key=lambda c: c["cell_key"])
        (cols[g["bucket"]] if g["bucket"] in cols else loose).append(g)
    for v in cols.values():
        v.sort(key=lambda g: (g["state"] != "UNCLASSIFIED", g["state"] != "PROVISIONAL", -g["n"]))
    loose.sort(key=lambda g: -g["n"])

    tally = {"confirmed": 0, "provisional": 0, "unclassified": 0}
    for g in list(groups.values()):
        tally[g["state"].lower()] += g["n"]
    return {"buckets": config.BUCKETS,
            "cols": cols, "unclassified": loose, "tally": tally}


def fetch_log():
    """抓檔紀錄,新到舊。**給網頁看的**,不必再問我或開終端機 ——
    每一筆都是 acquire.fetch_one() 實際問過 TWSE 之後記下的答案
    (ok / absent / failed),不是猜的。"""
    log = acquire.load_log()
    return sorted(
        ({"key": k, **v} for k, v in log.items()),
        key=lambda e: e.get("at", ""), reverse=True)


def rebucket(name, to, global_=False, approved_by="henrylin", today=None):
    """把「一個科目名」改判到 `to` 桶 —— 分桶檢視拖曳的落地。

    **兩個動作分開,這是刻意的**(使用者 2026-07-29 裁示的選項 C):
      · 預設:立一條 taxonomy rule 並更新現有 Decision。改的是**分類紀錄**。
      · `global_`:額外寫進 `buckets.SYN`。那是**原始碼層的同義詞表**,
        會影響往後每一次抄列與每一份文件 —— 所以要另外點頭。

    CONFIRMED 不是隨便標的:`I3a` 要求指到一條 CONFIRMED 的 rule,`I3b` 要求
    那條 rule 至少有一條 `kind=="human"` 的依據。這裡兩條都補齊,不然
    `validate_decision` 會當場抓到。
    """
    from core import decision_store
    from core import decisions as dmod

    if to not in config.BUCKETS:
        raise ValueError(f"「{to}」不是 config.BUCKETS 裡的桶")
    today = today or datetime.datetime.now().isoformat(timespec="seconds")
    norm = buckets.norm(name)
    rule_id = f"tax:{norm}"

    path = os.path.join("taxonomy", "rules.json")
    rules = json.load(open(path, encoding="utf-8"))
    ref = dmod.make_reference(
        "human", f"分桶檢視拖曳:「{name}」→「{to}」 (by {approved_by})", today)
    hit = next((r for r in rules if r["rule_id"] == rule_id), None)
    if hit:
        hit.update(mapping=to, state=dmod.CONFIRMED,
                   approved_by=approved_by, approved_at=today)
        hit["references"] = list(hit.get("references") or []) + [ref]
    else:
        rules.append(dmod.make_rule(rule_id, "name", to, dmod.CONFIRMED, [ref],
                                    approved_by=approved_by, approved_at=today))
    json.dump(rules, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)

    cells = decision_store.load()
    touched = 0
    for decs in cells.values():
        for d in decs:
            if buckets.norm(d["name"]) != norm:
                continue
            d.update(mapping=to, state=dmod.CONFIRMED, taxonomy_ref=rule_id,
                     at=today, by="rebucket")
            touched += 1
    decision_store.save(cells)

    syn = None
    if global_:
        syn = confirm_bucket(name, to, f"分桶檢視拖曳(by {approved_by})")
    return {"rows": touched, "rule": rule_id, "syn": syn}


def requeue(cell_key):
    """把卡住的格放回待抄佇列 —— 只刪標記檔,不動 `facts/`
    (那些格從沒歸檔過,重跑一次是乾淨的,同 `fill.py requeue`)。

    ⚠️ **兩個目錄都要刪**(2026-07-30 修):這支原本只認 `BLOCKED_DIR`,
    `REJECTED_DIR`(擴頁到上限仍對不上的格,今天 25 格)完全沒有路徑退回 ——
    `fill.cmd_requeue()`(CLI 版)兩個目錄都刪,網頁版之前漏了一半。
    """
    doc, cls = cell_key.split("|", 1)
    removed = False
    for d in (fill.BLOCKED_DIR, fill.REJECTED_DIR):
        p = f"{d}/{doc}__{cls}.json"
        if os.path.exists(p):
            os.remove(p)
            removed = True
    return {"removed": removed}


def publish_status():
    """網站是不是比手上的資料舊 —— `plan_v5_統一.md` P4-1「永遠在的發布狀態列」,
    目前完全沒有這個訊號(2026-08 實測:facts/ 改到 07-31、v4/raw 改到 08-02,
    網站的 data.json 停在 07-29,畫面上沒有任何地方講)。

    只看 mtime,不重跑 build——這支要快到能常駐在 nav 上。
    """
    def _latest(pattern):
        paths = glob.glob(pattern)
        return max((os.path.getmtime(p) for p in paths), default=None)

    data_mtime = os.path.getmtime("data.json") if os.path.exists("data.json") else None
    sources = {
        "facts": _latest("facts/*.json"),
        "v4_raw": _latest("v4/raw/*.json"),      # GREEN 直接來自這裡,不必等 ratify
        "v4_ledger": _latest("v4/ledger/*.json"),  # RATIFIED 的凍結結果
    }
    newer = {k: v for k, v in sources.items() if v is not None and
             (data_mtime is None or v > data_mtime)}
    return {
        "data_mtime": data_mtime,
        "sources": sources,
        "stale": bool(newer),
        "newer_than_data": list(newer),
    }
