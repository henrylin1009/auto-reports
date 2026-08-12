# -*- coding: utf-8 -*-
"""資本適足 / 盈餘分配的**自動**抄表迴圈 —— 沿用 `fill_auto.py` 的形狀。

    定位(capital.locate)→ 工單(capital.context)→ 模型讀表(fill_auto.READERS)
    → 驗收(capital.verify_*)→ 過的寫 capital.json、不過的進複核佇列

**沒有人工讀表這一步。** 上一輪我把「agent 讀表」做成「我在對話裡逐頁手抄 40 格」,
那是走回頭路 —— `fill_auto.py` 早就把同一件事變成迴圈了,這支只是換一種表。

**這支程式不發明判準。** 讀回來的東西一律交給 `capital.verify_capital` /
`capital.verify_equity`,它們的閘門有注入錯誤的測試證明會失敗(test_capital.py)。
驗不過的**不寫進 capital.json**,寫進 `review/capital_queue.jsonl` 等網頁裁示。

用法:
    python3 capital_auto.py --kind capital            # 20 份年報,資本適足
    python3 capital_auto.py --kind equity --limit 2   # 先跑兩份看看
    python3 capital_auto.py --kind fair_value --reader claude   # AC 的公允價值
    python3 capital_auto.py --kind both --reader claude
"""
import argparse
import json
import os
import time

import capital
import docid
import fill_auto

OUT = "capital.json"
QUEUE = "review/capital_queue.jsonl"
YEARS = ("202204", "202304", "202404", "202504")

# 工單只給候選頁,不給整份 PDF。給整份的實驗(memory: whole-pdf-dump-experiment)
# 逐桶對得很好,但**口徑被無聲替換** —— 那正是這裡最不能出的錯,所以維持逐頁。
MAX_PAGES = 4

_COMMON = """
## 怎麼讀這份工單
下面每一行是 PDF 上的一橫列,格式是 `y座標 | (x座標)文字 (x座標)文字 ...`。
**x 座標就是欄** —— 同一個 x 附近的數字屬於同一欄。這份財報常把兩個口徑
(本行/合併)或兩個年度並排當欄,只看文字順序會抄串行。

## 抄不出來就說抄不出來
看不到、被截斷、不確定是哪一欄,就把該格留 null,或整份回 {"cells": []}。
**猜一個看起來合理的數字是最壞的結果** —— 它會通過肉眼、卡在對帳、浪費一輪。
"""

CAPITAL_RULES = _COMMON + """
## 你在抄什麼
台灣銀行年報的「資本適足性」附註。要抄出每一個口徑、每一個年度的下列數字(單位仟元):

    cet1          普通股權益第一類資本(CET1)
    other_tier1   其他第一類資本
    tier2         第二類資本
    own_funds     自有資本(= 上面三項合計,表上會印)
    rwa           加權風險性資產總額
    rwa_credit / rwa_op / rwa_mkt   信用 / 作業 / 市場風險加權資產(有印才抄)
    cet1_pct      普通股權益比率(%)
    tier1_pct     第一類資本比率(%)
    bis_pct       資本適足率(%)

⚠️ **三個比率是三個不同的數,不要互抄。** 資本適足率(BIS)最大、CET1 比率最小。
實測最常見的錯就是把資本適足率填進 cet1_pct。

## 口徑(basis)一定要跟著數字走
表上的欄名可能是「本行」「自行」「本公司」「個體」(= 銀行自己)或「合併」。
每一組數字都要標 basis,原文照抄。**絕不可以把合併的 CET1 配本行的 RWA** ——
四欄交錯的版面(合併|本行|合併|本行)特別容易取錯。

## 年度(period)
一張表通常印當期與前期兩欄,兩個都要抄成獨立的 cells 項目。
period 用西元年底,例如民國114年12月31日 → "2025-12-31"。

## 輸出
只輸出一個 JSON 物件,不要說明文字、不要 markdown 圍欄:

{"cells": [{"basis": "本行", "period": "2025-12-31", "cet1": 290350341,
            "other_tier1": 0, "tier2": 0, "own_funds": 0, "rwa": 2406508371,
            "rwa_credit": null, "rwa_op": null, "rwa_mkt": null,
            "cet1_pct": 12.07, "tier1_pct": 12.07, "bis_pct": 14.32}]}

金額一律整數、去逗號;括號代表負數。比率是浮點數,不要帶 %。
"""

