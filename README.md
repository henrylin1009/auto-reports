# 財報分析工具 —— 銀行債券投資（示範資料集）

把財報 PDF 變成可以核對、可以看的分析，全程在網頁上操作，運算用你自己的
Claude Code（不需要 API key，不需要付費）。

**▶ 目前的公開儀表板（示範資料集）：** https://henrylin1009.github.io/auto-reports/

五家台灣銀行的債券投資組合是內建的**示範資料集**，不是交付物——它存在的
目的是證明這台機器會動。這個 repo 真正的產物是一套可以核對任何一批
「PDF 財報 → 結構化數字 → 視覺化」資料的工具鏈。

---

## 這是什麼

三層,各自獨立測試過:

| 層 | 做什麼 | 對應模組 |
|---|---|---|
| **抽取** | 把財報 PDF 讀成結構化的表格資料 | `v4/reader.py`（呼叫你自己的 `claude -p`） |
| **核對** | 每一格數字都要有算術證明對得上資產負債表,證不了就是 `null`,不猜 | `results.py` / `core/closure.py` / `wide.py` |
| **視覺化** | 矩陣、逐桶表、時間序列 | `make_web.py`（公開儀表板）/ `web/workbench.js`（核對台）/ `web/sim.js`（模擬器） |

資料存在三張表（`documents` / `observations` / `rulings`,見 `db.py`）：
機器抄的進 `observations`,人在網頁上改過的進 `rulings`,**人工永遠蓋過
機器**。進 git 版控的是它匯出的 `facts/*.json`（人可讀的 diff）,不是資料庫
本身。

## 怎麼跑

受眾是**會 clone、自己有 Claude Code 訂閱的人**——這是 2026-08-12(v7 R4)
明確裁定的唯一分發路徑(原本另外還有一條打包 `.exe`/`.app` 給完全不寫程式的人的
路線,已經移除:那條的核心迴圈「上傳 PDF → 抽取」需要使用者自己的
`claude -p`,不寫程式、沒有 Claude Code 訂閱的人拿到執行檔也只能看示範資料、
無法加自己的銀行,兩者的受眾其實互相矛盾)。

```bash
git clone <this repo> && cd auto-reports
python3 app.py          # 起工作台,自動開瀏覽器 http://127.0.0.1:8765
```

或雙擊 [`啟動.command`](啟動.command)（macOS）——第一次執行會自動建立
虛擬環境、裝依賴,之後每次雙擊直接開。

打開後在「資料」頁把一份 PDF 拖進網頁上傳,系統會自動排隊用你的
Claude Code 讀取、驗算、分類。看到「要人看」的格子,點進去核對原始頁,
按「我看過原始頁,照這樣歸檔」寫進事實庫。改完按「重建」,`data.json`
就會照最新的事實庫重算。

```bash
python3 app.py build --diff     # 由 facts/ 重算,只印差異不寫檔
python3 app.py build --write    # 寫入 data.json
python3 app.py migrate          # facts/*.json → facts.db(三張表儲存後端)
python3 app.py fetch            # 抓最新財報(需要台灣網路,TWSE 擋雲端 IP)
```

`app.py` 是**唯一入口**,收的是日常會用到的四件事;其餘研究/除錯用的
腳本仍然各自 `python3 xxx.py` 執行,不重複收進選單（例如
`score_golden.py`、`analyze_oci_div.py` 這類一次性分析）。

## 通用性的範圍

2026-08-12 起,這個 repo 的「通用性」明確收窄成**銀行財報，多幾家銀行、
未來的期別**——不是換任意題目。曾經有一層題目無關的通用視覺化層
（`viz_generic.py`，只認 `schema.yaml` 描述的形狀），但它零使用者、
換來的通用性使用者從未用過，已經在 v7 計畫（`docs/plan_v7_完成品.md`
§0.3）退場。加一家銀行的路徑見同份文件 §0.4。

## 資料誠實性

- **不補 0。** 缺欄 = 未揭露 ≠ 0,取不到就是 `null`,前端畫成灰底斜紋。
- **三道恆等式驗證**：逐列相加 = 印出小計、小計拼樹 = 資產負債表錨值、
  分桶完整（沒有列漏分到桶）。任一道不過,整格擋下不發布。
- **人工裁示的稽核軌跡**：`facts/*.json` 裡每一列人改過的都帶 `_src`
  (誰、何時、為什麼),`git log` 是完整歷史。
- **可重現**：同一份 `facts/`,`build.py --diff` 連跑兩次輸出逐位元組相同。

## 銀行債券示範資料集的涵蓋範圍

中信(5841)、國泰(5835)、富邦(5836)、兆豐(5843)、玉山(5847),個體財報
（entity-level,非合併）,來源 TWSE 公開資訊觀測站。分類:FVTPL(Trading)、
FVOCI(OCI)、攤銷後成本(AC),桶:政府公債/公司債/金融債/資產基礎證券/
貨幣市場/其他/股票。近三年（2023 起）涵蓋率高,更早期的半年報有不少是
資產負債表頁為掃描影像、無法核對錨值的情形,誠實標記為缺資料而非猜測。

## 技術堆疊

Python（標準庫 http.server,零框架）· `claude -p`（抽取,你自己的訂閱）·
SQLite（三張表儲存）· pdfplumber/pypdfium2（PDF 讀取）· 手刻 HTML/CSS/JS
（工作台）· GitHub Actions（CI,render-only,不碰 TWSE）。

## 開發文件

現況與計畫見 [`docs/plan_v7_完成品.md`](docs/plan_v7_完成品.md)——
體檢、目標架構、逐項驗收記錄,包含這份 README 描述的每一件事的實測證據。
