# -*- coding: utf-8 -*-
"""事實庫。**唯一的讀寫入口**——呼叫端一律用這支,不直接碰 `facts/*.json` 或 `facts.db`。

    load()       {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`
    save(cells)  寫回
    validate()   回傳問題清單。空 list = 通過。**不修資料,只報告。**

⚠️ **儲存後端有兩種,呼叫端不需要知道走哪一種**(`docs/plan_v6_一台機器.md` R1):

    facts.db 存在 → 走 `db.py`(三張表:observations 機器寫、rulings 人工寫,
                    人工永遠蓋過機器,append-only)
    facts.db 不存在 → 走 `facts/*.json` 直讀直寫(舊行為,clone 下來還沒
                      `python3 db.py migrate` 的人不受影響)

只有 **production 呼叫**(不傳 `facts_dir`)才會走 DB。任何呼叫傳了
`facts_dir`(絕大多數測試都這樣做,注入 tmp 目錄)一律走 JSON 直讀直寫,
不碰 `facts.db` —— 這樣切換儲存後端不需要改任何一支測試。

機器寫 `observations`、人工寫 `rulings` 的判準是**現有的**
`core.webdata.human_ratified()`:一格的 records 裡任何一列帶 `_src` 就是
人工裁示過。這支不重複那個判準,直接呼叫它。
"""
import glob
import json
import os

import db as db_mod

DIR = "facts"
_DEFAULT_DIR = DIR   # 捕捉原始值,`_use_db()` 拿它判斷 DIR 有沒有被改過

REQUIRED_REC = ("doc", "class", "source_page", "source_kind", "total_col",
                "printed_total", "rows")
#: `bs_anchor` = 這格在**資產負債表**上的金額(仟元),抽取當下就讀到的。
#: 存進 record 的理由是實測出來的:`transcribe.verify` 的④(合計==錨)一向靠
#: `locate.locate(pdf)` 現場去 PDF 裡找錨,而那個定位器在 **31/91 份文件上
#: 一個錨都找不到**(`bs_page=None`,全是 2022H1 以前的半年報)。
#: `closure.build()` 把「沒有錨」跟「對不上」都判 hard fail,於是那批文件的格
#: 一律拒收 —— 拒收的理由不是資料有問題,是**驗它的那把尺沒讀到刻度**。
#:
#: 錨是這一格的**事實**,不是每次建置要重新推導的東西。抽取器整份讀過 PDF、
#: 當場就看到 BS 那一行(v4 raw 34 份裡 27 份三類都報得出來),把它丟掉再叫
#: 一個看不到那麼多的定位器去找,是這條管線分岔的具體形狀。
OPTIONAL_REC = ("printed_totals", "note", "_by", "bs_anchor")
REQUIRED_ROW = ("name", "cols")
#: `_src` = 這一列是人在網頁上改 / 增的,不是機器抄的
#: (`docs/plan_web_complete.md` §2)。形狀 `{"by", "at", "why", "evidence"?}`——
#: 跟 `_by` 同一個模式:稽核欄位,`wide`/`buckets`/`verify` 一律不准讀它,
#: 只讀 `name`/`cols`/`group`。**沒有 `_src` = 機器抄的**,這是唯一的判準,
#: 不需要另外存一個「是不是人工」的旗標。
OPTIONAL_ROW = ("group", "_src")


def human_ratified(recs):
    """這格的 records 裡有沒有任何一列帶 `_src`(= 人工裁示過)。

    這是機器寫 `observations` / 人工寫 `rulings` 的唯一判準(`save()` 用它
    決定進哪一張表),同時也是 `core.webdata.human_ratified()` 原本的定義 ——
    那支現在委派到這裡,避免兩個模組各存一份「什麼是人工裁示」。
    """
    return any("_src" in row
               for rec in (recs or [])
               for row in (rec.get("rows") or []))


def _use_db(facts_dir):
    """production 呼叫(不傳 `facts_dir`,而且 `DIR` 也沒被改過)且 `facts.db`
    存在 → 走 DB。

    ⚠️ **兩種方式都算「注入了目錄」,不是只有 `facts_dir` 參數這一種。**
    `core/ingest.py._write_facts_and_decisions()`(真正的機器抄列落地路徑)
    與 `test_b2.py` 都用另一招:暫時把模組層的 `facts.DIR` 換成 tmp 目錄,
    再呼叫不帶 `facts_dir` 的 `load()`/`save()`。R1 上線時只檢查了
    `facts_dir is None`,沒檢查 `DIR` 有沒有被换過 —— 於是這招的呼叫端
    以為自己寫進了 tmp 目錄,其實悄悄寫進了正式的 `facts.db`
    (2026-08-11 實測抓到:`test_b2.py` 的 F3 案例把 `doc="X"` 的假資料
    寫進了正式事實庫,`facts/X.json` 是這次事故的殘留)。
    """
    return facts_dir is None and DIR == _DEFAULT_DIR and db_mod.exists()


def load(facts_dir=None):
    """→ {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`。

    `facts_dir` 只給測試用(注入 tmp 目錄,見 `test_webdata.py`)——
    production 呼叫一律用預設值,不要傳。"""
    if _use_db(facts_dir):
        cells = db_mod.materialize_cells()
    else:
        d = facts_dir or DIR
        cells = {}
        for p in sorted(glob.glob(f"{d}/*.json")):
            cells.update(json.load(open(p, encoding="utf-8")))
    problems = validate(cells)
    if problems:
        raise ValueError("facts.load(): 事實庫驗證失敗:\n" + "\n".join(problems))
    return cells


