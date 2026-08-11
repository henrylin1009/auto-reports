# 施工單 —— Phase A 的 R / C0 / C1

> 給執行者(Sonnet)。規格見 `docs/plan_clean_core.md`,**衝突時以本單為準,
> 不確定就停下來問,不要自行裁示。**
>
> 本單只做三步:**R(裁定測試)→ C0(契約與錨值)→ C1(判定層)**。
> C2 以後不在本單範圍,**做完 C1 就停下來回報**。
>
> R 階段有**四個**裁定要落成測試:R1 發布單位、R2 G9/G17 三態、R3 Ring 分層、
> **R4 分類不得驅動 expand**(使用者 2026-07-27 親自裁示,見 §R.5)。

---

## 0. 先讀這段(硬性約束)

### 0.0 使用者親自裁示的七條鐵則(2026-07-27)

**這七條是使用者的原話,不是我的整理。任何一條與其他文件衝突,以這七條為準。**

| # | 鐵則 | 本單範圍? |
|---|---|---|
| 1 | **classification 不能觸發自動 expand** | ✅ R.5 / R.6 要落成測試 |
| 2 | **只有來源／算術／reconciliation 失敗可自動 expand** | ✅ 同上。⚠️ 但 reconciliation(第 3 道)今天切不開,本單裁定為**暫不觸發**,理由見 §R.5 |
| 3 | **classification unknown 必須保存 facts、建立 Decision、送 review** | ❌ Phase B。**本單不得實作,但也不得寫出擋住它的設計** |
| 4 | **review 必須支援確認、退回、人工要求 expand 三種處置** | ❌ Phase B。同上 |
| 5 | **現有 SYN 僅在批准遷移與 reference 建立後,才能成為 CONFIRMED 的來源** | ❌ Phase B(B1)。**本單不得預設 SYN == CONFIRMED** |
| 6 | **不修 `transcribe.py` 那條未呼叫的退化路徑;只記錄為獨立技術債** | ✅ 見 §R.5 與回報第 5 段 |
| 7 | **完成 R/C0/C1 後,跑完本單列出的所有注入、等價與回歸測試,再一次性回報** | ✅ 見 §回報格式 |

第 2 條有一個必須講清楚的落差:使用者允許 reconciliation 失敗觸發 expand,
但實測顯示第 3 道(`check_cross`)**今天沒有可用的純算術版本**(§R.5)。
所以本單的白名單先不含它 —— 這是**保守收緊,不是違背裁示**,
代價已量 = 0(`EXPAND_TRUTH` 11 格沒有一格靠它觸發)。
日後第 3 道被切成「算術部分 / 配對部分」時,算術部分應當加回白名單。
**若你認為這個落差不該由本單自行決定,停下來問使用者,不要自己加回去。**

第 3、4、5 條雖然不在本單,但**會約束你在 R/C0/C1 寫下的介面**:

- `core/expand_policy.py` 的回傳要留得住「這格要送 review」這個結論
  (至少 `may_expand()` 的理由字串要能區分「算術失敗」與「分類未知」)。
- `core/contracts.py` 的 `Record` / `Row` **不准把「分不出桶」寫成不合法** ——
  契約層只管來源、結構、型別,分類是別層的事。
- 任何地方**不准出現「SYN 命中 ⇒ 已確認」的假設**,包括註解與變數命名。

