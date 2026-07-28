# Phase 1 —— 過渡管線:v2 凍結快照 + build.py 唯一建置入口

> 制定 2026-07-27。依據 as-built 稽核(見本文 §0)。
> **本階段不發布、不 push、不改前端、不刪 v2 程式碼、不動 taxonomy。**

---

## 0. 為什麼要做這個(as-built 實證)

| 發現 | 證據 |
|---|---|
| v2 是目前唯一閉環 | `data.json._bridge.source == "extract_v2_results.json"`;CI `report.yml` 只跑 `make_web.py` 讀已 commit 的 `data.json` |
| v3 未閉環,且斷法危險 | `data.json` 無 `_bridge_v3` key(從未寫入);`bridge_v3.py:89` 讀落地檔 `results/verdict.json` |
| **落地 verdict 已過期** | `results/verdict.json` = 2026-07-26 18:21 / 14 格;`facts/` = 2026-07-27 19:54 / 36 格。**落後 25 小時、缺 22 格**,且早於 `衍生金融工具` 修正與兆豐 REIT 裁示 |
| v3 覆蓋率不足以整批切換 | 14 個網站格,三類齊全僅 9 個;網站 `wide` 共 70 格(有值 50 格) |
| schema 錯誤被送去擴頁 | `fill.py:283` `gap = ... if recs and not problems else None` → `problems` 非空時 gap 恆為 None → 落到 `fill.py:308` `loc.expand()` |

**結論**:唯一性要來自「唯一建置入口」,不是來自「v3 覆蓋 100%」。

---

## 1. 發布單位(publish unit)

### 定案:`(期別, 銀行, 類別, 口徑)` 四元組

```
unit = (period, bank, cls, basis)
       2024H2 | 國泰 | Trading | wide
對應 data.json 的欄位集合:  data[basis][f"{period}|{bank}"][f"{cls}_{bucket}"]  ∀ bucket ∈ WIDE_BUCKETS
```

### 為什麼 `(期別,銀行,類別)` 三元組不夠 —— 實測

v3 對同一個 `(期別,銀行,類別)` 可能**只有一個口徑合格**。實測 8 處衝突:

```
wide       2023H1|中信 OCI      v3=null(逐桶帳面文件裡不存在)  v2 有 7 欄
wide_cost  2023H2|富邦 Trading  v3=null(明細表未抄逐欄合計)   v2 有 4 欄
wide_cost  2024H2|國泰 Trading  v3=null                        v2 有 5 欄
wide_cost  2024H2|富邦 Trading  v3=null                        v2 有 4 欄
wide       2025H1|中信 OCI      v3=null                        v2 有 7 欄
wide_cost  2025H2|國泰 OCI      v3=null                        v2 有 5 欄
wide_cost  2025H2|國泰 Trading  v3=null                        v2 有 5 欄
wide_cost  2025H2|富邦 Trading  v3=null                        v2 有 4 欄
```

用三元組 → 採用 v3 就會把上列 v2 數字抹成 null(違反 §3 禁令);
用四元組 → `wide` 走 v3、`wide_cost` 保留 v2,**兩者各自有明確 provenance**。

### 不納入 Phase 1 的單位

- `wide_consol` / `wide_cost_consol`(中信合併 AI1):`bridge_v3.cell_of()` 對 `AI1` 回 `None`,
  v3 尚無對應映射。**整塊沿用 v2 凍結快照**,provenance 記為 `v2(合併報表 v3 未支援)`。
- `data` / `review` / `wide_metrics` / `periods` / `banks` 等非發布單位欄位:
  **逐字沿用凍結快照**,build 不得改寫。

---

## 2. 凍結快照(frozen snapshot)

```
snapshots/v2_frozen_<YYYYMMDD>.json   當前 data.json 的完整副本,chmod 444
snapshots/MANIFEST.json               來源、建立時間、sha256、產生它的 v2 產物
```

- 快照是 **build.py 的唯讀輸入**,任何情況下不得被 build 覆寫。
- `bridge_v2.py` / `bridge_v3.py` 加**寫入防護**:直接拒絕寫 `data.json`,提示改用 `build.py`。
  程式碼不刪(out of scope),只是關掉寫入口。

---

## 3. build.py —— 唯一建置入口

### 鐵則

1. **唯一寫入者。** 只有 `build.py` 可以寫 `data.json`。
2. **當次重建。** v3 結果一律在本次執行內由 `facts/` + 現行分類邏輯算出
   (`results.build()`),**不得讀取 `results/verdict.json`**。程式內以斷言防止。
