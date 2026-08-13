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
    absent     TWSE 清單上真的沒有這期這個口徑的檔(`resolve.download` 回 None)
    failed     抓過但失敗(網路/被擋)→ 可以重試

`absent` 一定要存下來,否則每次開頁面都會對著同一批不存在的期別重打 TWSE。
存在 `work/fetch_log.json`,格式
`{"{period}_{code}_{口徑}": {"status":..., "at":...}}`。

⚠️ **key 一定要帶口徑**。同一期同一家的個體與合併是兩件獨立的事實(TWSE
可以有其中一個而沒有另一個),共用一個 key 的話,問完個體得到 absent 會讓
合併那格也顯示「查無」,反之亦然 —— 兩種原因一種結果,鐵律 9。
"""
import datetime
import json
import os
import re

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


#: 帶口徑之前的 key(`{period}_{code}`)。那時抓得到的只有個體,所以舊紀錄
#: 一律是個體的答案 —— 這不是推測,是 `fetch_one()` 當時第一行就擋掉非個體。
_OLD_KEY = re.compile(r"^\d{6}_\d{4}$")


def load_log():
    """讀抓檔紀錄。舊 key **在讀進來的當下就補上口徑**。

    刻意不在查表時 fallback 去試舊 key:那會變成同一道「這格問過沒有」的
    規則有兩個實作,而這個 repo 的 bug 反覆長在那個形狀上。在入口正規化一次,
    底下所有人只認得一種 key。
    """
    if not os.path.exists(LOG):
        return {}
    raw = json.load(open(LOG, encoding="utf-8"))
    return {(f"{k}_{locate.SOLO}" if _OLD_KEY.match(k) else k): v
            for k, v in raw.items()}


def _key(period, code, basis):
    """抓檔紀錄的 key。**組 key 只在這裡發生一次**(檔頭:key 一定要帶口徑)。"""
    return f"{period}_{code}_{basis}"


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


def expected_banks():
    """應該要有哪些銀行 —— `config.BANKS` 全部,**兩個口徑一視同仁**。

    2026-08-12 之前合併是特例:只列「已經有合併檔的那幾家」(當時只有中信)。
    那讓合併變成一個死結 —— 沒檔就沒欄、沒欄就沒格可按,於是唯一的進料口
    只剩拖放上傳,而且順序是反的(得先把檔拖進來,那一欄才會長出來)。
    使用者要在合併網格上加國泰時撞到的就是這個:`add_bank()` 說「國泰已經
    在清單裡」——完全正確,卻答的是另一個問題,因為讓它出現在合併網格的
    條件從來不是銀行清單,是有沒有檔。

    這正是本模組開頭那段(「格子由日曆決定,不由現有檔案決定」)要解的病,
    當時只解了個體那半邊 —— 一道規則兩個實作,又一次。合併現在抓得到了
    (`fetch_one` 收 basis),特例沒有理由再留。

    不收參數:兩個口徑同一個答案,留著 `basis` 只會讓人以為它還有分別。
    """
    return sorted(config.BANKS.values())


def doc_name(period, code, basis=locate.SOLO):
    """預期的檔名。**收代碼、回新式檔名** —— 代碼是 TWSE 那邊的身分,
    檔名是我們這邊的身分,這裡是兩者唯一的轉換點(`docid.py` 檔頭)。
    """
    bank = config.BANKS.get(code, code)
    return docid.make(period, bank, basis)


def cell_fetch_state(period, code, docs_present, log=None, basis=locate.SOLO):
    """一格在「抓檔」這個維度上的狀態。已經有檔就回 None(交給抄列那條線判)。"""
    if doc_name(period, code, basis) in docs_present:
        return None
    rec = (log if log is not None else load_log()).get(_key(period, code, basis))
    if rec and rec.get("status") in ("absent", "failed"):
        return rec["status"]
    return "missing"


def fetch_one(period, code, basis=locate.SOLO):
    """抓一期。回傳 {"status": ok|absent|failed, ...},並記進 fetch_log。

    **兩個口徑都抓得到**(2026-08-12)。原本這裡第一行是
    `if basis != SOLO: return failed`,理由寫「合併要另外一套解析」——
    但那是錯的:`resolve.report_filename()` 的最近標籤演算法一直都同時
    算出個體與合併,只是把合併那個丟掉。真正缺的是把口徑當參數傳下去,
    不是第二套解析器。
    """
    import resolve
    year, month = int(period[:4]), period[4:]
    roc = year - 1911
    key = _key(period, code, basis)
    log = load_log()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        path = resolve.download(code, roc, month, basis=basis)
    except Exception as e:                                   # noqa: BLE001
        log[key] = {"status": "failed", "at": now, "why": f"{type(e).__name__}: {e}"}
        save_log(log)
        return log[key]

    if path is None:
        # 清單上沒有這期這個口徑的檔。**這是答案,不是失敗** —— 記下來,
        # 否則每次開頁面都會對同一批不存在的期別重打 TWSE。
        log[key] = {"status": "absent", "at": now,
                    "why": f"TWSE 清單上沒有這期的{basis}檔"}
        save_log(log)
        return log[key]

    log[key] = {"status": "ok", "at": now, "path": str(path)}
    save_log(log)
    return log[key]


def missing_cells(basis, docs_present, log=None):
    """所有「預期有、但還沒抓」的格,新到舊。`absent` 不算 —— 那是已知沒有。

    回傳的每一筆都帶 `basis`:呼叫端(網頁 → `server._fetch_run`)要原樣
    交給 `fetch_one()`,漏掉的話合併那批會被當成個體去抓。
    """
    log = load_log() if log is None else log
    out = []
    for period in expected_periods(basis):
        # `expected_banks()` 回的是**名字**(畫面與檔名的身分),而抓檔要
        # **代碼**(TWSE 的身分)。轉換只在這裡發生一次。
        for bank in expected_banks():
            code = config.CODE_OF.get(bank)
            if not code:
                continue      # 不在設定裡的銀行抓不了 —— 那是設定的事,不在這裡猜
            if cell_fetch_state(period, code, docs_present, log, basis) == "missing":
                out.append({"period": period, "code": code, "basis": basis})
    return out
