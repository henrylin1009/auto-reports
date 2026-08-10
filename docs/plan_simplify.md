# 簡化計畫 —— 把三個時代的實作收斂成一條

**目標**:live 程式從 ~9,000 行收斂到 ~2,500 行,**每個概念只有一份實作**。
**判準**:`data.json` 的每一個數字在整個過程中**逐字不變**。簡化不是重寫,
是刪掉重複 —— 任何一步只要動到發布數字,就是做錯了,退回去。

寫於 2026-07-29。基準線全部是當天實測,不是估計。

---

## §0 基準線(2026-07-29 實測)

| 項目 | 數字 | 量法 |
|---|---|---|
| live 模組(從 6 個進入點的 import 閉包) | 26 支 / 9,019 行 | AST 閉包,進入點 = `server.py` `build.py` `make_web.py` `fill.py` `fill_auto.py` `resolve.py` |
| **完全無人引用的檔** | **25 支 / 157KB** | 同上,不在閉包內 |
| 測試 | 31 支 / 6,009 行,**23 綠 8 紅** | 逐支 `python3 test_x.py` 看 exit code |
| `facts/` | 42 格 / 637 列 / 127KB | |
| `decisions/` | 42 格 / **同樣 637 列** / **400KB** | 同一批列的分類結論,佔原始事實的 3.1 倍 |
| 發布單位 | **v3 62 / v2 321**(8 處衝突) | `build_manifest.json` |
| PDF | 89 份(2023+ 42 份,≤2022 **47 份**) | `pdf_cache/` |
| `build.py --diff` | rc=0,**27 秒**,確定性 | 已實測,可當閘門 |

### 沒有 CI 跑測試
`.github/workflows/` 三支:`report.yml`(跑 `make_web.py`)、`fetch-test.yml`
(跑 `fetch_test.py`)、`build-exe.yml`(打包 `app.py`)。**沒有任何一支跑
`test_*.py`** —— 所以「測試綠」目前是靠人記得跑。

### 8 支紅的測試,先分類再處理
| 測試 | 性質 | 處置 |
|---|---|---|
| `test_b3` `test_b5` `test_jobs` `test_rulings` `test_decide_equiv` | 測的是**已經無人引用的模組**(`jobs`/`publish_gate`/`ratify`/`recheck`/`reconcile`/`units`/`core.decisions`) | 隨 S1/S3 一起刪,不修 |
| `test_webdata` | **過時**:`overview()` 已改成口徑分兩張矩陣 + 空格可按(commit `7531879`/`01c3569`),測試還假設一張矩陣、`classes` 必非 None | S0 修 |
| `test_build` | **過時**:期望「6 處衝突」,現況是 8 處 | S0 修(確認 8 處都是已知的,不是新的) |
| `test_drive` | 42 格重現 41 格,**1 格不符** | S0 查清楚是哪一格、為什麼 |

---

## §1 為什麼要動 —— 四組重複(這是全部的理由)

### ① 三份重試迴圈
同一件事(「算術對不上就擴頁重抄」)有三份實作:

| 實作 | 誰在跑 |
|---|---|
| `fill.cmd_submit`([fill.py:286](../fill.py)) | 網站手動送出、CLI |
| `core.ingest.classify_outcome` + `fill_auto.run_cell` | 自動抄列 |
| `pipeline.drive`([pipeline.py](../pipeline.py)) | **只有測試在跑**;production 只用到 `pipeline.MAX_LEVEL` 這個常數 |

前兩份靠 `test_ingest_equiv` 的 E5 閘門維持等價,而 [core/ingest.py:202](../core/ingest.py)
自己記著**它已經漂移過一次**。更關鍵的是現在兩份**刻意不等價**了:
`use_policy=False` 分類未知 → `BLOCKED`(整格不歸檔),`use_policy=True` → `FILED`
(歸檔 + 進 review)。**同一格資料,兩個入口兩種結局。**

