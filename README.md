# 銀行債券投資 債種分析 — 自動化報表

五家銀行(5835國泰 / 5836富邦 / 5841中信 / 5843兆豐 / 5847玉山)**個體**財報,
自公開資訊觀測站(doc.twse.com.tw)自動抓取,解析「透過損益(Trading)/其他綜合損益(OCI)/
按攤銷後成本(AC)」三分類的債券債種明細,產出含**原生 Excel 圖表**的報表。

## 產出
`銀行債券_完整報表.xlsx`,分頁:
- **寬表** — 期間 × 五家 × 各指標(Trading_CP+NCD+BA、各分類/債種)
- **圖-按分類 / 圖-按債種** — 原生可編輯圖表(x軸=銀行、每家一色、時間序列)
- **資料_*** — 圖表綁定的來源表

## 一次性安裝(伺服器)
```bash
cd work
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 手動執行
```bash
python3 build_report.py            # 用現有快取,快
python3 build_report.py --refresh  # 先上網補抓當期個體檔(排程用這個)
```

## 定期自動更新(cron)
個體財報一年兩期:H1半年報(約8月)、年報(約隔年3-4月)。建議每月跑一次(含補正/遲交):
```cron
0 3 5 * * /path/to/work/run.sh
```
`run.sh` 會:補抓 → 產出 → 存 `output/銀行債券_完整報表_YYYYMMDD.xlsx` + `_latest.xlsx`,並寫 `logs/`。
把 `output/..._latest.xlsx` 放到共享磁碟/雲端硬碟,同事就永遠拿到最新版。

## 方案B:GitHub 自動跑 + 網頁(推薦,免伺服器)
GitHub Actions 定時跑、GitHub Pages 出網頁給大家看+下載。設定一次,之後全自動。
1. 建一個 GitHub repo(**public**,Pages 免費且財報本為公開資訊),把本資料夾內容推上去。
2. repo **Settings → Pages → Build and deployment → Source 選「GitHub Actions」**。
3. 完成。`.github/workflows/report.yml` 會在 push 時、每月5日、或手動(Actions頁按 Run)自動:
   抓財報 → 產 Excel → 畫圖 → 發佈到 `https://<帳號>.github.io/<repo>/`。
4. 把該網址給同事:可看兩張儀表板圖 + 按鈕下載完整 Excel,每月自動更新。

> 註:若 TWSE 擋雲端 IP 導致抓取失敗,改用方案A(自己伺服器)或 GitHub self-hosted runner。

## 檔案說明
| 檔 | 用途 |
|---|---|
| `build_report.py` | ★ 主程式(檔頭 CONFIG 可調圖表:SHOW_PERIODS 期間、GAP_WIDTH 間距、CHART_W/H 大小) |
| `extract3.py` | 核心解析 + 三層 checksum 驗算 |
| `extract2.py` | Trading 明細解析(被 extract3 引用) |
| `resolve.py` | 穩健取檔:自動找「個體」檔(代碼各家/各年不一,如 AI2/AI3) |
| `run.sh` | 排程進入點 |
| `pdf_cache/` | PDF 快取(已抓過不重抓) |

## 重要注意
- **兆豐**:財報未揭露債種明細 → 圖表留白、寬表相關格空白(先天缺料,非程式問題)。
- **資料可信度**:內建三層 checksum(純證券小計→合計扣除→整表對帳)。抽錯會標記,不會默默給錯數字。
- **調整期間/樣式**:改 `build_report.py` 檔頭 CONFIG 即可,不需動核心。
- 需擴充年份:改 `build_report.py` 的 `ALL_PERIODS`(民國年 range)。
