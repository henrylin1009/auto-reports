# -*- coding: utf-8 -*-
"""資本適足 + 盈餘分配的定位與驗收。走 phase0.py / extract_pnl.py 那條(單表、獨立 JSON),
**不碰 data.json** —— 那條有 build.py 當唯一寫入者、有快照保底,塞新欄位要連帶動
wide_metrics 與三支測試,風險遠大於收益。

## 為什麼不用 locate.py

locate.py 的錨是「BS 上三分類金融資產的值」,`CLASSES` 也寫死 Trading/OCI/AC。
資本適足表與權益變動表在 BS 上沒有對應錨可以 grep,套不進去。但**分工原則照抄**:

    Python 只找頁 + 驗收,讀表全交給 agent。

## 為什麼特別不准在這裡寫 parser

五家版面完全不同,而且是「同一個欄位、五種擺法」:

    中信   個體/合併分成兩張表(p108/p109)
    國泰   自行|合併 並排當欄,而且**兩個年度分在兩頁**(p119=114年, p120=113年)
    富邦   合併|本行|合併|本行 四欄交錯 —— 取第 1、3 個數字會全取到合併
    玉山   本公司|合併 並排
    兆豐   只有一張表(金控持股 100%,子公司小),且表身在文字層但欄名夾空白

實測教訓:為每種擺法補一條規則,連續錯三次(兆豐讀成資本適足率、年度對位跑掉、
富邦讀成合併當個體)。這正是 locate.py 開頭警告的「重造死規則解析器」。

## 對帳是免費的

兩張表的檢查數字都印在同一張表上,不需要外部真值:

    資本適足  CET1/RWA == 印出的比率;自有資本 == CET1+其他T1+T2;
              RWA == 信用+作業+市場;跨年重疊(前期欄 == 上一份的當期欄)
    權益變動  指撥列橫向加總 == 0(抽屜間搬移);期初+變動 == 期末;
              期末各欄 == BS 對應科目(跨表);提列法定 ÷ 前一年度淨利 ≈ 30%;
              股票股利金額 == 股本增加額

⚠️ basis(個體/合併)一定要跟著值走。D-SIB 門檻適用**合併**(國泰附註:「其合併後
資本適足率不得低於…」),但債券資料(facts/)是**個體 AI3**。混用會出錯 —— 實測把
富邦的合併 10.64% 當個體用了三輪,結論全錯。
"""
import json
import os
import re

import pdfplumber

import config
import docid

#: **銀行清單只有一份**(`config.BANKS`)。這裡原本自己複製了一份一模一樣的
#: 字典 —— 新增一家銀行要同步改四處(config / capital / yields / resolve),
#: 而沒有任何檢查抓得到漏改。2026-08-12 收成一份。
BANKS = config.BANKS

#: 資本適足表的錨。實測 5 家 × 5 份年報 25/25 全中,每份命中 1~3 頁。
CAP_ANCHOR = "加權風險性資產總額"

#: 權益變動表的欄名。**比對前必須去空白** —— 欄名是直排/夾空白印的,
#: 中信印成「未分配\n盈 餘」、兆豐印成「未 分 配 盈 餘」,
#: 連續字串比對會 0/25 全掛(實測)。
EQ_COLS = ("法定盈餘公積", "特別盈餘公積", "未分配盈餘")

#: 用來把權益變動表跟**資產負債表**分開 —— BS 也有那三個科目,
#: 但沒有「餘額」列與淨利列。少了這道,中信 202504 會定位到 p7(BS)而不是 p9。
EQ_ROWS = ("餘額",)
EQ_NET = ("本期淨利", "年度淨利")

#: 掃描影像檔:報表頁無文字層。實測 202104 的中信/國泰/富邦/玉山 p4~p11 len==0,
#: 目錄顯示那正是四大報表。**這是資料限制不是錨失敗**,要補值得跑 OCR。
MIN_TEXT = 200

#: 附註「金融工具之公允價值」的錨 —— AC 的公允價值只印在這裡。
#:
#: ⚠️ **不在投資明細表**。明細表多出來的那欄叫「總額/總面額/面值總額」,是**面額**不是市價
#: (驗算:總額 + 未攤銷溢(折)價 − 備抵損失 == 帳面金額)。拿它當市價會得到接近 0 的假浮虧。
#:
#: 這句是 IFRS 7 揭露的固定開場白。五家各印各的,只有這五個字是共同子字串:
#:
#:     中信/兆豐  除下表所列示者外        國泰  除下表所列示之項目外
#:     玉山       除下表所列外            富邦  除下表所列示之項目外(句子倒裝)
#:
#: 比抄表頭穩 —— 表頭有「帳面價值」與「帳面金額」兩種,欄數還有 2 欄與 4 欄兩種。
FV_ANCHOR = "除下表所列"