### ② 兩套分類系統,其中一套對發布數字零影響
- 真正決定 `data.json` 的:`buckets.SYN`(約 60 個名字的 dict)→ `wide` → `data.json`
- 平行的另一套:`taxonomy/rules.json`(83 條)+ `decisions/`(400KB)+
  `review/queue.jsonl` + `core/decisions.py`(21KB)+ `decision_store` + `core/queue.py`

證據不必推論,[build.py:183](../build.py) 自己寫著:
`"decisions_sha256": _sha("buckets.py", "config.py")` —— 決策層的指紋算的是那兩個檔。

**已經長出後果**:分桶檢視拖曳時([workbench.js:312](../web/workbench.js)),confirm 按
「取消」→ 只寫 `decisions/` + `taxonomy/`。畫面上桶變了、`tally` 變了,**網站數字一個字沒動**。

### ③ 同一張表四種表述
`config.BUCKET_RULES`(散文)→ `rules.KEYS`(關鍵字)→ `buckets.SYN`(精確表)
→ `taxonomy/rules.json`(帶 state 的規則)。加一個科目名要動幾處,看你從哪個按鈕進來。

### ④ 五個結局、三個佇列
`PASS / FILED / BLOCKED / RETRY / REJECT` + `work/pending` + `work/blocked/` +
`work/rejected/` + `review/queue.jsonl`。[core/queue.py](../core/queue.py) 整支存在的
唯一理由是「把兩個佇列合流」—— 那是在補一個從零開始不會有的洞。

---

## §2 S0:先立閘門(**必要前置,不可跳過**)

沒有閘門的刪除是賭博。閘門要能回答唯一重要的問題:**發布數字有沒有變。**

### S0.1 寫 `check.sh`(四道)
```
1. python3 build.py --diff          → 輸出與 baseline 逐字相同(27s)
                                      ← 最強的一道:它證明 data.json 每個數字沒變
2. 逐支跑 test_*.py                 → 今天綠的 23 支必須維持綠
3. python3 locate.py --expand       → 11 格定位回歸
4. server 煙霧測試                   → 起 server,打 8 支 GET endpoint,存 JSON 快照比對
```
先跑一次把輸出存成 `docs/baseline_20260729/`,之後每一步都比對它。

### S0.2 修測試汙染(**先修這個,否則閘門 1 與閘門 2 會互相打架**)
實測:跑 `test_build.py` / `test_drive.py` 期間,`results/verdict.json` 被覆寫成
300 bytes,導致同時跑的 `build.py --diff` 觸發鐵則 2 斷言而 rc=1。
→ 讓測試一律寫 tmp 目錄,不碰 production 的 `results/` `facts/` `decisions/`。

### S0.3 處理 8 支紅的其中 3 支(`test_webdata` `test_build` `test_drive`)
另外 5 支不修,它們測的模組在 S1/S3 會消失。

**S0 產出**:一句 `./check.sh` 就能回答「我剛才有沒有弄壞東西」。約半天。

---

## §3 S1:刪無人引用的 25 支(低風險,先做)

### 批次 A —— 無測試依賴,直接刪(8 支)
```
bridge_v2.py  build_native.py  extract_pnl.py  make_charts.py
phase0.py     score_golden.py  core/cli.py     core/__main__.py
```
⚠️ `更新網站.command` 呼叫 `bridge_v2.py` —— 一併處理(見 §7 待裁示①)。
`bridge_v2` 早已有寫入防護([bridge_v2.py:67](../bridge_v2.py) 直接 `SystemExit`),
所以那個 `.command` 今天雙擊只會印錯誤,已經是死的。

### 批次 B —— 死碼 + 死測試一起刪(10 支程式 + 8 支測試)
```
程式:core/jobs.py  core/migrate_syn.py  core/publish_gate.py  core/ratify.py
      core/recheck.py  core/reconcile.py  core/report.py  core/review.py
      core/store.py  core/units.py  core/contracts.py
測試:test_jobs  test_taxonomy_migration  test_b3  test_b5  test_ratify
      test_report  test_ring  test_rulings  test_units  test_contracts  test_e2_equiv
```
**這批刪完 `core/` 從 21 支剩 8 支。** 刪的順序:先刪測試、跑閘門,再刪程式、再跑閘門
—— 分兩次才知道是誰弄壞的。

