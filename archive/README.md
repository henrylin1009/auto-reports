# archive/ — 已退役的抽取世代(勿再執行)

⚠️ **2026-08-11 更新**:下面這段「現行資料流」是舊的,已經不現行了 ——
`bridge_v2.py` 早就刪掉、`extract_v2.py` 本身也在 R5-2(見
`docs/plan_v6_一台機器.md`)移進了 `root_scripts_2026-08-11/`。**現行資料流
是 `v4/reader.py`(呼叫 `claude -p`)→ `facts.db`(三張表,`db.py`)→
`build.py` → `data.json` → `viz_generic.py`/`make_web.py`。** 下面這段留著
只為了解釋這批更早的檔案(`extract_megabank.py` 等)彼此的關係,不要照著
它去找「現行」路徑。

這些是被 `extract_v2.py` 取代的更舊抽取程式與其附屬工具(而 `extract_v2.py`
自己後來也被 `v4/reader.py` 取代)。保留只為追溯歷史,**不在現行網站
資料流內**,請勿再執行。

## 這裡描述的那個世代的資料流(已退役,只為追溯歷史)

```
resolve.py(抓檔)
  → batch_v2.py(+面板跨期驗證)
  → extract_v2.py(+key 輪替 / 錨可疑 / total_assets 上界)
  → extract_v2_results.json
  → bridge_v2.py  ← 這個世代的唯一寫入者(已刪除)
  → data.json(+review 待複核旗標)
  → make_web.py → site/
```

設定源:`config.py`(銀行 / 桶 / 容差 / 模型)。
估值/獲利分頁另由 `phase0.py`→`phase0.json`、`extract_pnl.py`→`pnl.json` 供應
(`phase0` 對兆豐仍 `from archive.extract_megabank import …`)。

## `root_scripts_2026-08-11/`

R5-2 從根目錄搬過來的 19 支 `.py`——實測從 `app.py`/`server.py`/`build.py`
等任何真正的入口都到不了,也沒有任何測試 import 它們。**搬過來,不是
刪掉**:有幾支的研究結論已經寫進 `docs/`(例如 `analyze_oci_div.py` 對應
`docs/ac_oci_發現彙整.md`),移動而非刪除保留了「這個結論是怎麼算出來的」
這條線索。

| 檔案 | 原用途 | 退役原因 |
|---|---|---|
| `compute_data.py` | **舊的 data.json 寫入者**(regex) | 與 `bridge_v2.py` 雙寫同一檔的地雷;改由 bridge_v2 獨寫 |
| `extract2.py` / `extract3.py` | 逐版型 regex 抽取(summary/國泰/兆豐) | 被 `extract_v2` 的通用視覺管線取代 |
| `extract_megabank.py` | 兆豐座標式特例解析 | 主債種改走 extract_v2;phase0 仍可 import |
| `batch.py` / `batch3.py` | 舊批次跑者 | 被 `batch_v2.py` 取代 |
| `poc_extract.py` | 概念驗證 | — |
| `list_status.py` / `export_wide.py` / `export_excel.py` | 依賴 extract3 的工具 | 隨 extract3 一併退役 |