#: 退路:錨句被斷行或改寫時,認版面 —— 同頁要有攤銷後成本 + 公允價值 + 帳面欄名。
FV_LOOSE = ("攤銷後成本", "公允價值")
FV_BOOKCOL = ("帳面價值", "帳面金額")

#: ⚠️ **不要用「第三等級」把整頁擋掉。** 公允價值等級表也有「按攤銷後成本衡量之
#: 債務工具投資」那一列,而且它是「合計/第一/第二/第三等級」四欄,拿合計除第一等級
#: 會做出 −12%~−27% 的假浮虧(第一版就是這樣被汙染的)。但實測**五家的等級表都印在
#: 正表的同一頁**,整頁擋掉會五家全殺。這件事交給工單講清楚 + verify 的量級閘門與
#: facts/ 對帳去攔,不在定位這層做。

#: 子公司分部的同名表(中信證券部門、金控旗下人壽),口徑不是本行個體。
FV_ANTI_SCOPE = ("證券部門", "人壽", "保險")

#: 綜合損益表(四大報表之一)。錨只用「利息淨收益」—— 加「本期淨利」會掉 2/5:
#: 富邦與玉山的損益表跨兩頁,淨利在次頁。所以**一律連下一頁一起送工單**。
#:
#: 證券的損益有四條印在表身上,不必翻附註(這是本輪才發現的):
#:     49310/43100  透過其他綜合損益按公允價值衡量之金融資產已實現損益
#:     49450        除列按攤銷後成本衡量之金融資產損益
#:     65308/65309  透過其他綜合損益按公允價值衡量之債務工具評價損益(在 OCI 段)
#: 科目代碼五家不同(中信 49310 vs 兆豐 43100 是同一項),**錨與抄讀都認中文品名**。
PNL_ANCHOR = "利息淨收益"
PNL_MAXPAGE = 26

#: 附註「利息淨收益」裡的證券利息那一列。五家列名不同,而且**範圍不一樣**:
#:     有價證券息 / 投資有價證券利息收入        = 全證券(AC+OCI,不含 Trading)
#:     按攤銷後成本衡量之債務工具投資利息        = 只有 AC 桶(富邦)
#: 不要自己統一,照抄原文,口徑交給驗收判。
#:
#: ⚠️ 分子已經排除 Trading —— 附註自己寫「上表不含透過損益按公允價值衡量之金融資產
#: 或金融負債所產生者」(中信/富邦明印;另三家把 Trading 利息放在 FVTPL 那個附註的
#: 獨立欄位)。**所以算殖利率時分母也必須是 AC+OCI,不能含 Trading。**
#: 實測含 Trading 會把橫斷面極差從 0.37~0.66pt 壓成 0.14~0.31pt,而且排名翻轉
#: (兆豐 Trading 只佔 4.5%、別家 16~29%,等於系統性懲罰 Trading 多的銀行)。
INT_ROWS = ("有價證券息", "投資有價證券利息", "按攤銷後成本衡量之債務工具投資利息",
            "證券投資利息")

#: 附表「利息收入明細表」。20/20 都印,但**只有國泰與玉山真的是一張表** ——
#: 中信與兆豐印的是「請參閱附註六(…)」,富邦的索引也指回附註三三。
#: 這兩家的分桶利息就是沒有,不是抄漏。
#:
#: ⚠️ 富邦另有一張同名的「明細表十二」(202504 p206),合計只有 16 億,
#: 而全行利息收入是 1,186 億 —— 那是子分部的表。用它會把殖利率算成 1/70。
#: 所以認表要求同頁必須有「貼現及放款利息」或「投資有價證券利息」這種全行科目。
DETAIL_ANCHOR = "利息收入明細表"
DETAIL_MUST = ("貼現及放款利息", "投資有價證券利息")


def _flat(page):
    return re.sub(r"\s+", "", page.extract_text() or "")


def _flat_coord(page):
    """用逐字座標按列重組後的去空白文字。

    `extract_text()` 在「橫排標題 + 左側直排欄名」的版面會把兩者交織成字元湯,
    連續字串比對整頁失效。實測第一銀行(5844) 202504 p124:

        extract_text → '總第險率率曝說險額1險明一類加權性＝普＝(。1總及資普4年12月28353…'
        座標重組     → '普通股權益 285,536,856' / '加權風險性資產總額 2,442,312,979' …

    表在、字在,只是順序被打散。兆豐的證券部門表也是同一種病(memory 已記)。
    這個比 extract_text 慢一個量級,所以只在快路徑整份都沒命中時才跑。
    """
    from collections import defaultdict
    rows = defaultdict(list)
    for ch in page.chars:
        rows[round(ch["top"])].append(ch)
    return re.sub(r"\s+", "", "".join(
        "".join(c["text"] for c in sorted(rows[k], key=lambda x: x["x0"]))
        for k in sorted(rows)))


