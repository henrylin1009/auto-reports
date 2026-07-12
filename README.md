# 銀行債券投資 債種分析 — 自動化報表

台灣主要銀行(目前 5835國泰 / 5836富邦 / 5841中信 / 5843兆豐 / 5847玉山,可擴充)**個體**財報,
自公開資訊觀測站(doc.twse.com.tw)抓取,解析「透過損益(Trading)/其他綜合損益(OCI)/
按攤銷後成本(AC)」三分類的債券債種明細,產出**互動網頁儀表板** + 含原生 Excel 圖表的報表。

## ⚠️ 重要前提:抓取必須在「台灣網路」跑
TWSE 會擋 GitHub 等雲端機房 IP(實測:清單有時抓得到、下載常失敗、DNS 時好時壞)。
**所以「抓財報」這一步必須在台灣的機器上跑**(本機 Mac/PC、或台灣 VPS)。
GitHub 只負責「把產好的資料發成網頁」,不抓資料。

## 三個產物 / 三種用法
| 產物 | 給誰 | 怎麼來 |
|---|---|---|
| **互動網頁** https://henrylin1009.github.io/auto-reports/ | 給人看 | 本機產資料 → push → GitHub Actions 發佈 |
| **銀行債券_完整報表.xlsx**(寬表+原生圖表) | 給要檔案的人 | 本機 `python3 build_report.py` |
| **雙擊工具**(exe / .app) | 給非技術者(mentor)自己跑 | GitHub Actions 打包,下載 Artifacts |

## A. 本機產出報表
```bash
pip install -r requirements.txt
python3 build_report.py            # 抓最新財報,產出 xlsx + data.json
```
年份**自動**延伸到當前民國年(START_ROC=109 起),圖表自動取最近 6 期 —— 明年後年跑自動含新財報,免改程式。

## B. 更新網站(本機產 → GitHub 發佈)
```bash
python3 build_report.py
git add data.json 銀行債券_完整報表.xlsx
git commit -m "更新資料" && git push
```
push 後 `.github/workflows/report.yml` 會 **render-only**(只讀已 commit 的 data.json + xlsx、畫圖、發佈 Pages,不抓 TWSE)。
Pages 設定:repo **Settings → Pages → Source =「GitHub Actions」**(一次性)。

## C. 打包雙擊工具給 mentor
`.github/workflows/build-exe.yml`:GitHub 用 Windows / Mac 機器把 `app.py` 打包成單一檔
(打包不需連 TWSE)。到 Actions 該次 run 下載 Artifacts:
- `銀行債券報表-Windows`(.exe)
- `銀行債券報表-Mac`(.zip:含 binary + 「啟動-產生報表.command」)

mentor 在**台灣**執行(TWSE 通):雙擊(Mac 需右鍵→打開過 Gatekeeper)→ 2-3 分鐘 → 同資料夾產出 xlsx。

## 檔案說明
| 檔 | 用途 |
|---|---|
| `build_report.py` | ★ 主程式(檔頭 CONFIG:GAP_WIDTH 間距、CHART_W/H 大小、SHOW_N 圖表期數) |
| `extract3.py` / `extract2.py` | 核心解析 + 三層 checksum 驗算 |
| `resolve.py` | 穩健取檔:自動找「個體」檔(代碼各家/各年不一,如 AI2/AI3),含瀏覽器標頭 |
| `make_web.py` | 讀 data.json 產**互動儀表板網頁**(KPI 結論 + 跨行比較 + 時間趨勢 + 熱力圖;可選計入債種、可篩選銀行;給 GitHub Actions 用) |
| `app.py` | 雙擊工具入口(供 PyInstaller 打包) |
| `run.sh` | 台灣伺服器 cron 進入點(選用) |

## 重要注意
- **兆豐**:債種明細來自其財報「證券部門變動明細表」(座標式排版,與他家彙總表不同,`extract_megabank.py` 專用解析)。其證券部門**無 Trading 部位**,故 Trading 為 0(真實零部位,非缺料)。
- **真 0 vs 無資料**:2020H1 國泰/玉山之個體財報為掃描影像檔、無文字層,無法解析 → 標為 `null`(網頁畫斜線「無資料」),與「真實零部位」區分。抽不到文字層(`len(text)<2000`)即自動歸為無資料。
- **資料可信度**:內建三層 checksum(純證券小計→合計扣除→整表對帳),抽錯會標記不會默默給錯。
- **想全自動免本機**:需台灣/亞洲 VPS 跑 `run.sh` cron(GitHub 雲端會被 TWSE 擋,做不到)。