### 0.1 絕對不准做

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` | 這些是已驗證的底層能力。**唯一合法的重用方式是 `import`** |
| 刪除任何檔案 | 退場有獨立的驗收條件,不在本單 |
| 跑 `build.py --write` / `bridge_v2.py` / `bridge_v3.py --write` | 會動到已發布的 `data.json` |
| 修改 `data.json` `facts/*.json` `snapshots/*` | `facts/` 在本單裡是**唯讀輸入**,一個 byte 都不准變 |
| 呼叫任何模型 API | 使用者已定案:抄列由外部 agent 做,程式不呼叫 |
| 「順手」重構、改名、整理、補型別 | 等價閘門會分不出差異來自搬家還是整理 |
| 為了讓測試變綠而放寬測試 | 測試紅了要回報,不是改判準 |

### 0.2 環境

```bash
source .venv/bin/activate
```

沒有 pytest。測試是可執行腳本,`python3 test_x.py`,exit 0 = 綠。

**現有九支測試(每一步結束都要全綠)**:

```bash
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done
```

`test_build.py` **目前跑不完 2 分鐘**(已知,原因就是 C1 要解的問題)。
R / C0 階段不要等它;C1 完成後它應該變快,那時再跑。

### 0.3 已量到的基準(不要重新推導,直接用)

```
facts:          36 格 / 15 份 PDF / 583 列 / 75 個相異列名 / 20 個相異 group
results.build:  56.5 秒(36 格)。只餵錨值時 0.003 秒,verdict 逐位元組相同
發布單位:       v3 57 / v2 326(其中 315 是「facts 尚未抄錄」)/ 衝突 8
四元組→三元組:  wide 採 v3 的三元組 31 個,其中 wide+wide_cost 都合格 24 個
data vs wide:   31 個已採用單位、93 個 1:1 比對點,不一致 21 處
擴張使用率:     36 格裡只有 2 格用過(202504_5835 的 AC 與 Trading,level=2 retries=2)
EXPAND_TRUTH:   11 格,10 格需要擴頁 —— ①②算術驅動 5 格、⑤分類驅動 5 格、③跨表 0 格
```

---

## 步驟 R —— 裁定測試(先紅後綠)

**目的**:把 `plan_clean_core.md` §1 的三個裁定寫成可執行的測試。
**這一步不改任何行為**,只新增檔案。

### R.1 `core/units.py`(新檔,純函數,Ring 1)

發布單位的判定邏輯。**只寫純函數,不做 IO,不 import build/bridge。**

```python
# core/units.py
"""發布單位的判定。atomic unit = (期別, 銀行, 類別) —— 見 plan_clean_core.md §1 R1。

**採用是 all-or-nothing**:一次切換該格的每一個投影(data / wide / wide_cost)。
四元組(帶口徑)是錯的切法 —— data 區塊也是同一格的投影,四元組管不到它,
實測會在同一頁上顯示 419.67 億與 788 億兩個數字。
"""
PROJECTIONS = ("data", "wide", "wide_cost")

# 回退的三種狀態。**不准合併成一種** —— 見 R2。
NOT_YET       = "NOT_YET"        # v3 對這格沒有意見(facts 未抄錄)
BLOCKED       = "BLOCKED"        # v3 抄了但六道檢查沒過
CONTRADICTION = "CONTRADICTION"  # v3 判該口徑文件裡不存在,而 v2 有數字 → 需人工裁示
ADOPTED       = "ADOPTED"

def projections_present(snapshot, cell, cls) -> set[str]:
    """快照對 (cell, cls) 已經填了哪些投影。回傳 PROJECTIONS 的子集。"""

def adopt(verdict, snapshot, cell, cls, holdout_keys, ledger) -> dict:
    """回傳 {"provenance": "v3"|"v2", "state": ..., "reason": str, "projections": [...]}。

    採用 v3 的條件(全部成立):
      ① verdict 存在且 pass
      ② 快照對該格已填的**每一個**投影,v3 都供應得出來
      ③ 七桶齊全
      ④ key 不在 holdout
    否則整格留 v2,一個投影都不動,並依上面三種狀態分類回退原因。

    ratchet(R2):ledger 記為 v3 的 unit 若這次不合格 → 回傳 state=CONTRADICTION
    且 reason 標明「已發布過 v3 卻不再合格」。呼叫端要讓 build 失敗,不是靜靜回退。
    """
```

### R.2 `test_units.py`(新檔)—— 合成輸入的單元測試

用**手寫的假 verdict / 假快照**,不碰真實資料。必須包含這些注入測試
(每一條都要「注入錯誤 → 測試失敗」才算數):

| # | 命題 | 注入什麼 |
|---|---|---|
| U1 | 快照有 `wide_cost` 而 v3 供不出 → 整格 v2,`wide` 也不採用 | 讓 `adopt` 回傳 v3 → 必須紅 |
| U2 | 快照沒填 `wide_cost` 而 v3 只有 `wide` → 可以採用 | — |
| U3 | 六道未過 → `BLOCKED`,不是 `NOT_YET` | 把 BLOCKED 併成 NOT_YET → 必須紅 |
| U4 | verdict 不存在 → `NOT_YET` | — |
| U5 | v3 pass 但某口徑 null 且快照該投影有值 → `CONTRADICTION` | 歸成 NOT_YET → 必須紅 |
| U6 | 七桶缺一 → 不採用 | — |
| U7 | key 在 holdout → 永不採用(即使全部合格) | — |
| U8 | ledger 記為 v3 但這次不合格 → `CONTRADICTION` 且 reason 含「已發布過」 | 靜靜回退 v2 → 必須紅 |

### R.3 `test_rulings.py`(新檔)—— 對**真實資料**的基準與棘輪

這支不是普通測試,是**棘輪(ratchet)**:記錄今天的真實數字,**只准變好,不准變壞**。
有些命題今天本來就該是紅的(要到 C4 才會綠),所以它印基準表、只在數字**惡化**時 exit 1。

```
BASELINE = {
    # 命題                              今天      目標    何時該達成
    "mixed_provenance_cells":            0,       0,      # 已經是 0,不准變大
    "data_wide_inconsistencies":         21,      0,      # C4(data 改成同源投影)
    "adopted_units_triple_rule":         24,      24,     # 三元組規則下的採用數
    "conflicts_classified_as_NOT_YET":   8,       0,      # C4(三態分類上線)
}
```

三條真實資料的計算方式(照抄,不要自己發明):

1. **`data_wide_inconsistencies`**:對 `preview/build_manifest.json` 裡
   provenance == v3 且結尾 `|wide` 的單位,取 1:1 對得上的三個桶
   `{"公債":"GB", "公司債":"公司債", "金融債":"金融債"}`,
   比 `preview/data.json` 的 `data[cell][cls][舊桶]` 與 `wide[cell][f"{cls}_{新桶}"]`,
   `abs(差) > 1` 算一處。
   ⚠️ **不要把「其他」納入比對** —— `data` 是債券口徑,不含股票與貨幣市場,
   對進去會量出 51 處假不一致。
2. **`adopted_units_triple_rule`**:用 `core.units.adopt` 對真實 verdict + 快照重算,
   數 provenance == v3 的三元組。應為 24。
3. **`conflicts_classified_as_NOT_YET`**:manifest 的 8 處 `conflicts`,
   用 `core.units.adopt` 重跑後有幾個被歸成 `NOT_YET`。應為 8(今天全錯),目標 0。

### R.4 `test_ring.py`(新檔)—— R3 的分層測試

```
Ring 1(純):core.contracts / core.classify / core.reconcile / core.publish / core.units
Ring 0(不純):core.store 的 anchors 產生器 / core.ingest / resolve
```

三條(C0 之前先寫,`core.reconcile` 還不存在時該項先 skip 並印出 SKIP):

1. `test_ring1_no_pdf`:把 `pdf_cache/` 與 `state/` **暫時改名**,跑 Ring 1 的
   verify/build 路徑 → 要能跑完且輸出逐位元組相同。**測試結束一定要改回來**
   (用 try/finally,失敗也要還原)。
2. `test_ring1_imports`:`import core.reconcile` 之後斷言
   `"pypdfium2" not in sys.modules` 且 `"requests" not in sys.modules`。
3. `test_ring1_deterministic`:同輸入連跑兩次,payload 逐位元組相同
   (時鐘只准出現在 manifest,不准進 `data.json`)。

### R.5 `core/expand_policy.py`(新檔,純函數)—— R4 的裁定

**這是使用者親自裁示的規則,不准打折、不准加「但是」分支。**

> **分類狀態不得驅動 PDF expand。** `UNCLASSIFIED` 或 `rules.propose()` 提不出候選,
> **不能**推論成「頁沒找全」或「可能是小計」—— 它同樣可能只是個新的真實科目。
> 只有**來源 / 表內算術 / 跨表 reconciliation** 失敗才有資格觸發 expand。
> 分類未知一律走「facts 歸檔 + review queue」,最多在工單顯示提示,
> **不得消耗重試預算。**

實證(不要重新推導,直接寫進 docstring):`rules.propose()` 回 None 的名字裡,
玉山「透過其他綜合損益按公允價值衡量之權益/債務工具投資」是**小計**,
兆豐「不動產投資信託受益證券」與玉山「國外機構發行債券」是**真科目**(後來人工裁示為
資產基礎 / 公債)。同一個訊號指向相反處置 → 用它路由等於擲硬幣。

```python
# core/expand_policy.py
"""擴頁觸發訊號的白名單。**不在名單上的一律不觸發,也不消耗重試預算。**"""

# 判準是「哪一道檢查失敗」,**不是比對錯誤訊息字串**。
# (fill._taxonomy_gap 已經踩過訊息比對的坑:同一個根因會在第 3 道長出第二個症狀。)
TRIGGERS = {
    "source",           # source_page 不在候選頁集合內
    "check_identity",   # ①② sum(葉列 total_col) != printed_total
    "check_anchor",     # ④  printed_total != 錨
    "check_col_totals", # ⑥  逐欄合計對不上
}
NEVER = {
    "check_buckets",    # ⑤ 純分類
    "check_cross",      # ③ 混合訊號,今天切不開(見下)
}

def may_expand(failed_checks: set[str]) -> tuple[bool, str]:
    """→ (要不要擴頁, 理由)。理由要能直接印在工單上給人看。"""

def consumes_budget(failed_checks: set[str]) -> bool:
    """分類造成的失敗**不消耗重試預算**。"""
```

**⚠️ 為什麼第 3 道(`check_cross`)也排除 —— 已實測,不要自己再試一次:**

我試過用「`check_cross(recs, bk=None)` 通過但 `bk=buckets` 失敗 ⇒ 純分類造成」
把它切開。**那條路徑一跑就炸**:

```
transcribe.py:337  _by_bucket(a, b, None) → bad 回成 list
transcribe.py:293  _merged() 當它是 dict → AttributeError: 'list' object has no attribute 'items'
```

而且設計上也不成立:29 格適用第 3 道,其中 **17 格兩份 record 口徑不同**,
對齊本身就需要分桶知識(`transcribe.align` 的 docstring 自己說「這層相依是真的」)。
→ **保守裁定:③ 不觸發 expand。代價已量 = 0**(EXPAND_TRUTH 11 格沒有一格靠它)。

**這個 AttributeError 是潛伏 bug,本單不准修**(`transcribe.py` 在禁改清單裡,
且今天無人呼叫)。在回報裡列出來就好。

### R.6 `test_expand_policy.py`(新檔)

| # | 命題 | 注入什麼 |
|---|---|---|
| X1 | 只有 ⑤ 失敗 → 不擴頁 | 把 `check_buckets` 加進 `TRIGGERS` → **必須紅** |
| X2 | 只有 ③ 失敗 → 不擴頁 | 把 `check_cross` 加進 `TRIGGERS` → **必須紅** |
| X3 | ① 失敗 → 擴頁 | 把它從 `TRIGGERS` 拿掉 → 必須紅 |
| X4 | ⑤ 失敗時 `consumes_budget()` 為 False | 改成 True → 必須紅 |
| X5 | ① + ⑤ 同時失敗 → 擴頁(理由要指名是 ①,不是 ⑤) | 理由字串裡出現 `check_buckets` → 必須紅 |
| X6 | **算術家族行為不變**:對 M4 的 5 格(國泰 202102 Trading、中信 202401/202501/202502 AI1 OCI、中信 202502 AI3 OCI),斷言其第一層失敗訊號落在白名單內 | — |
| X7 | **分類家族確實停住**:對玉山 5 格(202102 AI3、202102 AI2、202302、202402、202502 的 OCI),斷言 `may_expand() == False` | — |

X6 / X7 用 `locate.EXPAND_TRUTH` 當清單來源,**不要自己硬編一份**。
這兩條需要知道「第一層抄錄會失敗在哪一道」,而 C3 之前沒有 ingest ——
所以 R 階段先用**手寫的 fixture**(把玉山 202102 的兩列小計寫成合成 record:
`16,018,428 + 271,692,749 = printed_total = 錨 287,711,177`,兩列 `bucket()` 皆 None),
驗證 policy 的判斷。真實端到端驗證留到 C3。

### R 的驗收(回報時要附這些)

```
[ ] core/units.py 存在,零 IO,不 import build/bridge/locate
[ ] core/expand_policy.py 存在,純函數,零 IO
[ ] test_units.py 綠,且 U1/U3/U5/U8 各自「注入錯誤 → 紅」的實測輸出各貼一段
[ ] test_expand_policy.py 綠,且 X1/X2/X4 各自「注入 → 紅」的實測輸出各貼一段
[ ] test_rulings.py 跑得出基準表,四個數字與 §0.3 一致
[ ] test_ring.py 三條可跑(reconcile 未存在的項印 SKIP)
[ ] 九支既有測試全綠
[ ] git status:只有新增檔案,零修改
```

---

## 步驟 C0 —— 契約與錨值固化

### C0.1 `core/contracts.py`

資料型別 + 邊界 parse。**磁碟格式與現行 `facts/` 逐欄相同,一個欄位都不准加減。**

```python
REQUIRED_REC = ("doc","class","source_page","source_kind","total_col","printed_total","rows")
OPTIONAL_REC = ("printed_totals","note","_by")
REQUIRED_ROW = ("name","cols")
OPTIONAL_ROW = ("group",)
```

- `parse_cell(key, raw_records) -> Cell`,不合格就 raise,**不修資料**。
- `dump_cell(cell) -> raw`,要滿足 `dump_cell(parse_cell(x)) == x`(round-trip 測試)。
- `validate(cells)` 直接轉呼叫 `facts.validate` 當**第二 oracle**,兩者結果必須一致。

### C0.2 `core/store.py` + `anchors/`

`anchors/{doc}.json` 的 schema(照這個寫,不要自創欄位):

```json
{
 "doc": "202404_5843_AI3",
 "pdf_sha256": "…",
 "bs_page": 12,
 "located_by": "locate.locate",
 "cells": {
   "Trading": {"amount": 9082587, "pages": [31, 135]},
   "OCI":     {"amount": 41701384, "pages": [33]}
 }
}
```

函式:

| 函式 | Ring | 說明 |
|---|---|---|
| `build_anchors(doc)` | 0 | 呼叫 `locate.locate()`,寫 `anchors/{doc}.json`。**不改 locate** |
| `load_anchors(doc)` | 1 | 只讀 json。**不准 import pypdfium2,不准開 PDF** |
| `anchor_of(doc, cls)` | 1 | → int 或 None |
| `verify_anchors()` | 0 | 重新推導全部並逐項比對,不符就列出差異 |
| `load_facts()` / `save_facts()` | 1 / 0 | 包 `facts.load`/`facts.save` |
| `sha256_of(*paths)` | 1 | 內容雜湊 |

**過期防護(必做,這是 C0 引入的唯一新風險)**:
`load_anchors()` 要比對 `pdf_sha256` 與現場 PDF;**PDF 換了就 raise 拒絕使用,
不准自動重算**。若 `pdf_cache/` 不存在(Ring 1 測試會把它改名),則跳過比對直接用快取
—— 這是刻意的:純層本來就不該依賴 PDF 在不在。

### C0.3 CLI 骨架

```bash
python3 -m core anchors            # 對 facts/ 涵蓋的 15 份 PDF 產生 anchors/
python3 -m core anchors --verify   # 重新推導並逐項比對
python3 -m core status             # 印:facts 格數 / anchors 份數 / 覆蓋率
```

`core/cli.py` 只做參數分派,零業務邏輯。

### C0.4 `docs/guardrails.md`

建立護欄清冊,把 `plan_clean_core.md` §5.2 的 G1–G20 逐條抄進去,四欄:
**護欄 / 實測案例 / 證明它會失敗的測試 / 新核心誰擁有**。
「新核心誰擁有」這欄 C0 時大多還是空的 —— **留空是對的**,它是後續步驟的待辦清單。

### C0.5 `test_contracts.py`(新檔)

| # | 命題 | 注入什麼 |
|---|---|---|
| P1 | round-trip:`dump_cell(parse_cell(x)) == x` 對 36 格全數成立 | — |
| P2 | `core.contracts.validate` 與 `facts.validate` 對 36 格結果**逐條一致** | — |
| P3 | 缺必要欄位 → raise | 拿掉 `printed_total` → 必須紅 |
| P4 | 型別錯誤 → raise | `cols` 的值放字串 → 必須紅 |
| P5 | **分類未知的列必須存得進去**(鐵則 3) | 造一列 `name="某個不存在的科目名"`(`buckets.bucket()` 回 None)→ `parse_cell` **必須成功**。若它 raise → 紅 |

P5 是**鐵則 3 在契約層的體現**:契約層只管來源、結構、型別。
今天 `facts.validate()` 本來就不看分類(它沒有 import buckets),所以 P5 應該直接綠 ——
**它的價值在於防止你在 C0 順手加一條「分不出桶就不合法」的檢查。**

### C0 的驗收

```
[ ] E1:python3 -m core anchors --verify 對 15 份 PDF 全數逐項相同(貼輸出)
[ ] test_ring.py 三條全綠(pdf_cache/ 改名後 Ring 1 仍可跑)
[ ] test_contracts.py 綠(P1–P5),且 P3/P4「注入 → 紅」的實測輸出各貼一段
[ ] P5 綠:分類未知的列存得進 contracts(鐵則 3)
[ ] git diff facts/ 為空(一個 byte 都沒變)
[ ] 九支既有測試全綠
[ ] docs/guardrails.md 存在,G1–G20 齊全
```

---

## 步驟 C1 —— 判定層

### C1.1 `core/reconcile.py`

**核心動作只有一件:讓判定層吃「錨值整數」,不吃 `Located`。**

`transcribe.verify(recs, loc)` 對 `loc` 的全部用途是 `check_anchor()` 裡的
`loc.anchors.get(rec["class"])`。所以寫一個最小 adapter:

```python
class _Anchors:
    """只暴露 transcribe 真正用到的那一個屬性。**不要繼承 Located,不要補其他方法** ——
    多補一個方法,就多一條讓 PDF 依賴偷偷回來的路。"""
    def __init__(self, mapping):   # {"Trading": 9082587, ...}
        self.anchors = mapping
```

```python
def verdict_of(cell, anchors) -> Verdict      # 純函數
def verify_all(cells, store) -> dict[key, Verdict]
```

`Verdict` 是現行 `verdict` 與 `audit` 的合併(見 `plan_clean_core.md` §2.2),
但**內容逐欄照抄 `results.build()` 現在算的東西**,一個欄位都不准加減、不准改名。

產物寫 `out/verdict.json` 與 `out/audit.json`。
**`out/` 只准寫,不准任何程式讀回來**(R-A)。`core/store.py` 不得提供讀 `out/` 的函式。

### C1.2 E2 等價閘門 `test_e2_equiv.py`

```python
new = core.reconcile.verify_all(cells, store)     # 吃 anchors/,零 PDF
old = results.build(cells)                        # 吃 PDF,56 秒
```

斷言:

1. key 集合相同;
2. 每格 `pass` / `wide` / `wide_cost` / `side` / `others` / `anchor` **逐欄相同**;
3. 每格 `checks` 的**訊息字串逐字相同**(不是「都失敗」就算過)——
   那些訊息是拒收的證據,也是 `/fill` skill 明令 agent 照抄的東西,漂移 = 護欄變了;
4. `audit` 的 `sources` / `basis_gap` / `unknown` 逐項相同。

### C1.3 速度

```
[ ] core verify 對 36 格 < 1 秒(今天 results.build 是 56.5 秒)
[ ] test_build.py 跑得完(< 60 秒);若仍跑不完,回報並停下
```

### C1 的驗收

```
[ ] E2 全綠,四條斷言各貼一段輸出
[ ] core verify 計時 < 1 秒(貼數字)
[ ] test_ring.py 的 test_ring1_imports 綠(reconcile 不得把 pypdfium2 拉進來)
[ ] 九支既有測試全綠
[ ] test_build.py 跑得完並綠(或明確回報卡在哪)
[ ] guardrails.md:G2/G3/G4/G6/G7/G8 的「新核心誰擁有」填上 core.reconcile
[ ] results.py 尚未刪除(退場條件是「連續兩次分類表變更後仍等價」,不在本單)
```

---

## 回報格式

**一次性回報(鐵則 7)。** R / C0 / C1 三步全部做完、**且跑完下面這張總表**之後,
才回報一次。中間不要逐步回報,也不要做完 R 就來問要不要繼續 —— 除非遇到
§0.0 說的「停下來問使用者」那種情況。

### 回報前必須跑完的總表

```bash
# ① 注入測試(每一條都要「注入 → 紅」的實測輸出)
python3 test_units.py            # U1 U3 U5 U8
python3 test_expand_policy.py    # X1 X2 X4
python3 test_contracts.py        # round-trip + 缺欄注入

# ② 等價閘門
python3 test_e2_equiv.py         # E2:core.reconcile vs results.build
python3 -m core anchors --verify # E1:15 份 PDF 逐項比對
python3 test_ring.py             # T-R3:三條
python3 test_rulings.py          # 棘輪基準表

# ③ 回歸(九支既有測試,一支都不准紅)
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ④ 發布層(C1 之後應該跑得完;跑不完就回報卡在哪)
python3 test_build.py
```

**任何一項紅了,不要修判準,回報它。**

### 回報這五段:

1. **每一步的驗收 checklist**,逐條打勾或說明為什麼沒打勾。
2. **注入測試的實測輸出** —— U1/U3/U5/U8 每條「注入 → 紅」各貼一段。
   `plan_clean_core.md` 的規矩是:**驗收器必須證明它會失敗,只證明會通過不算數。**
3. **速度數字**:`core verify` 與 `results.build` 各自的秒數。
4. **`test_rulings.py` 的基準表**,以及與 §0.3 的差異(若有,逐項解釋)。
5. **遇到的意外**:任何「規格說 A、實際是 B」的地方。**不要自行裁示,列出來。**
   已知會遇到、不必再回報的一件:`check_cross(recs, bk=None)` 的 AttributeError(§R.5)。

---

## 常見誤區(這些都真的會發生)

| 誤區 | 正解 |
|---|---|
| 把 `transcribe.py` 的檢查抄進 `core/reconcile.py` 順便整理 | **只准 `from transcribe import ...`**。拆 god module 是另一步,綁一起會讓 E2 分不出差異來源 |
| `_Anchors` 寫成繼承 `Located` 或補上 `text()`/`expand()` | 多一個方法就多一條讓 PDF 依賴回來的路。**只暴露 `.anchors`** |
| 錨值對不上就自動重算 | **拒絕使用並 raise**。自動重算會讓「錨過期」這種錯無聲通過 |
| E2 只比 `pass` 布林值 | 要比到**訊息逐字**。只比布林會放過訊息漂移 |
| 看到 `test_rulings.py` 紅就去改判準 | 有些命題本來就該紅到 C4。它是棘輪:只在**數字惡化**時 exit 1 |
| 覺得「分類未知時擴一下頁也沒差,加個保險分支」 | **使用者已裁示不准。** M3 證明那個訊號一半指向小計、一半指向真科目。加分支 = 把擲硬幣寫進程式 |
| 想順手修 `check_cross(bk=None)` 的 AttributeError | 禁改檔案,且今天無人呼叫。**列進回報,不要動** |
| 用錯誤訊息字串判斷該不該擴頁 | 判準是「哪一道檢查失敗」。訊息比對會漏判 —— 同一個根因會在第 3 道長出第二個症狀 |
| 為了讓 `data_wide_inconsistencies` 變 0 去改 `data` 區塊 | 那是 C4 的工作,本單**不准碰 `data.json`** |
| 覺得 `check_anchor` 反正恆真,不必留 | 錨改成快取之後它變成**真的檢查**(印出合計 vs 快取錨)。價值上升,不准拿掉 |
| 順手把 `results.py` 刪了 | 退場條件是「連續兩次分類表變更後仍等價」,不在本單 |
| 在 C0/C1 寫下「SYN 命中 = 已確認」的假設 | 鐵則 5:SYN 要先完成批准遷移並建立 reference 才有這個資格,而那是 Phase B |
| 在 `contracts.py` 把「分不出桶」寫成不合法 | 契約層只管來源、結構、型別。**分類未知必須存得進去**(鐵則 3) |
| 做完 R 就回報問要不要繼續 | 鐵則 7:一次性回報。除非遇到 §0.0 指名要問的落差 |