def locate(path, kind):
    """回傳候選頁碼(1-based)。kind: 'capital' | 'equity' | 'fair_value'。

    equity 只掃前 26 頁 —— 權益變動表是四大報表之一,一定在前段;
    全頁掃 25 份 PDF 會逾時(實測 9 分鐘沒跑完)。
    fair_value 在附註後段,必須全掃。
    """
    if not os.path.exists(path):
        return None
    pdf = pdfplumber.open(path)
    try:
        n = len(pdf.pages)
        if kind in ("equity", "pnl"):
            rng = range(min(PNL_MAXPAGE, n))
        else:
            rng = range(n)
        # fair_value 先只認錨句。認版面那條(FV_LOOSE)會把會計政策段、
        # 移轉未除列表、互抵表一起撈進來 —— 實測中信多 5 頁、兆豐多 3 頁,
        # 工單被灌爆而真正那張反而被 MAX_PAGES 切掉。零命中才放寬。
        out = _scan(pdf, rng, kind, _flat, loose=False)
        if not out and kind == "fair_value":
            out = _scan(pdf, rng, kind, _flat, loose=True)
        # 快路徑整份沒命中才退到座標重組。**不要因為「有命中」就跳過** ——
        # 有命中不代表命中完整,但整份零命中一定是版面問題,不是真的沒有這張表。
        if not out:
            out = _scan(pdf, rng, kind, _flat_coord, loose=True)
        # 表被「(接次頁)」切開時要把續頁一起送工單,而且**要一路跟到底**:
        #   玉山的損益表跨三頁(p8→p9→p10),OCI 的「可重分類」段在第三頁。
        #   只補一頁 → 三份年報的 oci_debt_ovi 全部抄不到(實測 FAIL ×3)。
        #   富邦的公允價值表跨兩頁,前期欄整個在續頁(實測靜靜少四格)。
        # 少格不會報錯,只會讓下游的分析悄悄少一年 —— 所以寧可多送一頁。
        # ⚠️ 損益表**不能只靠「接次頁」判斷**:兆豐 202204 的表跨 p11-p12,
        #    兩頁都沒印那三個字,就是直接接著排(而且該頁是字元湯,連
        #    _flat_coord 也找不到標記)。少了 p12 就抄不到 65309 那一列。
        #    所以 pnl 一律無條件多送一頁,再跟接次頁的鏈。
        # ⚠️ 公允價值那張也一樣不能只靠標記:富邦 202304 的錨句
        #    「除下表所列示之項目外…」印在 p107 的**最後一行**,表整個在 p108,
        #    兩頁都沒有「接次頁」。只送 p107 → 模型回「這幾頁沒有可抄的表」(實測兩次)。
        if kind in ("pnl", "fair_value"):
            out = _follow(pdf, sorted({p for i in out
                                       for p in (i, i + 1) if p <= n}), n)
        # 附註那張常印「(接次頁)」把利息費用切到次頁(玉山),同上處理;
        # 另外把附表「利息收入明細表」接在後面 —— 它才有 AC/OCI 分桶,
        # 而且它的合計可以跟附註的小計互相對帳(同一份 PDF 內的第二來源)。
        if kind == "interest":
            more = []
            for i in out:
                more.append(i)
                if i < n and "接次頁" in _flat(pdf.pages[i - 1]):
                    more.append(i + 1)
            # 附表那頁自己也符合 interest 的條件(它有列名也有「利息收入」),
            # 直接相加會出現重複頁 —— 重複會吃掉 MAX_PAGES 的額度。
            seen, merged = set(), []
            for p in sorted(set(more)) + _scan(pdf, rng, "interest_detail", _flat):
                if p not in seen:
                    seen.add(p)
                    merged.append(p)
            out = merged
        return out
    finally:
        pdf.close()


def _scan(pdf, rng, kind, flatten, loose=True):
    out = []
    for i in rng:
        page = pdf.pages[i]
        flat = flatten(page)
        if kind == "capital":
            if CAP_ANCHOR in flat:
                out.append(i + 1)
            continue
        if kind == "pnl":
            if PNL_ANCHOR in flat and len(flat) >= MIN_TEXT:
                out.append(i + 1)
            continue
        if kind == "interest":
            # 前段是四大報表(損益表本身也有「利息收入」),證券利息那一列只在附註,
            # 所以用列名認,不用「利息收入」認。
            if "利息收入" in flat and any(w in flat for w in INT_ROWS) \
                    and i + 1 > PNL_MAXPAGE:
                out.append(i + 1)
            continue
        if kind == "interest_detail":
            if DETAIL_ANCHOR in flat and any(w in flat for w in DETAIL_MUST):
                out.append(i + 1)
            continue
        if kind == "fair_value":
            if any(w in flat for w in FV_ANTI_SCOPE):
                continue
            if not any(w in flat for w in FV_BOOKCOL):
                continue
            if FV_ANCHOR in flat:
                out.append(i + 1)
            elif loose and all(w in flat for w in FV_LOOSE):
                out.append(i + 1)
            continue
        if len(flat) < MIN_TEXT:
            continue
        head = ("權益變動表" in flat) or all(k in flat for k in EQ_COLS)
        if head and any(k in flat for k in EQ_ROWS) and any(k in flat for k in EQ_NET):
            out.append(i + 1)
    return out


