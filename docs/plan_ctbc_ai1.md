# 中信銀「合併(AI1)」抽取 + 上網站 計畫

> 執行者注意:一律用新管線 extract_v2/batch_v2,**不准退回 legacy/unified 或死規則解析器**。
> 背景:現行專案抽 5 家銀行「個體 AI3」;本任務新增 5841 中信的「合併 AI1」序列,期別先做近兩年(2024H1/H2、2025H1/H2),與個體並列放上網站。

## Phase 0:單檔試金石(先做,不下載新檔)
1. `pdf_cache/202402_5841_AI1.pdf` 已存在。臨時把 `batch_v2.py` 的 `KINDS` 改成 `{"AI1"}`(或加參數),`YEARS={"2024"}`,只跑這一份。
2. 驗收:三類(Trading/OCI/AC)是否 pass(對 BS 對帳綠燈)。半年報走主附註 `printed_total` 路徑。
3. 觀察點(合併報告可能的差異):
   - 頁數多很多 → `locate_by_digest` / `locate_notes_all` 的掃描區段(lo/hi)若用固定比例,確認附註仍落在範圍內;不在就放寬範圍,不要手刻頁碼。
   - BS 錨用「資產總計」grep,合併報表同樣有,應可直接中。
   - 附註編號可能不完全是六(三)(四)(五) → 定位靠 LLM 判會計意義,照理沒差;若定位錯,修 prompt 不是加關鍵詞字典。
4. 這一步全綠才繼續;有 `~`(桶警示/弱錨)記下來人工瞄,不阻斷。

## Phase 1:補齊近兩年 AI1 PDF
1. 下載器沿用既有 TWSE 兩段式(`doc.twse.com.tw/server-java/t57sb01`,POST `step=9&kind=A&co_id=5841&filename=...` 拿臨時 /pdf/ 連結再抓)。檔名 `{西元年}{02|04}_5841_AI1.pdf` 放 `pdf_cache/`。legacy/build_report.py 裡有現成下載碼可抄邏輯(只抄下載,不抄解析)。
2. 需要:202404、202502、202504(202402 已有)。

## Phase 2:整批跑 + 驗收
1. `batch_v2` 跑 5841×AI1×近兩年,共 4 份 ×3 類 = 12 格,寫進 `extract_v2_results.json`(key=`YYYYMM_5841_AI1`,與 AI3 key 天然不撞)。
2. 目標 12/12 綠;年報有逐桶成本證人(`bucket_cost_witness`),⚠ 只警示不擋。
3. 改 `KINDS` 時**不要弄壞現行 AI3 批次**:改成 `KINDS={"AI3","AI1"}` 但 AI1 只收 5841(加個白名單條件),或跑完恢復原設定——擇一,程式要能重跑不重抽(有 resume/快取)。
4. Gemini 免費額度 500/天(`.env` 兩把 key),4 份約 30~50 次呼叫,一天內綽綽有餘。

## Phase 3:接進網站
1. `bridge_v2.py`:目前代碼→行名映射是 5841→中信。AI1 要成為**獨立序列**,不能覆蓋個體格。建議行名 `中信(合併)`(bank key 加 kind 後綴判斷:kind==AI1 → 行名加「(合併)」)。
2. 同樣攤進 `data.json` 的 `wide`(帳面)/`wide_cost`(成本)雙口徑;單位仟元÷1e5=億;半年報成本=null、AC 成本=null,規則同現行。
3. `make_web.py` / site:中信(合併)以第 6 個「銀行」欄位出現即可(表格與圖自動吃 data.json 的行清單就不用改;若行清單寫死,加上去)。可考慮在 UI 註記「合併口徑,含海外子行,與其他 5 行個體口徑不可直接相比」。
4. 產出後本機開 site 檢查:雙口徑切換鈕、中信合併欄有值、舊 5 行數字**一格都不能變**(diff data.json 舊備份確認)。

## Phase 4:收尾
- `git status` 目前工作區有大量未 commit 的管線改動(彈性化+證人),先確認不要混進本任務的 commit;分開 commit 或先問用戶。
- 更新 `extract_v2_results.json` 備份習慣照舊(改前先備份)。

## 驗收總表
- [ ] 202402 AI1 三類綠(Phase 0)
- [ ] 4 份 AI1 PDF 齊(Phase 1)
- [ ] 12/12 綠、⚠ 清單列給用戶(Phase 2)
- [ ] data.json 多出中信(合併)、舊格不變、網站顯示正常(Phase 3)