### 批次 C —— 桌面工具(**要裁示,見 §7 待裁示②**)
`app.py` + `.github/workflows/build-exe.yml`。**這條線已經壞了**:`app.py` 第 21 行
`import build_report`,而 `build_report.py` **不存在**(README 記載的 `extract3.py`
`extract2.py` `extract_megabank.py` 也都不存在)。

**閘門**:`./check.sh` 四道全過。**S1 預估 1 天,可回復(git revert)。**

---

## §4 S2:三份重試迴圈併成一份

1. `fill.cmd_submit` 改成薄殼:讀 `pending` → 呼叫 `core.ingest.classify_outcome`
   → `apply_outcome`。**判斷邏輯一份都不留在 `fill.py`。**
2. 統一 `use_policy=True`,**拆掉 `BLOCKED` 出口** —— 分類未知一律 `FILED`
   (歸檔 + 進 review)。這不是新裁示,[core/expand_policy.py](../core/expand_policy.py)
   檔頭 2026-07-28 就已經寫定「分類未知一律走 facts 歸檔 + review queue」,
   `BLOCKED` 是更早期留下、與該裁定矛盾的第二條路。
3. 隨之消失:`work/blocked/`、`work/proposals.jsonl`、`fill.cmd_requeue` 的一半、
   `core/queue.py` 的合流(只剩一個來源就不必合流)、`fill._taxonomy_gap`(147 行)。
4. 刪 `test_ingest_equiv`(等價閘門是「養兩份實作」的稅,只有一份就不需要)。
5. `pipeline.py` 只剩 `MAX_LEVEL` 一個常數 → 移進 `config.py`,刪
   `pipeline.py` `transcriber.py` `test_pipeline` `test_drive`。

⚠️ **`test_drive` 是「重播 facts 能重現同樣結論」的回歸**,刪掉會少一道保險。
替代:S0 的閘門 1(`build.py --diff` 逐字相同)涵蓋同一個性質,而且更直接
—— 它比的是最終數字,不是中間結論。**確認閘門 1 已就位再刪。**

**結局從 5 個變 3 個**:`PASS`(全過)/ `FILED`(算術過、分類待審)/ `REJECT`(擴到上限仍對不上)。

**閘門**:`./check.sh` + 額外檢查 `facts/` 42 格內容 byte-identical。**預估 1 天,中風險。**

---

## §5 S3:拆掉第二套分類系統

刪除:
```
core/decisions.py (21KB)  core/decision_store.py  core/queue.py
taxonomy/  (92KB)         decisions/ (424KB)      review/ (20KB)
test_decisions  test_decide_equiv  test_queue  test_b2  test_b4
```
改寫(`core/webdata.py` 三個函式):
- `bucket_view()` 改讀 `facts/` + `buckets.bucket()` **現算**。
  ⚠️ 現在讀 Decision 的理由是「規則是應然、Decision 是實然」—— 但**現況兩者必然相同**,
  因為 Decision 就是同一套規則算出來寫下的,沒有任何獨立資訊。
  唯一的例外是 `rebucket()` 寫進去的單格覆寫,而那個功能本身正是 ② 那個陷阱。
- `rebucket()` 改成**只寫 `buckets.SYN`**(即 `confirm_bucket`),拿掉「只改分類紀錄」
  那個選項 —— 那個選項的效果是「看起來改了但沒改」。UI 的 confirm 對話框跟著改成
  「這會影響所有文件,確定?」。
- `pending_entries()` 改成從 `facts/` 現算:`bucket(row) is None` 的名字就是待裁示清單。
  **待辦用算的,不用存的** —— 存的那份就是會跟事實不同步的那份。