#: 「(接次頁)」的續頁最多再跟幾頁。4 是 capital_auto.MAX_PAGES 的上限,
#: 再多也送不進工單;實測最長的是玉山損益表的三頁。
FOLLOW_MAX = 3


def _follow(pdf, pages, n):
    """把每個候選頁的「(接次頁)」續頁一路串進來。回排序去重後的頁碼。"""
    out = set()
    for p in pages:
        out.add(p)
        for _ in range(FOLLOW_MAX):
            if p >= n or "接次頁" not in _flat(pdf.pages[p - 1]):
                break
            p += 1
            out.add(p)
    return sorted(out)


def context(path, page):
    """產生 agent 的工單:該頁的**逐字座標重組**,不是 extract_text。

    extract_text 會把並排欄壓成一行(富邦四欄交錯就是這樣被讀錯的),
    帶 x 座標才分得出哪個數字屬於哪一欄。
    """
    from collections import defaultdict
    pdf = pdfplumber.open(path)
    try:
        rows = defaultdict(list)
        for ch in pdf.pages[page - 1].chars:
            rows[round(ch["top"])].append(ch)
        out = []
        for k in sorted(rows):
            cs = sorted(rows[k], key=lambda x: x["x0"])
            toks, cur, x0, prev = [], "", None, None
            for x in cs:
                if prev is not None and x["x0"] - prev > 3.0:
                    if cur.strip():
                        toks.append((round(x0), cur))
                    cur, x0 = "", None
                if x0 is None:
                    x0 = x["x0"]
                cur += x["text"]
                prev = x["x1"]
            if cur.strip():
                toks.append((round(x0), cur))
            if toks:
                out.append((k, toks))
        return out
    finally:
        pdf.close()


#: 檢查是三值的(沿用 transcribe.py 的規矩):None=通過、NA_*=不適用、字串=失敗。
#: 「不適用」不准畫成綠燈 —— 那是恆真閘門。
NA_NO_PRINTED = "N/A(該表未印比率)"
NA_NO_CONSOL = "N/A(無合併表)"


def verify_capital(rec, tol=0.011):
    """資本適足一格的驗收。rec 需有 cet1 / rwa / 印出的 cet1_pct(可選 tier1/tier2/自有資本)。

    tol 用 0.011pt:財報比率印到小數兩位,四捨五入誤差最大 0.005,留一倍餘裕。
    **不要放寬到 0.05** —— 實測把資本適足率(16.42%)誤讀成 CET1 比率(14.16%)時,
    差 2.26pt,任何合理容差都擋得住;放寬只會讓真錯溜過去。
    """
    fails = []
    if not rec.get("cet1") or not rec.get("rwa"):
        return "缺 cet1 或 rwa"
    calc = rec["cet1"] / rec["rwa"] * 100
    printed = rec.get("cet1_pct")
    if printed is None:
        fails.append(NA_NO_PRINTED)
    elif abs(calc - printed) > tol:
        fails.append(f"CET1/RWA={calc:.2f}% 對不上印出的 {printed:.2f}%")
    own = rec.get("own_funds")
    if own is not None:
        parts = rec["cet1"] + (rec.get("other_tier1") or 0) + (rec.get("tier2") or 0)
        if abs(parts - own) > max(1, own * 1e-6):
            fails.append(f"自有資本 {own:,} != CET1+其他T1+T2 {parts:,}")
        # 印出的資本適足率(BIS)= 自有資本 / RWA。這道跟 CET1 那道是**不同的兩個數**,
        # 一起驗才擋得住「兩個比率抄反」——實測兆豐就是這樣抄反的。
        if rec.get("bis_pct") is not None:
            calc_bis = own / rec["rwa"] * 100
            if abs(calc_bis - rec["bis_pct"]) > tol:
                fails.append(f"自有資本/RWA={calc_bis:.2f}% 對不上印出的 {rec['bis_pct']:.2f}%")
    if rec.get("tier1_pct") is not None:
        t1 = rec["cet1"] + (rec.get("other_tier1") or 0)
        calc_t1 = t1 / rec["rwa"] * 100
        if abs(calc_t1 - rec["tier1_pct"]) > tol:
            fails.append(f"第一類/RWA={calc_t1:.2f}% 對不上印出的 {rec['tier1_pct']:.2f}%")
    # ③ RWA 總額 == 信用 + 作業 + 市場。三項都抄到才驗 —— 少抄一項不算失敗
    #    (有些版面把作業/市場風險印在另一頁),但抄到了就必須合。
    parts3 = [rec.get(k) for k in ("rwa_credit", "rwa_op", "rwa_mkt")]
    if all(v is not None for v in parts3):
        s = sum(parts3)
        if abs(s - rec["rwa"]) > max(1, rec["rwa"] * 1e-6):
            fails.append(f"RWA {rec['rwa']:,} != 信用+作業+市場 {s:,}")
    return fails or None