EQUITY_RULES = _COMMON + """
## 你在抄什麼
「權益變動表」。要抄出每個年度的:期初餘額、當年所有變動列、期末餘額。

## 欄名一律翻成這幾個固定 key
    股本 / 資本公積 / 法定 / 特別 / 未分配 / 其他權益 / 庫藏股 / 其他
(「法定盈餘公積」→ 法定,「特別盈餘公積」→ 特別,「未分配盈餘」→ 未分配。
 其他權益底下的兌換差額、FVOCI 評價等子欄先合併成一個「其他權益」。)

⚠️ **「權益總額」那一欄不要放進 cols**,放進去會被重複計。它填在該列的 `total`。

## 每一列都要抄,包含指撥
提列法定盈餘公積、特別盈餘公積提列/迴轉、現金股利、股票股利、本期淨利、
其他綜合損益 —— 一列都不能漏。指撥列是「從未分配搬到公積」,所以是**一加一減**:
只記公積增加、漏記未分配減少,是實測最常見也最難看出來的錯。

## 輸出
只輸出一個 JSON 物件:

{"years": [{"period": "2024",
            "open":  {"股本": 147962186, "法定": 127316868, "未分配": 40812502},
            "moves": [{"name": "本期淨利", "cols": {"未分配": 49423933}, "total": 49423933},
                      {"name": "提列法定盈餘公積",
                       "cols": {"法定": 12243738, "未分配": -12243738}, "total": 0}],
            "close": {"股本": 158016512, "法定": 139560606, "未分配": 49423933}}]}

period 用該年度的西元年(變動所屬年度)。金額整數、去逗號,減項用負號。
"""

FV_RULES = _COMMON + """
## 你在抄什麼
附註「金融工具之公允價值 —— 非以公允價值衡量者」底下那張小表。開場白是
「除下表所列(示之項目)外…帳面金額趨近其公允價值」。只要「按攤銷後成本衡量」
那一列的 book(帳面價值/帳面金額)與 fair(公允價值)。

## ⚠️ 同一頁上有兩張表,長得幾乎一樣,只有一張是對的
緊接在正表後面的是**公允價值等級表**,那張的同一列也叫「按攤銷後成本衡量之
債務工具投資」。抄錯會做出 −12% ~ −27% 的假浮虧 —— 數量級很像真的長久期,
肉眼完全看不出來。**五家的等級表都印在正表的同一頁,所以一定要自己分辨:**

    正表   欄名是「帳面價值/帳面金額」與「公允價值」
    等級表 欄名是「合計」「第一等級」「第二等級」「第三等級」  ← 不要抄這張

看到「合計」或「第X等級」就是抄錯表了。

## 欄數有兩種,不要假設
    2 欄  一個年度一張表,兩個年度分開印(中信/兆豐/富邦)
          → 「按攤銷後成本衡量之債務工具投資 $ 875,353,432 $ 848,821,775」
    4 欄  兩個年度並排在同一列(國泰/玉山)
          → 表頭「114年12月31日 113年12月31日 / 帳面價值 公允價值 帳面價值 公允價值」
             那一列四個數字依序是 當期帳面、當期公允、前期帳面、前期公允

x 座標是唯一可靠的分欄依據,不要照文字順序猜。

## 科目名原文照抄到 item
五家叫法不同,而且指的範圍不一樣,不要自己統一:
    「按攤銷後成本衡量之債務工具投資」      = AC 全帳(含可轉讓定期存單那些)
    「按攤銷後成本衡量之金融資產－債券投資」 = 只有債券那段
兩種都對,照抄原文即可,後面驗收會自己判是哪一種。

## 口徑與年度
basis 原文照抄(本行/自行/本公司/個體/合併)。同一份年報會印當期與前期兩個年度,
**兩個都要抄成獨立的 cells 項目**。period 用西元年底,民國114年12月31日 → "2025-12-31"。

## 輸出
只輸出一個 JSON 物件:

{"cells": [{"basis": "本行", "period": "2025-12-31",
            "item": "按攤銷後成本衡量之債務工具投資",
            "book": 886706260, "fair": 868442291}]}

金額一律整數、去逗號。這張表沒有這一列就回 {"cells": []}。
"""

