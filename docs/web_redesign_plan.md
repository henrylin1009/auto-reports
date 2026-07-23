# 網站改版計劃(給執行模型)

目標檔案:`make_web.py`(單一檔案產生 `site/index.html`)。改完跑 `.venv/bin/python make_web.py`(注意:一定要用 `.venv/bin/python`,系統 python3 沒有 matplotlib),用 `.claude/launch.json` 的 `site` server(port 8799)預覽驗證。**不要動 `data.json` / `bridge_v2.py` / `extract_v2.py`。**

現況導覽(行號以 2026-07-23 版為準,改動後會漂移,請以 grep 為準):
- 銀行色:`COLOR=`(py, L16 靜態圖用)與 JS 的 `BANKHUE`(~L230)、`VC`(~L452)三處,**要一起改**。
- 段落組裝在檔尾:`{interactive_html()}{valuation_html()}{profit_html()}{wide_table_html()}`。
- 全域工具列:`ix-bar`(期間 `G_p` / 顯示銀行 `bankchips` / 計入項目 `inclbox`,~L180-198)。
- 時間趨勢圖:Chart.js line,`drawB()`(~L371),x 軸用全域 `PERIODS`。

---

## 任務 1:銀行改用企業品牌色

三處(`COLOR`、`BANKHUE`、`VC`)統一改成品牌色。先用 WebFetch 到 brandfetch.com 或官方網站驗證,驗不到就用下列建議值(玉山已從官網 CSS 實測):

| 銀行 | 建議色 | 依據 |
|---|---|---|
| 中信 | `#046A38` 深綠 | CTBC logo 綠(紅為輔助色,不用) |
| 兆豐 | `#00539F` 深藍 | 需驗證:兆豐 logo 主色(brandfetch.com/megabank.com.tw) |
| 國泰 | `#00584A` 墨綠 | 國泰「大樹綠」 |
| 富邦 | `#0072BC` 富邦藍 | Fubon 藍 |
| 玉山 | `#007A7A` 青綠 | 官網 CSS 實測(#007A7A/#00A19B) |

⚠ 中信/國泰/玉山都是綠系,**必須保持圖上可辨識**:維持上表深淺/色相差(深綠 vs 墨綠 vs 青綠);若驗證後三者太接近,允許微調亮度但保留色相。改完截圖確認時間趨勢圖 5 條線可分辨。
⚠ 債種色(`ALLBONDS`)、分類色(`CLS`/`SC`)**不要動**,只改銀行色。

## 任務 2:時間趨勢圖加起訖期間選擇

在「時間趨勢」的 `ix-ctl` 列(~L216)加兩顆下拉:`B_from` / `B_to`,選項來自 `PERIODS`(預設第一期/最後一期)。`drawB()` 內把 `labels` 與各 dataset 的 data 依 from/to 裁切(`PERIODS.indexOf`)。防呆:from > to 時自動對調。加 `onchange` 重繪。「AC 隱藏損失趨勢」圖(`vt_cv`)也吃同一組起訖。

## 任務 3:「計入項目」改造(重點)

1. **攤開在主頁**:把 `<details class="ix-cfg">計入項目` 從收合面板改成常駐列,放在 `ix-bar` 下方一條橫向工具列(手機可換行)。checkbox 改成 chip 樣式(參考現有 `.ov-chip`)。
2. **快捷鈕**:列前加三顆:`全選`、`只看債券`(GB+公司債+金融債+資產基礎+其他)、`含貨幣市場`(債券+貨幣市場)。點了之後同步所有 chip 狀態並觸發 `syncIncl()` + 重繪(現有 `.inclbox` 的 change handler,~L322)。預設維持現狀(債券全勾、貨幣市場/股票不勾)。
3. **全域選項集中**:「期間 G_p」「顯示銀行 bankchips」也移進同一條常駐工具列(不再藏在 details)。原 `ix-bar` 只留標題資訊。各段落自己的分類/債種下拉(`A_c`/`B_c`/`B_b` 等)**保留**——那是各圖語意,不是全域的。
4. **幣別標示**:所有數據皆為新台幣。在工具列尾端加固定灰字「幣別:新台幣(億元)」即可,**不要做切換鈕**(資料只有台幣一種,做鈕是假選項)。頁尾口徑說明同步補「單位:新台幣億元」。

## 任務 4:分頁 — 第二頁

把這幾段移到第二頁:`valuation_html()`(估值視角+AC 隱藏損失趨勢+利率風險視角)、`profit_html()`(獲利視角 NIM)、`wide_table_html()`(數字明細)。

做法(維持單一 index.html,免多檔部署):
- 兩個 wrapper:`<div id="page1">`(interactive_html)與 `<div id="page2" hidden>`(上述三段)。
- 頂部 header 加分頁鈕(ix-seg 樣式):「總覽」/「估值與獲利」。點擊切 hidden + `window.scrollTo(0,0)`,並用 `location.hash`(`#p2`)記狀態,載入時讀 hash 還原。
- 注意:page2 的 Chart.js 圖在 `hidden` 容器內初次 render 會是 0 寬。**切到 page2 時才初始化(或 resize)那些 chart**——把 valuation/profit 的 chart init 包成 lazy(第一次顯示時執行)。
- 全域工具列(期間/銀行/計入)兩頁都要看得到、狀態共用(工具列放在 wrapper 外面)。

## 驗收清單(每項都要用 preview 實際驗)

1. 五家品牌色三處一致,趨勢圖 5 線可辨識(截圖)。
2. 時間趨勢起訖選擇有效:選 2022H1–2024H2 只畫該區間;from>to 自動對調。
3. 計入工具列常駐可見;三顆快捷鈕各點一次,KPI/跨行比較/趨勢同步變動。
4. 「幣別:新台幣(億元)」在工具列可見。
5. 分頁切換:第二頁含估值/NIM/數字明細;切過去圖表正常渲染(非 0 寬空白);hash 重整後停在原頁。
6. 數字明細「帳面/成本」切換鈕(既有功能)在第二頁仍正常。
7. `.venv/bin/python make_web.py` 無錯誤跑完。

不確定就 grep 現有程式碼照既有慣例做;所有文案繁體中文。