#: 貨幣市場工具:沒有存續期間、不生浮虧,所以公允價值幾乎等於帳面。
#: 認**構詞**不認版型 —— 五家印成可轉讓定期存單 / 央行定期存單 / 銀行定期存單 /
#: 短期票券 / 國庫券 / 商業本票。
#:
#: ⚠️ 這段佔比很大而且各家差很多(中信 35~49%、兆豐 88%),混在分母裡會把 AC 的
#: 浮虧率系統性稀釋 —— 中信 2022 全帳算是 −3.62%,扣掉才是 −7.15%,差一倍。
MM_PAT = re.compile(r"可轉讓定期?存單|(央行|銀行)?定期?存單|國庫券|商業本票|短期票券")

NA_NO_FACTS = "N/A(facts/ 沒有這份的 AC 可對帳)"


def _roc_col(cols, year):
    """挑西元 year 那一欄的 key。**欄名格式各家不同,只認開頭的民國年數字**:

        中信「110.12.31」   富邦「110年12月31日」

    玉山那張明細表根本沒有年度欄(欄是 總面額/未攤銷溢(折)價/備抵損失/帳面價值),
    也就是**只印當期一個年度** —— 那種回 None,不要硬湊。
    """
    want = str(int(year) - 1911)
    return next((k for k in cols
                 if (re.match(r"\s*(\d+)", str(k)) or [None, None])[1] == want), None)


def ac_totals(doc, year=None):
    """回 (全帳, 扣貨幣市場) 的 AC 帳面金額,單位仟元;沒有就回 (None, None)。

    這是 fair_value 的**第二來源**:AC 的公允價值那張表自己印帳面價值,
    而 facts/ 是完全獨立的另一次抽取(投資明細表/附註)。兩邊對得上才收。

    year 指定西元年時**改抓那一年的欄**,不是預設的 total_col(當期欄)。
    ⚠️ 為什麼需要:投資明細表本來就同時印當期與前期兩欄。原本只認當期欄,
    要驗 2021 就只能去找 `facts/202104`,而中信與富邦根本沒有那份
    (掃描影像無文字層)、玉山那份沒有 AC ——**三家的 2021 就被判成「無法對帳」
    卡在佇列**,但那個數字明明印在 202204 的明細表前期欄裡。
    這不是資料缺,是我查錯地方。
    """
    path = f"facts/{doc}.json"
    if not os.path.exists(path):
        return None, None
    recs = json.load(open(path, encoding="utf-8")).get(f"{doc}|AC") or []
    best = None
    for r in recs:
        rows = r.get("rows") or []
        col = (_roc_col(rows[0].get("cols") or {}, year) if year and rows
               else r.get("total_col"))
        if not col or not rows:
            continue
        # 備抵損失是減項且名字含「損失」,不是部位;明細表會單獨列一行。
        body = [x for x in rows if "備抵" not in x["name"] and "減：" not in x["name"]]
        tot = sum((x["cols"].get(col) or 0) for x in body)
        mm = sum((x["cols"].get(col) or 0) for x in body if MM_PAT.search(x["name"]))
        if tot and (best is None or tot > best[0]):
            best = (tot, tot - mm)
    return best or (None, None)