PNL_RULES = _COMMON + """
## 你在抄什麼
「綜合損益表」(四大報表之一,不是附註)。每一個年度欄都要抄成獨立的 cells 項目。
工單通常給兩頁 —— 表跨頁,淨利與其他綜合損益那段常在次頁。

    interest_income   利息收入            (科目代碼多半是 41000)
    interest_expense  利息費用            **填絕對值,不要帶負號或括號**
    net_interest      利息淨收益
    oci_realized      透過其他綜合損益按公允價值衡量之金融資產已實現損益
    ac_derecog        除列按攤銷後成本衡量之金融資產(或債務工具投資)損益
    oci_debt_ovi      透過其他綜合損益按公允價值衡量之債務工具評價損益(在 OCI 段裡)
    net_income        本期淨利

## ⚠️ 科目代碼五家不同,一律認中文品名
中信印 49310、兆豐印 43100,指的是同一項(OCI 已實現損益)。**不要用代碼對應。**

## ⚠️ 「表上沒有這一列」要填 0,「我抄不出來」才填 null
玉山四份年報都沒有「除列按攤銷後成本衡量之金融資產損益」那一列(它沒處分過 AC)
—— 那是真的 0。兩者混用會讓驗收分不出「沒有」與「沒抄到」。

## 括號是負數
oci_debt_ovi 常是負的(升息年)。ac_derecog 也可能是負的。照號誌抄,
**只有 interest_expense 例外,填絕對值**。

## 輸出
只輸出一個 JSON 物件:

{"cells": [{"basis": "個體", "period": "2025",
            "interest_income": 153560890, "interest_expense": 82932181,
            "net_interest": 70628709, "oci_realized": 2965486,
            "ac_derecog": 12422, "oci_debt_ovi": 499952,
            "net_income": 57298147}]}

period 用該年度的西元年(民國114年度 → "2025")。basis 這幾份都是個體財報,
填表頭寫的(個體/本行/本公司);沒寫就填「個體」。金額整數、去逗號。
"""

INT_RULES = _COMMON + """
## 你在抄什麼
附註「利息淨收益」那張表 —— 利息收入的**分項**。每個年度欄抄成獨立的 cells 項目。

工單可能給到三種頁,請自己分辨:
  1. 附註「利息淨收益」正表(必抄)。有些家印「(接次頁)」把利息費用切到次頁。
  2. 附表「利息收入明細表」(國泰/玉山才有)。它把證券利息**再拆成 AC 與 OCI**,
     抄到 sec_ac / sec_oci。它只有當期一個年度。
  3. 只寫「請參閱附註六(…)」的佔位頁(中信/兆豐) —— 那不是表,略過。

## 要抄的欄
    rows              利息收入的每一個分項 [{"name": 原文, "amount": 金額}, ...]
    securities        上面那些分項裡,**證券利息那一列的金額**
    subtotal_income   利息收入小計
    subtotal_expense  利息費用小計   **填絕對值**
    net               利息淨收益
    sec_ac / sec_oci  證券利息拆成 AC / OCI 兩桶(只有附表有;沒有就填 null)

## ⚠️ 證券利息那一列,五家名字不同而且**範圍不一樣**
    有價證券息 (中信/國泰)            = AC + OCI 全部
    投資有價證券利息收入 (兆豐/玉山)    = 同上
    按攤銷後成本衡量之債務工具投資利息 (富邦) = **只有 AC 桶**
照原文抄進 rows 的 name,securities 填該列金額。**不要自己換算或合併。**

## ⚠️ securities 必須真的是 rows 裡的某一項
驗收會檢查。看到兩列都像證券(富邦 202404 同時印了 AC 與 OCI 兩列)時:
securities 填**兩列相加**、同時把兩列分別填進 sec_ac / sec_oci。

## ⚠️ 有一種頁絕對不要抄
富邦另有一張同名的「利息收入明細表」(明細表十二),合計只有 16 億,
而它全行的利息收入是 1,186 億 —— 那是子分部的表。**看到合計與正表差一個
數量級就是抄錯表了**,那一格留 null。

## 輸出
只輸出一個 JSON 物件:

{"cells": [{"basis": "個體", "period": "2025",
            "rows": [{"name": "放款息", "amount": 106086649},
                     {"name": "有價證券息", "amount": 31155757}],
            "securities": 31155757, "subtotal_income": 153560890,
            "subtotal_expense": 82932181, "net": 70628709,
            "sec_ac": null, "sec_oci": null}]}

## 口徑(basis)
這幾份都是**個體**財務報告。填表頭/表名寫的(個體/本行/本公司/自行);
**表上沒寫就填「個體」,不要填「合併」也不要留 null。**
實測富邦三份因為附註標題沒印口徑,被填成「合併」與 null,結果整份卡在對帳。

period 用西元年。金額整數、去逗號。
"""

