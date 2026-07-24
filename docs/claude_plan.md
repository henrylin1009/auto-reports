# 遷移計劃：Claude 視覺 Reader（最終版）

## 一句話
**語義判斷全交 Claude（看頁面圖）；算術/機械/驗證全留程式。**
定位用「目錄導覽」讓 Claude 決定去哪；讀值用切片 PDF 餵 Claude 視覺；三道保險絲不動。

## 核心原則（分工鐵則）
| 交給 Claude（語義） | 留在程式（算術/機械/驗證） |
|---|---|
| 看目錄選頁、讀數值、**對桶分類**、判股票/調整項、取當期欄 | 三道保險絲、切頁、oracle 比對、Batch 調度 |
> 保險絲交給 Claude = 讓 LLM 自己驗自己的數字 = 沒保險。**絕不。**

## 定案（設計決定）
1. **省路**：不餵整份 PDF。定位到 2–3 頁 → 只送那幾頁。
2. **目錄導覽定位**（PageIndex 精神）：程式建精簡目錄 → Claude 讀目錄決定讀哪頁（取代脆弱關鍵字判斷）。
3. **切片 PDF**：`pypdf` 按頁碼把選中頁抽成小 PDF 送 Claude（原生 PDF＝文字＋視覺；免 render、免 DPI）。
4. **單次雙欄**：明細表成本欄＋公允欄一次讀完 → 每桶 `{帳面,公允}`。**幹掉雙 pass**。
5. **對桶交 Claude**：讀值時一併把每列歸 7 桶之一（或股票/調整項）；`schema` 同義字表降為**交叉護欄**。
6. **結果快取**：每格結果存檔；重跑只跑待人工格。**快取鍵含 `pipeline_version`（改管線→舊快取自動失效）**。
7. **2024 oracle 黃金測試**：拿現有 data.json 當驗收門，每次改碼逐格比對。
8. **主力 Gemini 免費 Flash**（`gemini-2.5-flash` 或當前 Flash）；**難格（對帳不過）才升級付費模型**（Gemini Pro 或 Claude）。棄 DeepSeek。視覺 reader 隔離在一支檔,底層可換。

## 成本（省路 + 免費第一手）
- **Gemini 免費 Flash 第一手**：$0（額度 1,500 次/天,我們全量 ~450 次呼叫,一天內跑完）
- **難格升級**：只有對帳不過的 ~2–3 成格升付費 → 全部一次性 ~$3–5
- 全付費上限參考：Opus ~$15–25、Sonnet ~$10–15（開 Batch 再 5 折）
- 免費版代價:Flash 較弱(待人工長一點,但保險絲擋)、輸入可能被拿去訓練(公開財報無妨)、無 Batch

## 流程
```
每份 PDF 一次：
① 建目錄  outline(path)：逐頁抽標題行（自帶正確 PDF 頁碼）→ [(頁, 標題)]（程式,便宜）
② 導覽    Claude 讀目錄「一次」回全部：{Trading主附註頁, OCI頁, AC頁, 明細表頁, 資產負債表頁}
            （每份一次,非每類；SOURCE 要求：OCI/AC 要主附註非明細表）

每格：
③ 切頁    pypdf 抽選中頁（連前後1頁,涵蓋跨頁續表）→ 小 PDF（程式,機械）
④ 讀      Claude 視覺讀小 PDF → structured outputs（攤平 schema）：
            {source_type, header, anchor,
             rows:[{名, 段, 桶, 帳面, 公允}],   ← 桶由 Claude 歸；雙欄一次讀
             subtotals:[{段, 金額}]}
⑤ 外錨    Claude 讀資產負債表頁 → 資產側總額（自動相加流動+非流動、排除權益側）
⑥ 對帳    check()：Claude 歸的桶 vs schema 同義字交叉檢查（不一致→以 Claude 為準+標待人工）
            + 三道保險絲（程式,算術）
⑦ 驗收    對 2024 oracle 逐格比對（程式）

跑法：開發期（里程碑1–3）用同步單呼叫（即時除錯）；全量回測（里程碑4）才用 Batch API（5折,非同步）。
```