def verify_fair_value(rec, doc, tol_rel=0.01, max_gap=0.15):
    """AC 公允價值一格的驗收。

    三道,全部不需要外部真值:

      ① 帳面價值 == facts/ 的 AC 帳面(全帳 或 扣掉貨幣市場)
         兆豐只揭露「債券投資」那段,對的是後者;中信揭露全帳,對的是前者。
         **兩個都不對就是抄錯表** —— 實測這道擋下把等級表當成本表抄的情形。
      ② |公允/帳面 − 1| 要在 max_gap 內。等級表的「合計 vs 第一等級」會做出
         −12%~−27%,大小很像真的長久期,只有這道量級閘門攔得住。
      ③ 兩個數都要是正的整數(公允價值不會是負的)。

    ⚠️ 不要因為「①對不上就放寬 tol」—— 對不上的正常原因是抄到別張表,
    不是四捨五入。實測中信四年逐位元相同,兆豐差 <0.2%。
    """
    fails = []
    book, fair = rec.get("book"), rec.get("fair")
    if not book or not fair or book <= 0 or fair <= 0:
        return f"缺 book 或 fair(book={book!r} fair={fair!r})"
    gap = fair / book - 1
    if abs(gap) > max_gap:
        fails.append(f"公允/帳面 = {gap*100:+.2f}%,超出 ±{max_gap*100:.0f}% —— "
                     f"多半是抄到公允價值等級表(合計 vs 第一等級)")
    yr = str(rec.get("period") or "")[:4]
    bank = docid.bank_of(doc) if docid.is_valid(doc) else None
    # 同一家的**年報個體**才是 AC 總額的來源(半年報沒有那張明細表)。
    src = docid.make(f"{yr}04", bank, docid.SOLO) if yr.isdigit() and bank else None
    full, exdur = ac_totals(src) if src else (None, None)
    # 那一年自己的年報沒有 facts/ 時,退到**本份年報明細表的前期欄** ——
    # 同一份 PDF 但不同張表(投資明細表 vs 公允價值附註),仍然是獨立的第二次抽取。
    if full is None and yr.isdigit():
        full, exdur = ac_totals(doc, year=int(yr))
        if full is not None:
            rec["tie_src"] = f"{doc} 明細表 {int(yr)-1911} 年欄"
    if full is None:
        fails.append(NA_NO_FACTS)
    else:
        ok = [t for t in (full, exdur) if abs(book - t) <= max(1000, t * tol_rel)]
        if not ok:
            fails.append(f"帳面 {book:,} 對不上 facts/{src} 的 AC "
                         f"(全帳 {full:,} / 扣貨幣市場 {exdur:,})")
        else:
            rec["scope"] = "全帳" if abs(book - full) <= max(1000, full * tol_rel) else "扣貨幣市場"
    return fails or None


NA_NO_PNL = "N/A(capital.json 還沒有同期的 pnl 可對帳)"


def verify_pnl(rec):
    """綜合損益表一格的驗收。對帳數字全部印在同一張表上。

      ① 利息收入 − 利息費用 == 利息淨收益
      ② 三條證券損益必須有值。**null 是失敗、0 不是** —— 玉山四份都沒有
         「除列按攤銷後成本衡量之金融資產損益」那一列(它沒處分過 AC),
         那是真的 0;抄不出來才是 null。兩者混在一起就分不出「沒有」與「沒抄」。
      ③ 利息收入必須是正數且量級合理(> 利息淨收益)。

    ⚠️ 不驗「淨利 == 收入 − 費用」:營業費用/呆帳/稅等項目太多,抄漏一項就會
    假性失敗,而那些項目本研究用不到。寧可少一道也不要製造雜訊。
    """
    fails = []
    inc, exp, net = (rec.get("interest_income"), rec.get("interest_expense"),
                     rec.get("net_interest"))
    if inc is None or exp is None or net is None:
        return f"缺利息三欄(收入={inc!r} 費用={exp!r} 淨額={net!r})"
    if inc <= 0 or exp < 0:
        fails.append(f"利息收入 {inc:,} 應為正、利息費用 {exp:,} 應填絕對值")
    if abs(inc - exp - net) > 1:
        fails.append(f"利息收入 {inc:,} − 費用 {exp:,} = {inc - exp:,} != 淨額 {net:,}")
    # ⚠️ 收入與費用抄反時,①的恆等式**仍然成立**(只是全部變號),所以①擋不住。
    #    只有量級/號誌這一道攔得到:銀行的利息淨收益一定是正的,而且費用小於收入。
    if net <= 0 or exp >= inc:
        fails.append(f"利息收入 {inc:,} / 費用 {exp:,} / 淨額 {net:,} 量級不合理"
                     f" —— 收入與費用可能抄反")
    for k, label in (("oci_realized", "OCI已實現"), ("ac_derecog", "除列AC"),
                     ("oci_debt_ovi", "OCI債務工具評價")):
        if rec.get(k) is None:
            fails.append(f"{label} 沒抄到(null)。表上真的沒這一列要填 0,不是 null")
    return fails or None


