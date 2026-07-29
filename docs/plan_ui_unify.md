# 前後台合一計劃：同一個網頁，最上面一顆鈕切換（2026-07-29）

## 進度（2026-07-29）

- ✅ **步驟 1**：`web/tokens.css` 建好，`make_web.py` 內嵌它，`site/index.html` 產出
  與改動前逐位元組比對(除時間戳外)完全一致 —— 三個頁籤、帳面/成本切換、
  Chart.js 圖表、`.ix-seg` 分段鈕全部截圖驗過。
- ✅ **步驟 2**：`interactive_html()` 的 `.ix-seg`/`.ix-sub` 重複規則移除，改吃
  tokens.css 那份；`site/index.html` 的 `<style>` 從邏輯上的「兩份 7,178 字元
  拷貝」收斂成一份。
- ✅ **步驟 3**：`web/workbench.html` 改 `<link>` 引入 tokens.css，變數值全部
  換成淺色版(白底/靛紫),用同一組變數名以免改動每條規則。狀態色
  (ok/warn/danger)重新挑成 700 級色階(綠 #15803d／橘 #b45309／紅 #b91c1c),
  對白底文字對比度足夠,不是直接把深色版的亮色搬過來。總覽矩陣、分桶檢視兩
  個畫面截圖驗過,和分析頁的視覺語言(卡片陰影、分段鈕、狀態色語彙)一致。
- ✅ **步驟 4**：另一個併行 session 把 `pdf_cache/` 那 10 份 2026H1/H2 空殼檔
  清掉了(`locate.py`/`fill.py` 也一併 commit,`7531879`/`01c3569`),index
  build 不再炸。複核台的左右分割複核畫面(PDF 對照抄列)重新截圖驗過,白底
  卡片、`p.36`/`p.38` 分頁鈕跟分析頁同一套語言,可讀性沒問題。
- ✅ **步驟 5**:`server.py` 加 `GET /analysis`(302 到 `/site/index.html`)+
  `GET /site/*`(發 `site/` 目錄底下的檔,跟 `web/` 是分開的兩個目錄)。
  `web/workbench.html` 的 nav 加「前台」分頁,`workbench.js` 的
  `viewAnalysis()` 把它接成 `<iframe src="/analysis">`。跨 iframe 呼叫
  `contentDocument` 切頁籤(`tab2`)驗過,能動。**發現並修掉一個回歸**:
  nav 塞進第 3、4 個項目後,窄版面下文字會逐字換行(缺
  `white-space:nowrap`+`flex:none`),已補。
- ✅ **步驟 6**:`server.py` 加 `POST /api/rebuild`,背景執行緒依序跑
  `.venv/bin/python build.py --write` → `.venv/bin/python make_web.py`,
  沿用既有的 `_JOB["running"]` 鎖(跟抄列互斥)、沿用
  `/api/autofill/status` 輪詢介面。前端 `runRebuild()` 跑完自動把前台
  iframe 的 `src` 重指一次,不必手動重新整理。**端到端跑過一次真的**
  (瀏覽器的 `confirm()` 在自動化環境會被取消,改用 `curl -X POST
  /api/rebuild` 直接打 API 驗證同一段後端邏輯):
  `data.json` 的 `2025H2|玉山|OCI_GB` 從 292 變成 519,跟 build.py 印出的
  diff 一致;iframe 重新整理後前台頁尾的更新時間也從 15:38 跳到 17:02。
  閉環成立。

## 目前的檔案狀態(2026-07-29 執行完後)

`data.json`/`build_manifest.json` 已經被剛才那次真實重建改過(不是模擬)——
這是使用者先前明確同意的行為(重建鈕預設 `--write`)。改動內容就是 build.py
印出的那 35 個單位的差異,多出 `data.json.pre_build` 備份。**尚未 commit,
也沒有 push**——發布到 GitHub Pages 仍然要另外 `git push`,重建鈕本身不會碰。



## 目標

一個本機網頁，最上面一列有 **前台 / 後台** 切換：

```
┌──────────────────────────────────────────────────────────┐
│  銀行債券投資                    [ 前台 ] [ 後台 ]   ⟳重建 │
├──────────────────────────────────────────────────────────┤
│  後台： 待辦  複核台  分桶檢視                             │
│  前台： 個體報表  合併報表  個體更多(估值與獲利)            │
└──────────────────────────────────────────────────────────┘
```

- **前台** = 現在的 `site/index.html`（銀行債券投資債種分析），唯讀，看數字
- **後台** = 現在的 `web/workbench.html`（複核台），可寫，改數字
- **⟳重建** = 跑 `build.py` + `make_web.py`，讓後台剛改的東西當場反映到前台

兩件事一起做：**視覺語言統一**（步驟 1–4）+ **實際併成一頁**（步驟 5–6）。

## 為什麼是一起做，不是先後

切換鈕本身就是統一樣式最強的理由。使用者按一下就在兩個介面之間跳，
如果一亮一暗，那顆按鈕會變成整個產品最刺眼的地方——原本各自獨立時
看不出問題的色差，併在一起就無所遁形。

而真正的價值不在版面合併，在**閉環**：

```
後台改一個分桶 → 按 ⟳重建 → 切到前台，數字已經變了
```

現在這條線是斷的。你改完 `facts/`，得自己開終端機跑兩支程式，才知道
網站上會長什麼樣。接起來之後，「我這個改判會讓玉山的公債曲線變怎樣」
是**看得到的**，不是想像的。

## 現況落差（實測，2026-07-29）

| 項目 | 分析頁 `site/index.html` | 複核台 `web/workbench.html` |
|---|---|---|
| 底色 | `--bg:#f5f6f8` | `--bg:#0b0d10` |
| 卡片 | `#fff` / `1px #e9ebef` / `14px` / `0 1px 2px rgba(16,24,40,.04)` | `#14171b` / `1px #2a2d33` / `10px` / 無陰影 |
| 文字 | `--ink:#111827` `--sub:#5f6672` `--mut:#8a919e` | `--fg:#e5e7eb` `--dim:#9ca3af` `--mute:#6b7280` |
| 分隔線 | `--line:#e9ebef` | `--line:#2a2d33` |
| 主色 | `--accent:#4f46e5`（靛紫） | `--accent:#60a5fa`（亮藍） |
| 字體 | `Inter,-apple-system,"PingFang TC","Microsoft JhengHei"` | `-apple-system,"Noto Sans TC"` |
| 基準字級 | 12–14px | 13–14px |
| h1 | 16px / 600 | 17px / 500 |
| 按鈕 | `.ix-seg`（`#eef0f3` 底的分段控制） | `.pri` / `.dan`（實心色塊） |
| 表格 | `table.wide`，`#f8f9fb` 表頭、sticky 首欄 | `.mx` 矩陣，`border-spacing:4px` |
| 狀態色 | `.rev-badge` 橘（`#9a3412` / `#ffedd5` / `#fdba74`） | `--ok/--warn/--danger` 亮綠黃紅 |

複核台獨有、分析頁沒有對應物的元件（要新設計，不是換色就好）：
`.mx` 覆蓋矩陣、`.cell` 格子鈕、`.bars` 三色進度條、`.two` 左右分割複核版面、
`.row` 科目列、`.pg` PDF 頁圖。

## 關鍵決策：先抽共用 token，不要各寫一份

這個專案已經在 `BANK_COLORS` 上踩過一次「同一個顏色寫在三個地方」
（`make_web.py` 的 `COLOR`、JS 的 `BANKHUE`、JS 的 `VC`，見 `docs/web_redesign_plan.md`）。
樣式統一如果只是把 workbench 的十幾個色碼改成分析頁的值，就是**第四份拷貝**。

所以第一步是建 `web/tokens.css`，作為**唯一設定源**：

```
web/tokens.css      ← 新檔。:root 變數 + .card / .btn / table 等共用元件
    ├─ web/workbench.html   <link> 進來
    └─ make_web.py          產生 site/index.html 時內嵌它的內容
```

`site/index.html` 必須維持**單檔可攜**（GitHub Pages 上是靜態單檔，不能有外部 CSS 請求），
所以那邊是「建置時把 `tokens.css` 讀進來內嵌」，不是 `<link>`。複核台是本機服務，
`<link>` 沒問題。**兩邊來源同一個檔**，這條是重點。

## 順手要修的：分析頁的 CSS 重複了一份

`site/index.html` 有 5 個 `<style>`，其中 **#2 和 #5 是逐字元相同的 7,178 字元**——
`interactive_html()` 被呼叫兩次（個體報表 / 合併報表），CSS 跟著複製。
不處理的話，之後每改一個顏色都要改兩個地方，而且會靜靜地漏掉一個。

修法：`interactive_html()` 的 `<style>` 只在第一次呼叫時輸出（用參數控制，
跟現有的 `include_chartjs` 同一個模式，那個參數已經在做一樣的事）。

---

## 步驟

### 步驟 1：建 `web/tokens.css`

從 `site/index.html` 的第一個 `<style>` 抽出：

- `:root` 全部變數（`--ink --sub --mut --line --bg --accent`）
- `body` 字體堆疊
- `.card`、`.tblwrap`、`table.wide`、`.note`、`.foot`
- `.ix-*` 系列的通用部分（`.ix-seg` 分段鈕、`.ix-ctl` 控制列、`.ix-sub`）

**驗收：** `make_web.py` 改成內嵌 `tokens.css` 後重跑，`site/index.html` 的
**渲染結果與改動前一致**。做法：改動前先存一份 `site/index.html.before`，
改動後開兩個瀏覽器分頁比對三個頁籤的截圖。CSS 順序若有變動可能影響覆蓋，要實際看。

### 步驟 2：`make_web.py` 去重

`interactive_html()` 加 `include_css=True` 參數，合併報表那次呼叫傳 `False`。

**驗收：** 產出的 `site/index.html` 只剩 4 個 `<style>`，且合併報表分頁的
互動圖表、chips、分段鈕外觀全部不變（截圖比對）。

### 步驟 3：複核台換皮

`web/workbench.html` 的 `<style>` 改成 `<link rel="stylesheet" href="/tokens.css">` +
一段只放複核台專屬元件的 `<style>`。`server.py` 要讓 `/tokens.css` 發得出去
（`SITE` 目錄就是 `web/`，`SimpleHTTPRequestHandler` 應該自動就通，實測確認）。

逐元件對照：

| 複核台元件 | 改成 |
|---|---|
| `body` / `nav` | 淺底 `--bg`；nav 改成分析頁 `header` 的白底 + `1px --line` + sticky |
| `.card` | 直接用 tokens 的 `.card`（白底 / 14px / 微陰影） |
| `button` / `button.pri` | 用 `.ix-seg` 的語彙；主要動作維持實心，底色改 `--accent:#4f46e5` |
| `.cell`（矩陣格） | 白底 + `--line` 邊框；hover 邊框轉 `#c6cbd4`（跟 `.ov-chip` 一致） |
| `.bars` 三色條 | 綠黃紅要在**白底上**重新選，現在那組是為深底挑的，直接搬會太亮 |
| `.row.cur` 選中列 | `#1b2431` → 淺色的選中態（參考 `.ix-cfg-panel label:hover` 的 `#f5f6f8`） |
| `.pg` PDF 頁圖 | 邊框改 `--line`；PDF 本身是白底，深色框現在其實是違和的 |
| 狀態色（ok/warn/danger） | 統一改用分析頁 `.rev-badge` 的作法：深色文字 + 淺色底 + 中彩度邊框 |

**⚠ 這一步不是查表換色。** `--ok:#4ade80` 那組亮色是為 `#0b0d10` 底挑的，
放到白底上對比度會不夠（亮綠配白，文字幾乎看不見）。三個狀態色要**重新挑**，
挑完用對比度檢查（正文 4.5:1、大字 3:1），不是目測。

### 步驟 4：PDF 頁圖與矩陣的可讀性回歸

複核台最重要的畫面是「左邊科目列、右邊 PDF 頁圖」對照。換成淺色後
PDF 頁圖會跟背景融在一起（兩邊都白），需要確認：

- 頁圖有沒有明確邊界
- 高亮的那一列在白底上還看得出來嗎
- 覆蓋矩陣的 `·` / `●` / `H` 三態在淺色下還分得出來嗎

**驗收：** 跑 `python3 server.py`，實際開三個分頁截圖，逐項確認。
這一步不能只靠 CSS 讀完就宣告完成。

### 步驟 5：併成一頁 —— 前台/後台切換鈕

**做法：iframe，不做真融合。**

`server.py` 加一條路由（那支的路由表就是一串 `elif`，加一條幾乎零成本）：

| 路由 | 回什麼 |
|---|---|
| `/analysis` | 直接發 `site/index.html`（靜態檔） |
| `/tokens.css` | 步驟 1 的共用 token（`web/` 目錄本來就在發靜態檔） |

`web/workbench.html` 的 `nav` 最右邊加一組 `.ix-seg` 分段鈕（前台 / 後台）：

- 按「後台」→ 顯示現有的三個分頁，`nav` 第二列是 待辦 / 複核台 / 分桶檢視
- 按「前台」→ 整個 `main` 換成 `<iframe src="/analysis">`，第二列頁籤隱藏
  （前台自己有三個頁籤，在 iframe 內部）

**為什麼是 iframe 而不是真融合：** 真融合要拆 `make_web.py` 產出的那一大坨
內嵌 JS（`interactive_html` 一次就 7,178 字元 CSS + 大量 IIFE），讓它跟
`workbench.js` 共存於同一個 document，工程量大得多，而且會把兩邊的
變數命名空間問題全部引爆。iframe 一天做完。

**代價要講清楚：** iframe 之下兩邊 JS 不通，所以
「在前台點某一格 → 跳到後台那一格去修」**做不到**。
這是真融合才有的功能。建議先 iframe 把閉環跑起來，等你確定天天在用，
再評估值不值得為那個跳轉做真融合。

**驗收：**
- 切前台 → 三個頁籤都能點、圖表都畫得出來、帳面/成本切換正常
- 切後台 → 複核台的寫入功能全部正常（改分桶、抄列、自動抄列）
- 來回切五次，iframe 不重複載入到卡頓
- 兩個介面的 header 高度、字級、顏色對得起來（這是步驟 1–4 的驗收）

### 步驟 6：⟳重建按鈕 —— 閉環

`nav` 右側加一顆「⟳重建」，`POST /api/rebuild`：

```
build.py（facts/ → data.json）→ make_web.py（data.json → site/index.html）
```

**四個必須處理的點：**

1. **不准並行。** 沿用 `server.py` 現有的 `_JOB["running"]` 模式——那個機制
   本來就是為「兩份 `fill_auto` 同時跑會搶 `facts/`」設的，重建同理。
   重建期間「自動抄列」也要擋掉，反之亦然。

2. **`make_web.py` 一定要用 `.venv/bin/python`。** 系統 `python3` 沒有 matplotlib，
   會靜靜失敗。（`docs/web_redesign_plan.md` 已經記過這個坑。）

3. **預設寫哪裡要裁示。** `build.py` 預設是 dry-run 寫 `preview/`，`--write` 才動
   `data.json`。重建鈕該按哪一個？
   - 寫 `preview/`：安全，但前台看到的還是舊數字，閉環等於沒接上
   - 寫 `data.json`：閉環成立，但那是**發布用的檔**，本機亂按會讓 git 一直髒
   - **建議**：重建鈕走 `--write`，但明確理解「寫 `data.json` ≠ 發布」——
     發布是 `git push`（GitHub Actions 才會上 Pages），那一步永遠人工。
     這條要你點頭。

4. **重建要多久、跑完怎麼通知。** `build.py` 會由 `facts/` 當次重算 verdict，
   實測數十秒等級；`make_web.py` 要畫兩張 matplotlib 圖。所以是背景工作 +
   進度回報，不是同步等待。沿用 `/api/autofill/status` 的輪詢模式。

**驗收（這一步的重點，不能只看按鈕會動）：**
故意改一個分桶 → 按重建 → 切前台 → **確認那個數字真的變了**。
沒做這個往返，等於沒驗到閉環，只驗到按鈕有反應。

---

## 範圍外（明確不做）

- **不動任何資料流的邏輯**：`build.py` / `bridge_*` / `facts/` 的行為一律不改。
  步驟 6 只是**呼叫**它們，不改它們。
- **不做前台↔後台的深層連動**（點某格跳到後台修）：那要真融合，不是 iframe。
- **不碰 GitHub Pages 發布**：`git push` 永遠人工，重建鈕不會推任何東西。
- **不改版面結構**：只換視覺語言，不重排欄位、不搬按鈕位置。
- **不做深色模式切換**：分析頁本來就沒有，複核台也不留。要做是另一個題目。
- **不動 `docs/plan_ui_redesign.md` 定下的裁示**（範圍只做 2023+、本機服務、頁層級 PDF）。

## 全程的驗收原則

樣式改動最容易出的錯是「看起來對了，但某個狀態壞了」。所以每一步的驗收都要
**實際跑起來截圖**，而且要涵蓋非預設狀態：

- 分析頁：三個頁籤 × 帳面/成本切換 × 至少一個有 `—`（null）的格子
- 複核台：總覽矩陣 / 複核台左右分割 / 分桶檢視，各一張；外加一格 BLOCKED 狀態

`site/index.html` 是 `make_web.py` 的產出（在 `.gitignore` 裡），**不要手改**——
改了會在下次重跑時靜靜消失。

## 要你裁示的一件事

**步驟 6 的重建鈕，預設寫 `preview/` 還是 `data.json`？**（詳見步驟 6 第 3 點）
我建議寫 `data.json`——不然閉環等於沒接上。發布仍然是人工 `git push`，
重建鈕碰不到 GitHub Pages。
