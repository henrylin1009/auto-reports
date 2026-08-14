# 財報分析工具 —— 銀行債券投資（示範資料集）

把財報 PDF 變成可以核對、可以看的分析，全程在網頁上操作，運算用你自己的
Claude Code（不需要 API key，不需要付費）。

**▶ 目前的公開儀表板（示範資料集）：** https://henrylin1009.github.io/auto-reports/

六家台灣銀行的債券投資組合是內建的**示範資料集**，不是交付物——它存在的
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

**macOS 最省事:clone 完直接雙擊 [`啟動.command`](啟動.command)。** 第一次執行
會自動建虛擬環境、裝依賴、開工作台(實測從裸 clone 到網頁跑起來約 1 分鐘),
之後每次雙擊直接開。

手動跑的話:

```bash
git clone <this repo> && cd auto-reports
python3 -m venv .venv                      # 這一步不能省,見下方說明
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                    # 起工作台 http://127.0.0.1:8765
```

⚠️ **一定要先建虛擬環境。** 現在的 Homebrew / Debian Python 依 PEP 668 會擋掉
直接 `pip install`,錯誤訊息是 `error: externally-managed-environment` ——
這不是這個專案的問題,但你會在第一步就撞到。`啟動.command` 已經幫你處理掉。

打開後在「資料」頁把一份 PDF 拖進網頁上傳,系統會自動排隊用你的
Claude Code 讀取、驗算、分類。看到「要人看」的格子,點進去核對原始頁,
按「我看過原始頁,照這樣歸檔」寫進事實庫。改完按「重建」,`data.json`
就會照最新的事實庫重算。

### clone 下來會拿到什麼、不會拿到什麼

| | 進 git | 說明 |
|---|---|---|
| `data.json`(算好的發布資料) | ✅ | **clone 完直接雙擊 `啟動.command`(或 `.venv/bin/python app.py`)就看得到全部圖表**,不必重建 |
| `facts/*.json`(事實庫) | ✅ | 70 份、203 格,人可讀的 diff |
| `pdf_cache/*.pdf`(原始財報) | ❌ | 太大,而且 `python3 app.py fetch` 抓得回來(需要台灣網路,TWSE 擋雲端 IP) |
| `facts.db` | ❌ | 由 `facts/*.json` 匯入而來,沒有它會自動直讀 JSON |

**沒有 PDF 時**:網頁、圖表、模擬器全部能用;`build`(重算)和 8 支要開 PDF
驗算的測試會停下來並告訴你去跑 `app.py fetch`。這是刻意的 ——
驗算的定義就是「合計對得上原始財報的資產負債表」,沒有原始檔就不該假裝驗過。

```bash
# 以下一律用虛擬環境裡的 python(下面寫 .venv/bin/python,不是 python3)
.venv/bin/python run_tests.py         # 35 支(沒有 PDF 時 27 支,其餘明確跳過)
.venv/bin/python app.py build --diff  # 由 facts/ 重算,只印差異不寫檔
.venv/bin/python app.py build --write # 寫入 data.json
.venv/bin/python app.py migrate       # facts/*.json → facts.db(三張表儲存後端)
.venv/bin/python app.py fetch         # 抓最新財報(需要台灣網路,TWSE 擋雲端 IP)
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

國泰(5835)、富邦(5836)、中信(5841)、兆豐(5843)、玉山(5847) 五家較完整,
華南(5838) 目前只有 2025H2 一格、且兩個口徑各缺一類(帳面缺 AC、成本缺
Trading);第一(5844) 已抄但一格都還發不出去,所以不在發布清單裡。個體財報
（entity-level,非合併）,來源 TWSE 公開資訊觀測站。分類:FVTPL(Trading)、
FVOCI(OCI)、攤銷後成本(AC),桶:政府公債/公司債/金融債/資產基礎證券/
貨幣市場/其他/股票。

**實際涵蓋率(2026-08-14 實測,別當成滿的)**:逐桶表帳面 35%、成本 50%;
首頁那張四桶長條圖有「三類全齊才畫」的規則,所以只涵蓋 14 格
(兆豐/國泰/富邦 各 3、玉山 3、中信 2 —— 華南湊不齊,進不了首頁但逐桶表看得到)。
近三年（2023 起）涵蓋率高,更早期的半年報有不少是資產負債表頁為掃描影像、
無法核對錨值的情形,誠實標記為缺資料而非猜測。

## 技術堆疊

Python（標準庫 http.server,零框架）· `claude -p`（抽取,你自己的訂閱）·
SQLite（三張表儲存）· pdfplumber/pypdfium2（PDF 讀取）· 手刻 HTML/CSS/JS
（工作台）· GitHub Actions（CI,render-only,不碰 TWSE）。

## 開發文件

**先看 [`docs/現況.md`](docs/現況.md)** —— 它是唯一的入口索引,說明 40 份文件
哪幾份還有效、哪幾份已作廢。不要直接挑一份 `plan_*.md` 讀,編號大的不一定
是最新的結論(v8 在寫完當天就被自己作廢了)。

逐項驗收記錄與實測證據見 [`docs/plan_v7_完成品.md`](docs/plan_v7_完成品.md)
(R0–R4 全部完成),之後的增修見 v9/v10/v11。