def verify_interest(rec, doc, pnl_store=None):
    """附註「利息淨收益」一格的驗收。

      ① 各分項加總 == 印出的小計          (表自己印,免費)
      ② 小計 − 費用小計 == 利息淨收益      (同上)
      ③ 證券利息必須真的是分項之一         (擋「自己算一個數填進去」)
      ④ 分桶(AC/OCI)有抄就必須加總 == 證券利息
      ⑤ **跨表:小計 == 綜合損益表的利息收入** ← 最強的一道,而且是精確相等
         實測中信 153,560,890、兆豐 116,639,707 兩邊逐位元相同,不需要容差。

    pnl_store 是 capital.json['pnl'],沒給就跳過 ⑤(記成 N/A,不是綠燈)。
    """
    fails = []
    rows = rec.get("rows") or []
    sub, exp, net = (rec.get("subtotal_income"), rec.get("subtotal_expense"),
                     rec.get("net"))
    sec = rec.get("securities")
    if sub is None or sec is None:
        return f"缺小計或證券利息(小計={sub!r} 證券={sec!r})"
    ac0, oc0 = rec.get("sec_ac"), rec.get("sec_oci")
    amts = [r.get("amount") for r in rows]
    if any(a is None for a in amts) or not amts:
        fails.append("分項有 null 或整個沒抄到,①②③ 都驗不了")
    else:
        if abs(sum(amts) - sub) > 1:
            fails.append(f"分項加總 {sum(amts):,} != 印出的小計 {sub:,}")
        # ③ 證券利息要嘛就是某一個分項,要嘛是 AC/OCI 兩列相加 ——
        #    富邦 202404 的附註**同時印了兩列**(AC 26,023,280 + OCI 5,279,614),
        #    工單要求相加填進 securities。只認「等於單一分項」會把它誤判成造假。
        allowed = list(amts)
        if ac0 is not None and oc0 is not None:
            allowed.append(ac0 + oc0)
        if not any(abs(a - sec) <= 1 for a in allowed):
            fails.append(f"證券利息 {sec:,} 不等於任何一個分項、也不等於 AC+OCI "
                         f"兩列之和 —— 可能是自己算的")
    if exp is not None and net is not None and abs(sub - exp - net) > 1:
        fails.append(f"小計 {sub:,} − 費用 {exp:,} != 利息淨收益 {net:,}")
    ac, oc = rec.get("sec_ac"), rec.get("sec_oci")
    if ac is not None and oc is not None and abs(ac + oc - sec) > 1:
        fails.append(f"分桶 AC {ac:,} + OCI {oc:,} != 證券利息 {sec:,}")
    # 口徑跟著記錄走,不要讓下游自己猜(同 verify_fair_value 的 scope)。
    # 富邦的證券利息只涵蓋 AC 桶,拿它跟別家的 AC+OCI 並列就是兩把尺;
    # 但 202404 那一份它同時印了 AC 與 OCI 兩列,那一格是可比的。
    sec_name = next((r.get("name", "") for r in rows
                     if r.get("amount") is not None and abs(r["amount"] - sec) <= 1), "")
    rec["scope"] = ("AC+OCI" if (ac is not None and oc is not None)
                    else ("僅AC" if "按攤銷後成本" in sec_name else "AC+OCI"))
    # ⑤ 跨表
    hit = None
    for r in (pnl_store or {}).get(doc, []):
        if r.get("period") == rec.get("period") and \
                r.get("basis_norm") == rec.get("basis_norm"):
            hit = r
            break
    if hit is None:
        fails.append(NA_NO_PNL)
    elif hit.get("interest_income") != sub:
        fails.append(f"小計 {sub:,} != 綜合損益表的利息收入 "
                     f"{hit.get('interest_income'):,}")
    return fails or None


def verify_equity(rec, bs=None):
    """權益變動表一格的驗收。

    rec['moves'] 是 [{name, cols:{科目:金額}}, ...];rec['open']/rec['close'] 是各科目餘額。
    bs 給了就多跑一道跨表對帳(期末 == 資產負債表) —— 那是同一份 PDF 內免費的第二來源。

    ⚠️ **null 是失敗,不是 0。** 工單明講「抄不出來就留 null」,所以 null 一定會出現。
    分兩種:`cols` 裡**沒有這個 key** = 這列不動那一欄 = 真的 0;`cols`/`open`/`close`
    裡的值**明寫 null** = 沒抄到 = 驗不了。實測 202204_5841 就是明寫 null,原本在
    `abs(got - cl[k])` 直接 TypeError 讓整份 ERROR —— 比那更糟的是若當 0 吞掉,
    縱向會「剛好」對上而靜靜通過。一律列成 fails 交人審。
    """
    fails = []
    op, cl, mv = rec.get("open"), rec.get("close"), rec.get("moves") or []
    if not op or not cl:
        return "缺期初或期末餘額"

    def _nulls(cols, where):
        """回 cols 裡明寫 null 的欄名,順便記帳。"""
        bad = sorted(k for k, v in cols.items() if v is None)
        if bad:
            fails.append(f"{where}:{'、'.join(bad)} 沒抄到(null),這幾欄驗不了")
        return set(bad)

    for where, d in (("期初", op), ("期末", cl)):
        _nulls(d, where)
    # ① 指撥列橫向加總 == 0(抽屜間搬移,權益總額不變)
    for m in mv:
        holes = _nulls(m["cols"], f"「{m['name']}」")
        s = sum(v for v in m["cols"].values() if v is not None)
        if any(k in m["name"] for k in ("提列", "迴轉", "轉增資", "股票股利")):
            if not holes and abs(s) > 1:
                fails.append(f"「{m['name']}」橫向加總 {s:,} != 0")
        # ①b 任何一列:各欄加總 == 該列印出的「權益總額」欄。
        #     這道擋的是**漏抄一欄** —— 漏抄時縱向仍可能自洽(期初期末都少同一欄),
        #     只有跟表自己印的總額欄比才看得出來。
        if m.get("total") is not None and not holes:
            if abs(s - m["total"]) > 1:
                fails.append(f"「{m['name']}」各欄加總 {s:,} != 印出的權益總額 {m['total']:,}")
    # ② 期初 + 所有變動 == 期末(逐欄)。任一環節是 null 就跳過 —— 上面已記成 fail。
    for k, end in cl.items():
        chain = ([op[k]] if k in op else [0]) + [m["cols"][k] for m in mv if k in m["cols"]]
        if end is None or any(v is None for v in chain):
            continue
        got = sum(v or 0 for v in chain)
        if abs(got - end) > 1:
            fails.append(f"{k}:期初+變動 {got:,} != 期末 {end:,}")
    # ③ 跨表:期末 == 資產負債表
    if bs:
        for k, v in bs.items():
            if cl.get(k) is not None and abs(cl[k] - v) > 1:
                fails.append(f"{k}:權益變動表期末 {cl[k]:,} != BS {v:,}")
    return fails or None