RULES = {"capital": CAPITAL_RULES, "equity": EQUITY_RULES, "fair_value": FV_RULES,
         "pnl": PNL_RULES, "interest": INT_RULES}
KINDS = tuple(RULES)


def build_prompt(kind, path, pages):
    lines = [RULES[kind], "\n## 來源頁"]
    for p in pages:
        lines.append(f"\n### 第 {p} 頁")
        for y, toks in capital.context(path, p):
            lines.append(f"{y:>4} | " + " ".join(f"({x}){t}" for x, t in toks))
    return "\n".join(lines)


def judge(kind, doc, data):
    """回 [(rec, fails), ...]。fails 為 None 代表這一項通過。

    判準全部來自 capital.verify_* —— 這裡不加也不減。
    doc 只有 fair_value 用得到(要拿它去 facts/ 對帳)。
    """
    if data is None:
        return None
    items = data.get("years") if kind == "equity" else data.get("cells")
    if items is None:
        return None
    # interest 的第 ⑤ 道是跨表對帳,要拿已經驗過的 pnl 來比。
    # **必須讀 capital.json(只放過驗收的),不可以讀佇列** —— 拿沒過驗收的當真值
    # 對帳,等於用一個可能錯的數去背書另一個數。
    pnl_store = _load(OUT, {}).get("pnl", {}) if kind == "interest" else None
    out = []
    for rec in items:
        if kind == "equity":
            fails = capital.verify_equity(rec)
        else:
            rec["basis_norm"] = capital.norm_basis(rec.get("basis"))
            if kind == "capital":
                fails = capital.verify_capital(rec)
            elif kind == "pnl":
                fails = capital.verify_pnl(rec)
            elif kind == "interest":
                fails = capital.verify_interest(rec, doc, pnl_store)
            else:
                fails = capital.verify_fair_value(rec, doc)
            if rec["basis_norm"] is None:
                fails = (fails or []) + [f"口徑認不出來:{rec.get('basis')!r}"]
        out.append((rec, fails))
    return out


def run_doc(kind, doc, reader):
    """跑一份 PDF。回 dict:{doc, kind, pages, passed, queued, outcome}"""
    path = f"pdf_cache/{doc}.pdf"
    pages = capital.locate(path, kind)
    if not pages:
        return {"doc": doc, "kind": kind, "outcome": "NO_PAGE",
                "reason": "定位不到候選頁(可能是掃描檔無文字層)"}
    pages = pages[:MAX_PAGES]
    raw = fill_auto.READERS[reader](build_prompt(kind, path, pages))
    data = fill_auto._parse_json(raw)
    res = judge(kind, doc, data)
    if res is None:
        return {"doc": doc, "kind": kind, "pages": pages, "outcome": "PARSE_FAIL",
                "reason": "模型輸出不是預期的 JSON", "raw": raw[:2000]}
    if not res:
        return {"doc": doc, "kind": kind, "pages": pages, "outcome": "EMPTY",
                "reason": "模型說這幾頁沒有可抄的表", "raw": raw[:2000]}
    ok = [r for r, f in res if not f]
    bad = [{"rec": r, "fails": f} for r, f in res if f]
    return {"doc": doc, "kind": kind, "pages": pages, "passed": ok, "queued": bad,
            "outcome": "PASS" if not bad else ("FAIL" if not ok else "PARTIAL")}