## 這次砍掉/簡化的東西
| 刪除 | 原因 |
|---|---|
| 座標重組 `page_rows` / `_coord_text` / `_is_soup` | 視覺看圖,字元湯不再是問題 |
| `balance_sheet_anchor` regex 特例（流動非流動相加、6碼代碼） | Claude 視覺看整張表自己相加 |
| 圖 render / DPI 旋鈕 | 改送切片 PDF（原生文字＋視覺） |
| 雙 pass（`auto_extract_dual` 兩次 API） | 單次讀雙欄 |
| `_unknown` 掉數字的洞 | Claude 一定歸某桶 |
| 同義字表追新品名 / 「衍生 prefix」prompt hack | 對桶交 Claude,看得懂脈絡 |
| 手解 JSON | structured outputs |

## 保留不動
`schema.py`（桶定義＋同義字→降為交叉護欄）、`check()` 三道保險絲、方案 B 輸出結構、`backtest.py` 待人工彙整、SOURCE/MEASURE 口徑、candidates 的分區概念（併入目錄導覽）。

## 檔案改動
- **新增 `vision_reader.py`**（取代 `llm_reader.py`；底層可換模型,預設 Gemini,難格升 Claude）：
  - `_client()`：`google.genai.Client()`（key = `.env` 的 `GEMINI_API_KEY`）；付費升級掛口另接 Anthropic
  - `outline(path) -> [(page, heading)]`：抽每頁標題＋自印目錄頁種子
  - `navigate(outline, cls, source) -> [page_idx]`：Claude 讀目錄選頁
  - `_slice(path, pages) -> pdf bytes`：pypdf 抽頁（含前後 1 頁）
  - `read_note(path, pages, cls, measure_note) -> {groups, anchor, source_type, header}`：
    切片 PDF document block → `output_config.format` 綁 JSON schema（含每列的桶/帳面/公允）；`model=claude-opus-4-8`, `thinking=adaptive`
  - `read_bs_anchor(path, bs_pages, cls_name) -> int`：資產負債表資產側總額
- **`universal.py`**：`auto_extract`/`resolve_bs_anchor` 改呼叫 `claude_reader`；刪座標/regex 特例；`check()` 加「Claude桶 vs 同義字交叉檢查」示警；`auto_extract_dual` 併成單次雙欄。
- **`backtest.py`**：加結果快取（跳過已過格）。
- **新增 `test_oracle.py`**：2024 逐格比對 data.json（golden gate）。
- **`.env`**：加 `ANTHROPIC_API_KEY`（gitignored,勿提交）。

## 里程碑
1. **接 `claude_reader`**：乾淨格（2023 中信 OCI）端到端跑通。
2. **富邦 2021 試金石**：現在 note 讀爆(1169≠413)、BS 讀不到。Claude 視覺重跑,目標一舉讀對：
   OCI 413.0 億(流動65.7+非流動347.2)、AC 545.2 億;且讀主附註非明細表。
3. **2024 oracle golden 測試建立**：新管線對得上現有 data.json 才算過。
4. **Batch 跑 2020–2024 全量** → 乾淨待人工清單。
5. 接 data.json（每桶 {帳面,公允}+每類公允總額）/ 網站（7 桶+股票）。

## 技術備忘（Anthropic SDK）
- 切片 PDF：`{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}` 放 user content。
- 結構化輸出：`output_config={"format":{"type":"json_schema","schema":{...}}}`（保證合法；與 citations 互斥→溯源改回報 page+header 欄位）。
- 省錢：`messages.batches`（5 折,非同步）；prompt caching 前綴 `cache_control`。
- 難格重試：對帳不過 → 重讀（可加頁/換頁）。