#: 五家對「銀行本身」那一欄的叫法都不同(本行/自行/本公司/個體),但意思是同一個。
#: **一定要正規化再存**,否則網頁上要拿個體比較時會五種 key 各存一半;
#: 而且合併絕不能被歸進來 —— D-SIB 門檻適用合併、債券資料(facts/)是個體,混用結論全錯。
#:
#: ⚠️ 合併的判斷要**先**做,而且不能只認「合併」二字:中信的合併欄印的是
#: 「本行及子行」(實測 202504,2026-08-04)—— 它含「本行」,只比對個體字眼會歸錯邊,
#: 而且四筆數字全對、四道對帳全過,錯得完全看不出來。
SOLO_WORDS = ("個體", "本行", "自行", "本公司", "銀行")
CONSOL_WORDS = ("合併", "子行", "子公司", "及子")


#: 重編:富邦從 202304 那份起,把 2022 的各欄改成**日盛銀行併入後**的數。
#: 實測差距(202204 原始 → 202304 重編後):
#:     利息收入 55,613,358 → 59,797,260 (+7.5%)   淨利 22,796,289 → 23,934,126 (+5.0%)
#:     AC 帳面   773,147,312 → 810,564,489 (+374 億)
#:
#: **一律用原始版(較早那份)** —— 不是因為它比較對,是因為 `data.json` 的富邦 2022
#: 是併前的 7,731 億。兩邊必須同一把尺,否則「浮虧 = 公允 − 帳面」會把併購
#: 造成的規模跳動算成評價變動。
#:
#: ⚠️ 一般情況「後出的年報比較對」,這裡剛好相反,所以要寫死不能靠直覺。
#: 另:memory 的 capital-equity-extraction 曾把這格記成「合併汙染」,那是誤判 ——
#: 原文印的是「111年12月31日(重編後)」。
RESTATED = {("富邦", 2022): "202204"}


def prefer_doc(bank, year, docs):
    """同一年出現在多份年報時,回該用哪一份的 doc 前綴。沒登記就回 None(代表都行)。"""
    want = RESTATED.get((bank, int(year)))
    return next((d for d in docs if want and d.startswith(want)), None)


def norm_basis(raw):
    """回 '個體' | '合併' | None(認不出來 → 交人審,不要猜)。"""
    s = re.sub(r"\s+", "", raw or "")
    if any(w in s for w in CONSOL_WORDS):
        return "合併"
    if any(w in s for w in SOLO_WORDS):
        return "個體"
    return None


def survey(kind, years=("202204", "202304", "202404", "202504")):
    """定位普查。跑之前先看這張表 —— 覆蓋不足就是錨要改,不是往下硬做。"""
    out = {}
    for yr in years:
        for code, name in BANKS.items():
            path = f"pdf_cache/{docid.make(yr, name, docid.SOLO)}.pdf"
            if not os.path.exists(path):
                continue      # 新加入的銀行還沒有那一期的檔,跳過不是錯
            out[f"{yr}|{name}"] = locate(path, kind)
    return out


if __name__ == "__main__":
    import sys
    kind = sys.argv[1] if len(sys.argv) > 1 else "equity"
    res = survey(kind)
    hit = sum(1 for v in res.values() if v)
    one = sum(1 for v in res.values() if v and len(v) == 1)
    for k, v in res.items():
        print(f"  {k:<14} {v if v else '✗'}")
    print(f"\n{kind}:命中 {hit}/{len(res)},唯一頁 {one}/{len(res)}")