審計軌跡怎麼辦:`git log -p buckets.py`。`build.py` 已經是這樣認定的(見 ②)。

**閘門**:`./check.sh` + 手動確認分桶檢視畫面的 tally 與改寫前相同。**預估 1–2 天,中風險(UI 要動)。**

---

## §6 S4 / S5:兩條退場

### S4 —— `extract_v2.py` 退場(半天,低風險)
786 行的舊抽取器活著,只因為 [fill_auto.py:111](../fill_auto.py) 要用它的 `_gen()`
(Gemini 多 key 輪替 + 節流,約 20 行)。
→ 抽成 `gemini.py`(~30 行),刪 `extract_v2.py` `batch_v2.py` `test_oracle.py`
`extract_v2_results.json`(225KB)、`config.LEGACY_BUCKETS` / `LEGACY_BUCKET_RULES`
及其 assert。

### S5 —— v2 凍結快照退場(取決於抄列進度)
今天 **321/383 個發布單位還是 v2 快照**。`build.py` 一半的複雜度
(`eligible` / `PASSTHROUGH` / `conflicts` / 禁止 null 覆寫 / `_assert_no_stale_verdict`)
都是「兩個時代並存」的稅。

**前置條件**:2023+ 的 42 份 × 3 類 = 126 格抄滿(今天 42 格,**33%**)。
抄滿後 `build.py` 應該剩 ~60 行:`facts → wide → data.json`,同時刪掉
`snapshots/` `bridge_v3.py` `holdout.py` `results/`。

**這一步不能靠重構加速,只能靠抄列。** 排在最後不是因為難,是因為它在等資料。

---

## §7 需要你裁示的三件事(卡住 S1 的只有第 ①②)

① **`更新網站.command` 要刪還是改?** 它現在呼叫已停止寫入的 `bridge_v2.py`,
   雙擊只會印錯誤。改成「跑 `build.py --write` + `make_web.py` + push」大約 10 行。

② **桌面工具(`.exe`/`.app`)還要不要?** `app.py` + `build-exe.yml` 這條線已經壞了
   (import 一個不存在的檔)。要留就得重接到 `build.py`;不要就連 workflow 一起刪。

③ **≤2022 的 47 份 PDF 要不要做?** `webdata.CUTOFF_YEAR = 2023` 已經把它們排除在
   畫面外。若確定不做,`pdf_cache/` 可以只留 2023+,`locate.CENSUS_BASELINE`
   的 267 槽基準要跟著重訂(現在 96 個「錨讀不到」全部來自 ≤2022)。
   —— 這件事不擋 S1~S4,可以晚點決定。

---

## §8 收斂後的形狀

```
resolve ─► locate(錨值千分位 grep) ─► agent 讀表 ─► 六道算術 ─► facts/*.json
                                          ▲              │不過
                                          └── expand ────┘
                                                          ↓
                                        buckets.SYN 一張表(+ 算出來的 unknown 清單)
                                                          ↓
                                                wide ─► data.json ─► site/
```

| | 現在 | 收斂後 |
|---|---|---|
| live 模組 | 26 支 / 9,019 行 | ~14 支 / ~2,500 行 |
| `core/` | 21 支 | 3–4 支(`acquire` `ingest` `webdata`) |
| 測試 | 31 支(8 紅) | ~12 支(全綠 + `check.sh`) |
| 抄列結局 | 5 種 | 3 種 |
| 待辦佇列 | 3 個(存的) | 1 個(算的) |
| 分類表 | 4 種表述 | 1 張 + 1 份給 agent 讀的散文 |
| 資料目錄 | `facts` `decisions` `taxonomy` `review` `results` `snapshots` `work` `anchors` `out` `preview` | `facts` `work` |

**不做的事**:不重寫 `locate.py`、不動六道檢查、不碰 `buckets.SYN` 的任何一條
內容、不改 `make_web.py`。那些是這個專案真正值錢的部分 —— 這份計畫從頭到尾
只刪重複,不碰判斷。