def save(cells, facts_dir=None, by=None, why=None):
    """寫回。DB 模式:機器寫的格進 `observations`,人工裁示過的(任何一列帶
    `_src`)進 `rulings`;同一次 `save()` 呼叫裡兩種可以混在一起,逐格判斷。
    寫完照樣匯出 `facts/*.json`(git diff 的可讀快照,見 `db.export_json()`)。

    JSON 模式(沒有 `facts.db`,或呼叫端傳了 `facts_dir`):按 doc 分檔直寫,
    舊行為不變。
    """
    if _use_db(facts_dir):
        machine, human = {}, {}
        for key, recs in cells.items():
            (human if human_ratified(recs) else machine)[key] = recs
        if machine:
            db_mod.record_observation(machine)
        if human:
            db_mod.record_ruling(human, by=by, why=why)
        db_mod.export_json()
        return

    d = facts_dir or DIR
    os.makedirs(d, exist_ok=True)
    by_doc = {}
    for key, recs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = recs
    for doc, part in by_doc.items():
        json.dump(part, open(f"{d}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)


def remove(key, facts_dir=None, by=None, why=None):
    """刪掉一格,回傳有沒有刪到。

    **為什麼不能只做 `del cells[key]; save(cells)`**:`save()` 只寫 `cells` 裡
    還在的 doc,一份 doc 的格**全部**被刪光時,舊檔就留在磁碟上,下次 `load()`
    又整份讀回來 —— 刪除靜靜失效。實測於 `core.webdata.revoke()`
    (2026-08-10):撤銷後該格仍在事實庫裡。

    檔案佈局的知識留在本檔,不外洩給呼叫端自己去 unlink。
    """
    if _use_db(facts_dir):
        cells = load(facts_dir)
        if key not in cells:
            return False
        db_mod.record_deletion(key, by=by, why=why)
        db_mod.export_json()
        return True

    d = facts_dir or DIR
    cells = load(facts_dir)
    if key not in cells:
        return False
    doc = key.split("|")[0]
    del cells[key]
    if not any(k.split("|")[0] == doc for k in cells):
        p = f"{d}/{doc}.json"
        if os.path.exists(p):
            os.remove(p)                 # 這份 doc 一格不剩 → 連檔一起收掉
    save(cells, facts_dir)
    return True


def validate(cells):
    """回傳問題清單。空 list = 通過。**不修資料,只報告。**"""
    problems = []
    for key, recs in cells.items():
        k_doc, k_cls = key.split("|", 1)
        for i, rec in enumerate(recs):
            tag = f"{key}[{i}]"
            missing = [f for f in REQUIRED_REC if f not in rec]
            if missing:
                problems.append(f"{tag}: 缺必要欄位 {missing}")
                continue
            unknown = [f for f in rec if f not in REQUIRED_REC + OPTIONAL_REC]
            if unknown:
                problems.append(f"{tag}: 出現未知欄位 {unknown}")
            if rec["doc"] != k_doc or rec["class"] != k_cls:
                problems.append(
                    f"{tag}: key 與內容不一致 key={k_doc}|{k_cls} "
                    f"內容={rec['doc']}|{rec['class']}")
            if not rec["rows"]:
                problems.append(f"{tag}: rows 為空")
            a = rec.get("bs_anchor")
            if a is not None and (isinstance(a, bool) or not isinstance(a, int)):
                # 錨要拿去跟印出合計做整數相等比較(`closure.build`),不是整數
                # 就驗不了。**寧可沒有錨也不要一個假的** —— 沒有錨時④會誠實說
                # 「查無可查」,而一個字串錨會讓比較永遠不相等、變成假失敗。
                problems.append(f"{tag}: bs_anchor 必須是整數(仟元),收到 {a!r}")
            total_col_seen = False
            for j, row in enumerate(rec["rows"]):
                rtag = f"{tag}.rows[{j}]"
                rmissing = [f for f in REQUIRED_ROW if f not in row]
                if rmissing:
                    problems.append(f"{rtag}: 缺必要欄位 {rmissing}")
                    continue
                runknown = [f for f in row if f not in REQUIRED_ROW + OPTIONAL_ROW]
                if runknown:
                    problems.append(f"{rtag}: 出現未知欄位 {runknown}")
                if not isinstance(row["name"], str) or not row["name"]:
                    problems.append(f"{rtag}: name 不是非空字串")
                if not isinstance(row["cols"], dict):
                    problems.append(f"{rtag}: cols 不是 dict")
                    continue
                for col, val in row["cols"].items():
                    if isinstance(val, bool) or not isinstance(val, int):
                        problems.append(f"{rtag}: cols[{col!r}] 不是 int:{val!r}")
                if rec["total_col"] in row["cols"]:
                    total_col_seen = True
            if not total_col_seen:
                problems.append(f"{tag}: total_col {rec['total_col']!r} 沒有出現在任何一列的 cols 裡")
            if "printed_totals" in rec:
                pt = rec["printed_totals"]
                if not isinstance(pt, dict):
                    problems.append(f"{tag}: printed_totals 不是 dict")
                else:
                    for col, val in pt.items():
                        if not isinstance(col, str):
                            problems.append(f"{tag}: printed_totals key 不是字串:{col!r}")
                        if isinstance(val, bool) or not isinstance(val, int):
                            problems.append(f"{tag}: printed_totals[{col!r}] 不是 int:{val!r}")
    return problems
