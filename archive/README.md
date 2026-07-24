# archive/ — 已退役的抽取世代(勿再執行)

這些是被 `extract_v2.py`(章錨→LLM 視覺→對帳,現行)取代的舊抽取程式與其附屬工具。
保留只為追溯歷史,**不在現行網站資料流內**,請勿再執行。

## 現行資料流(唯一路徑)

```
resolve.py(抓檔)
  → batch_v2.py(+面板跨期驗證)
  → extract_v2.py(+key 輪替 / 錨可疑 / total_assets 上界)
  → extract_v2_results.json
  → bridge_v2.py  ← data.json 的【唯一寫入者】
  → data.json(+review 待複核旗標)
  → make_web.py → site/
```

設定源:`config.py`(銀行 / 桶 / 容差 / 模型)。
估值/獲利分頁另由 `phase0.py`→`phase0.json`、`extract_pnl.py`→`pnl.json` 供應
(`phase0` 對兆豐仍 `from archive.extract_megabank import …`)。

| 檔案 | 原用途 | 退役原因 |
|---|---|---|
| `compute_data.py` | **舊的 data.json 寫入者**(regex) | 與 `bridge_v2.py` 雙寫同一檔的地雷;改由 bridge_v2 獨寫 |
| `extract2.py` / `extract3.py` | 逐版型 regex 抽取(summary/國泰/兆豐) | 被 `extract_v2` 的通用視覺管線取代 |
| `extract_megabank.py` | 兆豐座標式特例解析 | 主債種改走 extract_v2;phase0 仍可 import |
| `batch.py` / `batch3.py` | 舊批次跑者 | 被 `batch_v2.py` 取代 |
| `poc_extract.py` | 概念驗證 | — |
| `list_status.py` / `export_wide.py` / `export_excel.py` | 依賴 extract3 的工具 | 隨 extract3 一併退役 |