# ── 落地 ──────────────────────────────────────────────────────────
# capital.json 的形狀:{kind: {doc: [rec, ...]}}。**只放驗過的**。
# 驗不過的一律進 QUEUE 給網頁人審 —— 不硬填、也不悄悄放寬容差。

def _load(path, default):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return default


def apply(results):
    store = _load(OUT, {})
    qn = 0
    os.makedirs("review", exist_ok=True)
    with open(QUEUE, "a", encoding="utf-8") as q:
        for r in results:
            kind, doc = r["kind"], r["doc"]
            for rec in r.get("passed") or []:
                store.setdefault(kind, {}).setdefault(doc, [])
                # 同 doc 同 basis 同 period 只留一份(重跑會覆蓋,不會長出重複)
                key = (rec.get("basis_norm") or rec.get("basis"), rec.get("period"))
                store[kind][doc] = [x for x in store[kind][doc]
                                    if (x.get("basis_norm") or x.get("basis"),
                                        x.get("period")) != key]
                store[kind][doc].append(rec)
            for item in r.get("queued") or []:
                q.write(json.dumps({"doc": doc, "kind": kind, "pages": r.get("pages"),
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    **item}, ensure_ascii=False) + "\n")
                qn += 1
            if r["outcome"] in ("NO_PAGE", "PARSE_FAIL", "EMPTY"):
                q.write(json.dumps({"doc": doc, "kind": kind, "pages": r.get("pages"),
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "fails": [r["reason"]], "rec": None,
                                    "raw": r.get("raw")}, ensure_ascii=False) + "\n")
                qn += 1
    json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return qn


def main(argv=None):
    ap = argparse.ArgumentParser(description="資本適足 / 盈餘分配自動抄表")
    ap.add_argument("--kind", default="capital", choices=KINDS + ("both",))
    ap.add_argument("--reader", default=os.environ.get("FILL_READER", "claude"),
                    choices=sorted(fill_auto.READERS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--docs", nargs="*", help="只跑指定的 doc(例:202504_中信_個體)")
    ap.add_argument("--dry", action="store_true", help="不寫 capital.json / 佇列")
    a = ap.parse_args(argv)

    # 只跑真的有檔的 —— `config.BANKS` 可能含還沒有任何財報的新銀行,
    # 對它們排工作只會排出一堆「檔案不存在」。
    docs = a.docs or [d for y in YEARS for b in capital.BANKS.values()
                      if os.path.exists(f"pdf_cache/{(d := docid.make(y, b, docid.SOLO))}.pdf")]
    kinds = ("capital", "equity") if a.kind == "both" else (a.kind,)
    jobs = [(k, d) for k in kinds for d in docs][:a.limit or None]

    print(f"待跑 {len(jobs)} 份  READER={a.reader}" + ("  (乾跑)" if a.dry else ""))
    results, tally, t0 = [], {}, time.time()
    for n, (k, d) in enumerate(jobs, 1):
        print(f"[{n}/{len(jobs)}] {d} | {k} ...", end=" ", flush=True)
        try:
            r = run_doc(k, d, a.reader)
        except Exception as e:                                   # noqa: BLE001
            r = {"doc": d, "kind": k, "outcome": "ERROR",
                 "reason": f"{type(e).__name__}: {e}"}
        results.append(r)
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
        print(f'{r["outcome"]}  過 {len(r.get("passed") or [])} '
              f'待審 {len(r.get("queued") or [])}')
        for item in (r.get("queued") or [])[:3]:
            print(f'        ✗ {item["rec"].get("basis", "")} '
                  f'{item["rec"].get("period", "")}: {"; ".join(map(str, item["fails"]))[:120]}')
        if r.get("reason"):
            print(f'        {r["reason"][:160]}')

    print("\n" + "─" * 52)
    for k in sorted(tally, key=lambda x: -tally[x]):
        print(f"  {k:10s} {tally[k]}")
    print(f"  耗時 {time.time() - t0:.0f} 秒")
    if not a.dry:
        qn = apply(results)
        print(f"\n已寫入 {OUT};{qn} 項進 {QUEUE} 等人審。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
