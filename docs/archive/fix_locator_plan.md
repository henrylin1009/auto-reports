# 定位層修正計畫(三病一次解)

## 病因總結(已用中信/玉山實據驗證)
- **BS 錨可信**(中信 BS 原文:Trading 295,194,288 / OCI 350,691,335 / AC 886,706,260)。
  → recon vs BS 當裁判正確;所有 ❌cross 都是**明細表側**抓取錯,不是 BS 誤讀。
- 明細表地形亂:**同頁多表 + 標題跨行斷字 + 拆流動/非流動/部門子表**。
- 現行單頁 grep 定位在這種版面必敗:抓到子集(中信 OCI 抓到「－流動」28,384,216 而非整體 350,691,335)、或抓對整體卻漏續頁(玉山 Trading 短 37 億)。

## 設計原則
1. **完整性(讀全沒)由 gemini 自報**:多加 `saw_total_row` / `table_continues` 旗標,靠視覺判有沒有讀到收尾「合計」列——對文字湯/掃描頁一樣有效(它看圖不看文字)。
2. **正確性(選對表沒)由 BS 錨判**:讀出的合計 == BS(客觀真值)才收。
3. **有界 fallback**:候選表列舉 → 逐個讀 → 選/加總 == BS 那組;擴頁到 `saw_total_row` 為止。頁數是結果,不是假設。
4. gemini 單模型單呼叫,不引入 deepseek(病灶是「餵錯區域」不是「推理不足」)。

---

## 改動清單

### A. digest() 合併跨行標題(讓整體表浮出候選)
- 現在逐行篩,跨行斷字的標題(「…衡量之」/「金融資產明細表」)被拆掉抓不到。
- 改:先把連續短行黏合再篩,還原完整標題。

### B. 定位改回「每類一串候選頁」(不是單頁)
- `_LOC_SCHEMA`:每類回 `list[int]` 候選起頁(整體 + 各子集都列)。
- `_LOC_PROMPT`:要求把該類所有明細表(含「－流動/－非流動/證券部門」變體)的起頁都列出。
- **列候選求全不求準**:大標題文字命中就當候選,寧可多列。精準度不靠列候選,靠後面 E 的 BS 驗收淘汰。列錯/多列沒差(合計對不上 BS 自動被丟);唯一要避免的是漏掉對的那頁。
- **降級**:極少數整頁純掃描、連大標題都不在文字層 → 退到把章範圍頁面影像餵 gemini 問哪頁是表(例外路徑,非主路徑)。

### C. read_detail 加完整性旗標
- `_DET_SCHEMA` 增:
  - `saw_total_row`(bool):有沒有看到收尾「合計/總計」列。
  - `table_continues`(bool):最後一列是否表示表延續到下頁。
- `_DET_PROMPT` 對應說明。

### D. 新 read_detail_windowed(path, start, cls) — 擴頁迴圈
```
window = [start, start+1]
for _ in range(MAX_EXPAND=2):      # 最多擴到 4 頁
    det = read_detail(path, window, cls)
    if det.saw_total_row and not det.table_continues:
        return det                 # 讀到表尾,停
    window.append(window[-1]+1)    # 擴一頁重讀
return det                          # 擴到上限仍回最後一次(交給 BS 驗收判)
```
→ 解**玉山跨頁**(自動擴到看見合計列)。

### E. 新 select_detail(path, candidates, cls, bs) — BS 導向候選(有界 fallback)
```
reads = [read_detail_windowed(path, c, cls) for c in candidates]
# 1) 單張命中:某張 value_total == BS → 收
for r in reads:
    if abs(r.value_total - bs) <= TOL: return r
# 2) 加總命中:若干子表 value_total 相加 == BS → 合併 rows 收(流動+非流動)
combo = subset of reads whose value_total 相加 == BS
if combo: return merge_rows(combo)
# 3) 都不中 → 回最接近的,標 _needs_review(人工佇列)
return best_effort
```
→ 解**中信同頁多表/子集**(自動選/加總出 350,691,335 那組)。

**分工原則(重要)**:感知(讀合計)交給 gemini 影像;判斷(選哪張)交給**規則算術**對 BS,不讓 LLM 主觀判「哪張才對」——那正是「中信抓子集」的病根。候選 1~3 張,單張→兩兩組合窮舉,每步拿 BS 驗,確定性、免費、可重現。

### F. is_halfyear(path) + 半年報路由主附註
- 判別:檔名 `_02_` = 半年報(`_04_` = 年報)。
- 半年報:**跳過明細表定位**,直接用主附註(`read_subtotals_all` 已有)當**輸出來源**:
  - buckets = 主附註各桶小計;cost = NA(半年報主附註無取得成本欄)。
  - 對帳:sum(subtotals) == BS(cross);無 internal(無印出合計逐行)。
  - `_source = "note"` 標記,和年報明細表來源區分。
→ 解**半年報無整體表**(不再硬找不存在的表)。

### G. extract_all 重接線
```
半年報 → 每類走 note-primary(F)
年報   → 每類:candidates = loc[cls]
              det = select_detail(candidates, bs)   # D+E
              validate(cls, det, bs, note_sub)      # 沿用;桶仍只警示(方案A)
```

---

## API 呼叫預算
- 年報乾淨(單一整體表、單頁):locate1 + BS1 + note1 + 每類 1 讀 = **~6**(不變)。
- 需擴頁/多候選:每類多 1~3 讀(僅失敗時觸發)。
- 半年報:locate 省掉、只 note + BS + 各類 note-primary = **更少**。

## 驗收
改完重跑 20 份,期望:
- ❌cross(明細表抓錯)大幅轉綠(中信/玉山類)。
- ⚠定位(半年報)轉為 note-primary 綠燈或明確標示。
- ⚠桶 維持警示不阻斷(方案 A 已生效)。

## 分步(便宜先行)
1. **F 半年報路由**(小、獨立、立刻收半年報)+ **D 擴頁**(收玉山)。
2. 重跑看剩幾格紅。
3. **A~C+E BS 導向候選**(較大)收同頁多表/子集。
4. 再重跑出最終成績單。
