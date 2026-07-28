# 護欄清冊

> C0 建立。plan_clean_core.md §5.2 的 G1–G22 逐條抄進來。
> 「新核心誰擁有」欄 C0 時大多還是空的 —— **留空是對的**,它是後續步驟的待辦清單。
> 變形的護欄要重寫測試,不變形的一行都不准動;變形的護欄一律保留舊版本描述與失效日期。

| # | 護欄 | 實測案例 | 證明它會失敗的測試 | 新核心誰擁有 |
|---|---|---|---|---|
| G1 | 第 5 道擋兩層附註 | 玉山 2021H1 OCI:前四道全綠但產出是廢的 | `test_expand_policy.py` X7(玉山家族被 ⑤ 擋住);Phase B 才把安全性質改成發布閘門 | (待 Phase B) |
| G2 | `coarse()` 排除跨桶合併列 | 富邦 202404:六道全綠但每一桶都錯 | `test_wide.py` | (未動) |
| G3 | 三值檢查,`NA_*` 不畫綠燈 | 恆真閘門是頭號死因 | `test_cross.py` | (未動) |
| G4 | 缺欄不補 0(未揭露 ≠ 0) | 88 列缺欄;衍生無取得成本 | `test_wide.py` | (未動) |
| G5 | 合計欄印 `-` 記 0,其他欄不放 key | `facts.validate` total_col 檢查 | `test_facts.py` | `core.contracts`(轉呼叫 `facts.validate`) |
| G6 | 驗不到的成本欄不採用 | 沒抄 `printed_totals` 的明細表 | `test_wide.py` | (未動) |
| G7 | 三段恆等式 7桶+衍生+評價調整==合計 | 兩者會計意義相反 | `test_wide.py` | (未動;Phase B I4 要讓 UNCLASSIFIED 進恆等式) |
| G8 | `bond_mv` 只扣衍生 | 中信曾算出子集 > 全集 | `test_wide.py` | (未動) |
| G9 | v3 的 null 不得抹掉 v2 | 8 處衝突 | `test_units.py` U1/U5(整格回退,null 不覆寫 v2) | `core.units` |
| G10 | 保留集永不進發布 | holdout 3 格 | `test_units.py` U7 | `core.units`(透過 `holdout_keys` 參數) |
| G11 | `bs_anchor` 截斷偵測寧可回 None | OCR 掉逗號 | (bs_anchor.py 既有測試,未在本單清單) | (未動) |
| G12 | `CENSUS_BASELINE` 定位普查基準 | 96 / 2 / 169 | `test_locate.py` | (未動) |
| G13 | `facts.validate` 未知欄位與型別 | 邊界驗證 | `test_facts.py`、`test_contracts.py` P2/P3/P4 | `core.contracts`(轉呼叫,第二 oracle) |
| G14 | 分類表缺口短路,不白燒擴頁 | 國泰 202504:擴到 8 頁,白燒 8 輪 | `test_gap.py`;`test_expand_policy.py` X7(分類根本不在觸發清單上) | `core.expand_policy` |
| G15 | `SYN` 不准手工塞,要背書 | 今天靠人工儀式 | `test_synonyms.py` | (未動;Phase B B1 才變 CI 閘門) |
| G16 | 錨讀不到 → 拒收不猜 | `pipeline.run` 第一個分支 | `test_pipeline.py` | (未動) |
| G17 | 一格只有數字或 null,不留舊值 | `bridge_v3` 裁示 | `test_units.py` U1/U5/U8(分層陳述,見 R2) | `core.units` |
| G18 | **同一格三個投影不得混來源** | M1:21 處 data/wide 不一致 | `test_rulings.py` `data_wide_inconsistencies`(棘輪,今天 21,目標 0 於 C4) | `core.units`(`adopt()` all-or-nothing) |
| G19 | **發布過 v3 的 unit 不得倒退** | ratchet | `test_units.py` U8(ledger 記為 v3 卻不合格 → CONTRADICTION) | `core.units`(`ledger` 參數) |
| G20 | **Ring 1 不得碰 PDF / state / 時鐘** | T-R3 | `test_ring.py` 三條 | `core.contracts` / `core.reconcile` / `core.units` |
| G21 | **分類狀態不得觸發擴頁,也不得消耗重試預算** | M3:`propose()=None` 裡玉山 2 個是小計、兆豐+玉山 2 個是真科目 | `test_expand_policy.py` X1/X2/X4/X5/X7 | `core.expand_policy` |
| G22 | **UNCLASSIFIED 不得冒充 OTHER / null** | 今天 `wide.view()` 的 `unknown` + `View.ok` 已做對一半 | (未在本單清單;Phase B I4 才補完整) | (待 Phase B) |

## C1 補充:G2/G3/G4/G6/G7/G8 的新核心

`core.reconcile` 只是 `from transcribe import ...` 的 adapter(`_Anchors`),
六道檢查的實作**仍在 `transcribe.py`/`wide.py` 裡,一行沒搬**。所以上表
G2/G3/G4/G6/G7/G8「新核心誰擁有」填 `core.reconcile`,意思是**新核心透過它間接
擁有**(呼叫 `transcribe`/`wide` 的既有實作),不是重寫過。E2 等價閘門
(`test_e2_equiv.py`)證明這條 adapter 沒有改變任何一道檢查的行為
(36 格逐格逐欄相同,含 checks 訊息逐字相同)。

## Phase B / C4 前置條件(2026-07-28 使用者裁示,寫下防止之後被忽略)

`core.units.adopt()` 判 `provenance == "v3"` **今天只是 technical candidate**,
不是正式發布資格。它只核對六道檢查/七桶齊全/holdout,完全不查
`buckets.SYN` 命中是否已完成鐵則 5 要求的批准遷移與 reference 建立(B1)。

**在 B1 完成前:**
- `adopt()` 的 v3 結果不得被下游當作「可以上網站」的最終判斷;
- C4 銜接 `core.units` 進真正發布流程時,**不准把現有 SYN 命中直接視為
  CONFIRMED** —— 那正是鐵則 5 明文禁止的事,也是 §3.4「B1 必須早於 I5
  上線」的順序約束。C4 要接的是「B1 完成後、SYN 命中有 reference 背書」
  的狀態,不是今天的 `SYN` dict 本身。

## 已知潛伏問題(記錄,本單不修)

`transcribe.check_cross(recs, bk=None)` 一跑就 `AttributeError`(`transcribe.py:337`
的 `_by_bucket()` 在 `bucket is None` 時把 `bad` 回成 list,`_merged()`/呼叫端當
dict 用)。今天唯一呼叫端 `verify()` 永遠傳 `buckets` 進去,這條路徑沒人走。
`transcribe.py` 在禁改清單裡,且修它會讓 E2 分不出差異來自搬家還是修 bug —— 見
`core/expand_policy.py` 的 docstring 與本次施工回報第 5 段。