3. **回退保底。** 不合格的單位一律回退凍結快照。
4. **禁止 null 覆寫。** v3 缺失 / 失敗 / 不完整,一律不得寫入該單位;
   保留 v2 值。**v3 的 null 永遠不會抹掉 v2 的數字。**
5. **保留集排除。** `holdout.HOLDOUT` 的格永不進入發布。

### v3 發布資格(保守定義)

單位 `(period,bank,cls,basis)` 採用 v3 **必須全部成立**:

```
① 該格 key 存在於本次重建的 verdict
② verdict[key]["pass"] is True              （六道檢查全過）
③ verdict[key][basis] is not None           （該口徑在文件裡存在且 View.ok）
④ 七個 wide 桶齊全
⑤ key ∉ holdout
```

任一不成立 → 回退 v2,並記錄**具體原因**。

### 資料流

```
snapshots/v2_frozen_*.json ──┐
                             ├─► build.py ─► preview/data.json
facts/ ──► results.build() ──┘              preview/build_manifest.json
  (當次重建,含 buckets/wide 現行邏輯)
```

### 執行模式

```
python3 build.py              # dry-run:寫 preview/,印差異摘要。預設
python3 build.py --write      # 寫 ./data.json + ./build_manifest.json(Phase 1 不執行)
python3 build.py --diff       # 只印差異,不寫任何檔
```

**Phase 1 只跑 dry-run。**

---

## 4. build metadata

`build_manifest.json`(與 `data.json` 相鄰):

```json
{
  "build_timestamp": "...",            // 只在 manifest,不進 data.json(保持可重現)
  "code_revision":   {"git": "...", "dirty": false},
  "inputs": {
    "frozen_snapshot": {"path": "...", "sha256": "...", "source": "extract_v2_results.json"},
    "facts":           {"sha256": "...", "cells": 36},
    "decisions":       {"sha256": "...", "files": ["buckets.py", "config.py"]}
  },
  "units": [
    {"unit": "2024H2|兆豐|OCI|wide", "provenance": "v3", "reason": "v3 合格"},
    {"unit": "2024H2|國泰|Trading|wide_cost", "provenance": "v2",
     "reason": "v3 該口徑為 null:沒有來源逐項是成本口徑…"}
  ],
  "counts": {"v3": 0, "v2": 0, "conflicts": 0}
}
```

`data.json` 內只放 **確定性** 的 `_build`(輸入的 revision,**不含 timestamp**),
確保同輸入重跑 byte-identical。

---

## 5. 驗收(test_build.py)

| # | 命題 | 方法 |
|---|---|---|
| T1 | 同一輸入重跑結果完全一致 | 連跑兩次,`data.json` payload 逐 byte 相同 |
| T2 | v3 不完整時 v2 值不消失 | 對 8 處已知衝突斷言:輸出 == 凍結快照的值,且 provenance == v2 |
| T3 | v3 合格時正確覆蓋 | 對 9 個三類齊全的格斷言:輸出 == 當次重建的 v3 值,provenance == v3 |
| T4 | 不讀過期 verdict | 把 `results/verdict.json` 換成毒餌(內容明顯錯誤)後重跑,輸出不變 |
| T5 | 每格可追溯 | 每個非空發布單位在 manifest 中都有 provenance 與 reason |

---

## 6. 保守預設與可回滾性

| 情境 | 預設 | 理由 |
|---|---|---|
| v3 判 null 但 v2 有值 | **保留 v2,標記 conflict** | 抹成 null 會改變已發布財務數字 → 需使用者裁示(Phase 2) |
| v3 合格但 v2 該格為空 | 採用 v3 | 新增,非覆寫 |
| 快照缺該單位 | 留空 | 不猜 |
| v3 與 v2 數值不同但兩者皆合格 | 採用 v3,差異列入 preview 報告 | v3 是目標管線;差異必須逐筆有解釋 |

回滾:Phase 1 不寫 `data.json`。即使日後 `--write`,亦先備份 `data.json.pre_build`。

---

## 7. 明確 out of scope

- ❌ taxonomy 架構、agent classification、facts/decisions 分離
- ❌ 前端 / `make_web.py`
- ❌ 刪除 `extract_v2.py` / `batch_v2.py` / `bridge_v2.py`
- ❌ 發布網站、git push
- ❌ 修 `fill.py` 的四條失敗路徑(已記錄,留 Phase 2)
