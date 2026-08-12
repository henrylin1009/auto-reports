# -*- coding: utf-8 -*-
"""抓檔層:決定「應該要有哪些格」,以及把缺的那些抓回來。

**與 `core/webdata.py` 分開的理由不是潔癖**:webdata 是純函式資料層,不連外網;
這支會打 TWSE。混在一起的話,單純開個總覽頁都可能卡在網路逾時。

## 為什麼需要「預期清單」

矩陣原本的列與欄都是從 `pdf_cache/*.pdf` 反推的(`fill._all_docs()`)。
沒有 PDF 就沒有那一格,連那一列都不存在 —— 所以新年度到了,那一列**根本不會出現**,
使用者沒有任何地方可以說「這期我要」。這裡改成由日曆規則生成應有的格子,
現有檔案只決定每一格的**狀態**,不決定格子存不存在。

## 三種「沒有檔」要分開

    missing    還沒抓 → 可以按「抓這期」
    absent     TWSE 清單上真的沒有這期的個體檔(`resolve.download` 回 None)
    failed     抓過但失敗(網路/被擋)→ 可以重試

`absent` 一定要存下來,否則每次開頁面都會對著同一批不存在的期別重打 TWSE。
存在 `work/fetch_log.json`,格式 `{"{period}_{code}": {"status":..., "at":...}}`。
"""
import datetime
import json
import os

import config
import docid
import locate

LOG = "work/fetch_log.json"

#: 個體財報只有半年報(02)與年報(04);合併才有四季。兩者期別不同是**事實**,
#: 不是設定 —— 硬塞進同一個網格就會長出一整排永遠空著的季報欄。
MONTHS = {locate.SOLO: ("02", "04"), locate.CONSOLIDATED: ("01", "02", "03", "04")}

#: 與 `core.webdata.CUTOFF_YEAR` 同一個裁示(只做 2023+)。這裡不 import 它,
#: 因為 webdata 反過來要 import 本模組,會繞成環。
START_YEAR = 2023


def load_log():
    if not os.path.exists(LOG):
        return {}
    return json.load(open(LOG, encoding="utf-8"))


def save_log(log):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    json.dump(log, open(LOG, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)


def expected_periods(basis=locate.SOLO, today=None):
    """從 START_YEAR 到今年,依口徑生成應有的期別,新到舊。

    **不預測某期存不存在**。2026 年報要到 2027 年初才申報,但這裡照樣把它列出來 ——
    真相由 `fetch_one()` 打 TWSE 問出來,問到沒有就記成 `absent`。
    在這裡自作聰明地跳過,等於用猜的取代可以查證的事實。
    """
    today = today or datetime.date.today()
    out = []
    for y in range(today.year, START_YEAR - 1, -1):
        for m in sorted(MONTHS[basis], reverse=True):
            out.append(f"{y}{m}")
    return out


def expected_banks(basis, docs_present):
    """該口徑下應該有哪些銀行。

    個體:`config.BANKS` 全部 —— 那是分析的基準,每一家都該齊。
    合併:**只列已經有檔的那幾家**。合併目前只追中信一家,憑空生出另外四家
    × 十幾季的空格只是雜訊;而且 `resolve.download()` 專挑「個體」那份,
    合併根本不是它抓得到的東西(見 `fetch_one` 的 basis 檢查)。
    """
    if basis == locate.SOLO:
        return sorted(config.BANKS.values())
    return sorted({docid.bank_of(d) for d in docs_present if docid.is_valid(d)})


def doc_name(period, code):
    """預期的檔名。**收代碼、回新式檔名** —— 代碼是 TWSE 那邊的身分,
    檔名是我們這邊的身分,這裡是兩者唯一的轉換點(`docid.py` 檔頭)。

    只回個體:這支所在的取得層本來就只抓個體(見 `fetch_one`)。
    """
    bank = config.BANKS.get(code, code)
    return docid.make(period, bank, docid.SOLO)


def cell_fetch_state(period, code, docs_present, log=None):
    """一格在「抓檔」這個維度上的狀態。已經有檔就回 None(交給抄列那條線判)。"""
    if doc_name(period, code) in docs_present:
        return None
    rec = (log if log is not None else load_log()).get(f"{period}_{code}")
    if rec and rec.get("status") in ("absent", "failed"):
        return rec["status"]
    return "missing"


def fetch_one(period, code, basis=locate.SOLO):
    """抓一期。回傳 {"status": ok|absent|failed, ...},並記進 fetch_log。

    只支援個體:`resolve.indiv_filename()` 專挑清單上標「個體」的那份,
    合併要另外一套解析。與其偷偷抓錯口徑的檔,不如明說不支援。
    """
    if basis != locate.SOLO:
        return {"status": "failed", "why": "只支援抓個體財報,合併要另外處理"}

    import resolve
    year, month = int(period[:4]), period[4:]
    roc = year - 1911
    key = f"{period}_{code}"
    log = load_log()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        path = resolve.download(code, roc, month)
    except Exception as e:                                   # noqa: BLE001
        log[key] = {"status": "failed", "at": now, "why": f"{type(e).__name__}: {e}"}
        save_log(log)
        return log[key]

    if path is None:
        # 清單上沒有這期的個體檔。**這是答案,不是失敗** —— 記下來,
        # 否則每次開頁面都會對同一批不存在的期別重打 TWSE。
        log[key] = {"status": "absent", "at": now,
                    "why": "TWSE 清單上沒有這期的個體檔"}
        save_log(log)
        return log[key]

    log[key] = {"status": "ok", "at": now, "path": str(path)}
    save_log(log)
    return log[key]


def missing_cells(basis, docs_present, log=None):
    """所有「預期有、但還沒抓」的格,新到舊。`absent` 不算 —— 那是已知沒有。"""
    log = load_log() if log is None else log
    out = []
    for period in expected_periods(basis):
        # `expected_banks()` 回的是**名字**(畫面與檔名的身分),而抓檔要
        # **代碼**(TWSE 的身分)。轉換只在這裡發生一次。
        for bank in expected_banks(basis, docs_present):
            code = config.CODE_OF.get(bank)
            if not code:
                continue      # 不在設定裡的銀行抓不了 —— 那是設定的事,不在這裡猜
            if cell_fetch_state(period, code, docs_present, log) == "missing":
                out.append({"period": period, "code": code})
    return out
