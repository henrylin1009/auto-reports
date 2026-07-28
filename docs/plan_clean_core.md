# Clean-core migration —— Phase A 主幹統一 / Phase B 語意邊界修正

> 制定 2026-07-27,取代同名初版。使用者已裁示保留:搬家策略、`out/` 不回讀、
> anchors 固化、平行等價閘門、v2 frozen snapshot。
> **新增**:拆成兩個 phase,並在 C0 之前先裁定並測試三件事(§1)。
>
> 前提不變:不重抄 PDF、不重做定位演算法、不先刪舊程式。

---

## 0. 實測基準

### 0.1 初版已量到的

| 量測 | 數字 |
|---|---|
| 測試現況 | 9 綠 / `test_build.py` **跑不完 2 分鐘** |
| 事實庫 | 36 格 / 15 份 PDF / 583 列 / 75 個相異列名 / 20 個相異 group |
| 發布單位 | v3 57 / v2 326(其中 **315 是「facts 尚未抄錄」**)/ 衝突 8 |
| `results.build(36 格)` | **56.5 秒** → 每份 PDF 只 locate 一次 22.4 秒 → **只餵錨值 0.003 秒,verdict 逐位元組相同** |

`transcribe.verify()` 對 `Located` 的全部用途只有 `check_anchor()` 裡的
`loc.anchors[cls]`(一個整數)。判定層與投影層沒有任何一行碰 PDF,卻每格重解析一份
139~200 頁的 PDF。→ **錨值必須升格成被記錄的事實。**

### 0.2 為裁定四件事新量的(這批改變了初版的答案)

**M1 —— `data.json["data"]` 與 `wide` 是同一個會計事實的兩份表述,而 `build.py` 只寫後者。**

```
snapshot["data"] != preview["data"]   → False   (build.py 從不寫 data 區塊)
snapshot["wide"] != preview["wide"]   → True
```

`data` 用舊四桶(公債/公司債/金融債/其他,168 格全部只有這四個 key),
`wide` 用新七桶。取 1:1 對得上的三個桶(公債↔GB、公司債、金融債),
對 31 個「v3 已採用」的 wide 單位比對 93 個點:

```
不一致 21 處。最大三處全是玉山公債(國外機構發行債券改判):
  2024H2|玉山 AC   公債   data(v2)= 238.57   wide(v3)= 800   差 -561.43 億
  2024H2|玉山 OCI  公債   data(v2)= 419.67   wide(v3)= 788   差 -368.33 億
  2025H2|玉山 OCI  公債   data(v2)= 292.24   wide(v3)= 519   差 -226.76 億
```

→ 今天若跑 `build.py --write`,**同一頁上「分類檢視」會顯示 419.67 億、
「寬表檢視」會顯示 788 億,而且沒有任何 provenance 標記告訴讀者為什麼**。
這不是 v3 的 bug,是**發布單位切得比一致性邊界還小**。

（附註:第一次比對我把 `data` 的「其他」對到 v3 的 其他+資產基礎+貨幣市場+股票,
量出 51 處不一致 —— 那是我對桶對錯了,`data` 是債券口徑不含股票與貨幣市場。
上面 21 處只用 1:1 對得上的三個桶,是乾淨的。）

**M2 —— 改用三元組 all-or-nothing 的代價,是 31 → 24 個單位。**

```
wide 採 v3 的三元組                    31
  其中 wide + wide_cost 都合格         24   ← 三元組規則下可採用
  只有 wide 合格(整格退回 v2)          7
     2021H1|玉山 OCI · 2023H2|富邦 Trading · 2024H2|國泰 Trading ·
     2024H2|富邦 Trading · 2025H2|國泰 OCI · 2025H2|國泰 Trading · 2025H2|富邦 Trading
```

**M3 —— `rules.propose()` 提不出候選,兩種完全相反的東西都會落在裡面。**

```
透過其他綜合損益按公允價值衡量之權益工具投資   bucket=None   propose=None   ← 小計,不是科目
透過其他綜合損益按公允價值衡量之債務工具投資   bucket=None   propose=None   ← 小計,不是科目
不動產投資信託受益證券(兆豐)              bucket=資產基礎  propose=None   ← **真科目**,人工裁示
國外機構發行債券(玉山)                  bucket=公債     propose=None   ← **真科目**,人工裁示
基金受益憑證(國泰)                     bucket=股票     propose=股票    ← 真科目,規則提得出
```

→ **「提不出候選」不能推論成「頁沒找全」。** 已知案例裡它一半是小計、一半是真科目;
用它決定要不要擴頁等於擲硬幣。這是 §1 R4 的直接證據。

**M4 —— 擴頁的真實觸發來源(`locate.EXPAND_TRUTH` 11 格逐格量)。**

10 格的正確頁不在第一層候選裡(需要擴頁),按觸發訊號分解:

| 觸發訊號 | 格數 | 案例 |
|---|---|---|
| **①② 表內算術** | 5 | 國泰 202102 Trading(p34 單頁相加 ≠ 錨,小計在 p33);中信 AI1 OCI ×3 + AI3 OCI ×1(債務小計在前一頁) |
| **⑤ 分類** | 5 | 玉山 OCI 子附註家族(202102 AI3/AI2、202302、202402、202502) |
| **③ 跨表** | 0 | — |
| 不需擴頁 | 1 | 富邦 202304 Trading(正確頁已在第一層) |

玉山那 5 格逐格讀頁文字驗證過,第一層頁上就是兩列小計,**精準等於錨**:

```
202102  16,018,428 + 271,692,749 = 287,711,177   ①②④ 全綠,唯一失敗的是 ⑤
202302  14,248,122 + 327,683,118 = 341,931,240   同上
202502  23,130,069 + 292,943,799 = 316,073,868   同上
```

**M5 —— 第 3 道切不開,而且它的退化路徑是壞的。**

原本想用「`check_cross(recs, bk=None)` 通過但 `bk=buckets` 失敗 ⇒ 純分類造成」
把第 3 道的兩種失敗切開。實測**那條路徑一跑就炸**:

```
transcribe.py:337  _by_bucket(a, b, None) → bad 回傳 list
transcribe.py:293  _merged() 當它是 dict  → AttributeError: 'list' object has no attribute 'items'
```

docstring 寫了、沒有任何呼叫端用過的退化路徑。**這是潛伏 bug,本計畫不修**
(它在禁改清單裡,且今天無人呼叫),但它證明第 3 道**今天沒有可用的純算術版本**。

另外量到:29 / 36 格有兩份以上 record(第 3 道適用),其中 **17 格兩份口徑不同**
—— 所以「不給 buckets 就退化成純算術比對」在設計上也不成立,對齊本身就需要分桶知識
(`transcribe.align` 的 docstring 自己說了「這層相依是真的」)。

**M6 —— 擴頁在實務上很罕見。** 36 格裡只有 2 格用過擴張
(`202504_5835_AI3` 的 AC 與 Trading,level=2 retries=2),其餘 34 格 level=0。
(其中 19 格是早期遷移進來的,沒有 `_by` 稽核欄位。)

---

## 1. C0 之前必須裁定並測試的四件事

### R1 —— 發布切換的 atomic unit

**裁定:atomic unit = `(期別, 銀行, 類別)`。採用是 all-or-nothing,
一次切換該格的每一個投影(`data`、`wide`、`wide_cost`)。**

初版寫的是四元組 `(期別,銀行,類別,口徑)`,理由是「同一格可能只有一個口徑合格」。
那個理由仍然成立,但 M1 顯示**四元組解錯了問題**:口徑不是獨立的發布物,
`data` / `wide` / `wide_cost` 是同一格的三個投影,而四元組只管了其中兩個。

判準應該是:**atomic unit 的邊界 = 一致性必須成立的邊界。**
一格的三個投影描述同一份持有部位,它們必須同時來自同一個來源;
跨口徑之間沒有算術關係(實測:`make_web.py:78-80` 把 `book`/`cost` 交給前端**切換**,
`wide_metrics` 21 項全是單一口徑;AC 隱藏損失來自 `phase0.json`,不是 wide 減 wide_cost),
但**同一格的三個投影同時出現在同一頁上**,不一致會直接被讀者看見。

採用條件(比初版嚴):

```
一個 unit 採用 v3 ⟺ v3 能供應「快照對該格已填的每一個投影」
                    ∧ 六道檢查通過 ∧ 七桶齊全 ∧ 不在 holdout
否則整格留 v2,一個投影都不動。
```

代價已量:31 → 24(M2)。**這 7 格不是消失,是「還不到切換的時候」**,
它們的缺口是 `wide_cost` 沒有可驗證的成本欄 —— 那是抄列/文件的問題,不是發布策略的問題。

**測試 T-R1**(C0 前寫,必須先紅後綠):

1. `test_unit_atomic`:對每一個已發布的格,斷言 `data`/`wide`/`wide_cost`
   三個投影的 provenance **完全相同**。注入一個混合 provenance 的格 → 必須失敗。
2. `test_unit_consistency`:對每一個 provenance == v3 的格,用 1:1 對得上的三個桶
   斷言 `data` 與 `wide` 一致(容差 1 億,對應四捨五入)。**今天這條會抓到 21 處。**
3. `test_unit_cost`:三元組規則下採用數 == 24,且 M2 那 7 格 provenance == v2。

**推論(必須跟著做,否則 T-R1.2 永遠紅)**:`data` 區塊必須從「v2 獨立輸入」
改成「**與 wide 同源的投影**」—— 由同一份 verdict 用舊四桶映射算出
(`config.LEGACY_BUCKETS` 已存在)。v3 不合格的格,`data` 照樣回退快照。
這是 C4 的工作,不是 C0 的。

---

### R2 —— G9 與 G17 的過渡期規則

兩條護欄:

- **G9**(`build.py` 鐵則 4):v3 的 null 不得抹掉 v2 的數字。
- **G17**(`bridge_v3` 裁示):一格只有兩種下場 —— 有數字,或 null;**不准保留舊值**。

**裁定:兩者不矛盾,因為它們管的是不同層級的東西。矛盾只在「unit 小於一致性邊界」時出現,而 R1 已經把它消掉了。**

分層陳述:

| 層級 | 規則 | 屬於 |
|---|---|---|
| **來源內部** | 一格在 v3 這條路裡要嘛有數字要嘛 null。v3 拒收的格,v3 的輸出就是 null,**不准回頭用 v3 自己上一版的數字** | G17 |
| **跨來源回退** | unit 不合格 → **整格**用 v2。這不是「保留 v3 的舊值」,是「這一格尚未由 v3 接管」 | G9 |
| **不變式** | 每一個發布出去的數字恰好屬於一個來源;**任何 unit 內部不得混來源** | R1 |

有了 R1 的 all-or-nothing,G9 不再是「逐欄挑著保留」的補丁(那才是與 G17 打架的形狀),
而是「這個 unit 的接管尚未發生」。

**但這還不夠 —— 回退必須分三種,不能一律靜默。** 今天 `build.py` 的
`eligible()` 把三種情形都回成同一句「回退 v2」:

| 狀態 | 意思 | 處置 | 今天的數量 |
|---|---|---|---|
| `NOT_YET` | v3 對這格沒有意見(facts 未抄錄) | 靜默回退 v2 | 315 |
| `BLOCKED` | v3 抄了但六道檢查沒過 | 回退 v2 + **列入待辦**,不得靜默 | 0 |
| `CONTRADICTION` | **v3 有意見且與 v2 矛盾** —— v3 判「該口徑在文件裡不存在」而 v2 有數字 | 回退 v2 + **標記為待人工裁示,且必須在 manifest 與網站上可見** | **8** |

`CONTRADICTION` 是唯一真正危險的一種:v3 認為那個數字沒有文件依據,而它繼續掛在網站上。
靜默保留 = 用 G9 的字面意思違反 G9 的目的。

**再加一條防倒退(ratchet)**:一個 unit 一旦由 v3 發布過,就不准再退回 v2。
否則分類表回歸、facts 被誤刪都會讓網站**靜靜地變回舊數字**。
last-published provenance 記在 `published_ledger.json`(進 git,是輸入不是產物)。

**測試 T-R2**:

1. `test_no_mixed_provenance`:同 T-R1.1。
2. `test_fallback_classified`:326 個回退單位逐一有 `NOT_YET`/`BLOCKED`/`CONTRADICTION`
   其一;斷言 8 處衝突全部是 `CONTRADICTION`,**沒有一處被歸成 `NOT_YET`**。
3. `test_contradiction_visible`:`CONTRADICTION` 的格必須出現在 manifest 的
   `needs_ruling` 清單裡;把它從清單移除 → 測試失敗。
4. `test_ratchet`:對一個 ledger 記為 v3 的 unit,餵一份會讓它不合格的 facts →
   build 必須**失敗並指名**,而不是靜靜回退 v2。

---

### R3 —— R-B「唯一輸入四種」的適用範圍

**裁定:R-B 只適用於純層(Ring 1)。ingest 與 anchors 產生器屬於不純層(Ring 0),
它們當然要讀 `pdf_cache/` 與 `state/`。兩層的邊界寫成可測試的規則,不是口頭約定。**

初版的 R-B 寫得太寬,照字面讀會把 ingest 逼進死路 —— 使用者指出得對。

```
Ring 0(不純,可以有 IO / 網路 / 狀態 / 時鐘)
  core.store.anchors   讀 pdf_cache/ → 寫 anchors/
  core.ingest          讀 pdf_cache/ + anchors/ + state/ + agent → 寫 facts/ + state/
  resolve              網路 → 寫 pdf_cache/

Ring 1(純,同輸入必同輸出)
  core.contracts / core.classify / core.reconcile / core.publish
  只讀:facts/ · anchors/ · taxonomy/ · snapshots/ · published_ledger.json
  只寫:out/
  禁止:讀 pdf_cache/ · 讀 state/ · 讀 out/ · import pypdfium2/requests · 讓時鐘進入輸出
```

邊界契約一句話:**Ring 0 的唯一產出是 `facts/` 與 `anchors/`;Ring 1 只吃這兩者。**
`out/` 不回讀這條**兩層都適用**(它是 R-A,與 R-B 無關)。

**測試 T-R3**:

1. `test_ring1_no_pdf`:把 `pdf_cache/` 與 `state/` 改名 → `core verify` 與
   `core build` 仍能跑完,輸出**逐位元組相同**。
2. `test_ring1_imports`:import Ring 1 模組後,斷言 `sys.modules` 不含
   `pypdfium2` / `requests`。
3. `test_ring1_deterministic`:同輸入連跑兩次 payload 逐位元組相同
   (時鐘只准出現在 manifest,不准進 `data.json`)。

---

### R4 —— 分類狀態不得驅動 expand(使用者裁示,2026-07-27)

**裁定:只有「來源 / 表內算術」的失敗可以觸發擴頁。分類的任何狀態
(`UNCLASSIFIED`、`rules.propose()` 提不出候選)一律不得觸發擴頁,
也不得消耗重試預算。分類未知一律走「facts 歸檔 + review queue」。**

理由已量(M3):`propose()` 提不出候選的名字裡,玉山那兩個是**小計**,
兆豐「不動產投資信託受益證券」與玉山「國外機構發行債券」是**真科目**。
同一個訊號指向兩個相反的處置 → 用它路由等於擲硬幣。
**「提不出候選」最可能的意思是「這是個新的真實科目」,不是「頁沒找全」。**

#### 擴頁觸發訊號:白名單(不在名單上的一律不觸發)

| 訊號 | 檢查 | 性質 | 可觸發 |
|---|---|---|---|
| 來源不合法 | `source_page` 不在候選頁集合內 | 來源 | ✅ |
| ①② 列相加 | `check_identity`:`sum(葉列 total_col) != printed_total` | 表內算術 | ✅ |
| ④ 合計對錨 | `check_anchor`:`printed_total != 錨` | 表內算術 | ✅ |
| ⑥ 逐欄合計 | `check_col_totals` | 表內算術 | ✅ |
| ③ 雙表互對 | `check_cross` | **混合訊號,今天切不開**(M5) | ❌ |
| ⑤ 列皆可分桶 | `check_buckets` | 純分類 | ❌ |

**判準是「哪一道檢查失敗」,不是比對錯誤訊息字串。**
(舊的 `fill._taxonomy_gap` 已經踩過這個坑並在 docstring 裡記錄:
照訊息比對會漏判,因為同一個根因會在第 3 道長出第二個症狀。)

#### 代價,逐項量過(M4)

- **①② 覆蓋所有算術驅動的擴頁**(5 格:國泰 202102 Trading 跨頁、中信 OCI ×4 跨頁)
  → 這些格**行為完全不變**。
- **③ 排除的代價是 0** —— 11 格 EXPAND_TRUTH 裡沒有一格靠它觸發。
  這是保守裁定:等它被切成「算術部分」與「配對部分」再談,**不為想像中的困難預先加機制**。
- **⑤ 排除的代價是玉山子附註家族 5 格失去自動回收。** 這是真實代價,不掩飾。
  補償機制見下。

#### 玉山子附註家族的補償(使用者規則允許的範圍內)

那 5 格會變成:第一層兩列小計 → **①②④⑥ 全綠 → Gate 1 通過 → raw facts 歸檔**
(資料不再被丟掉,這本身是進步)→ 兩列都是 UNCLASSIFIED → **Gate 2 擋住,不可發布**
(G1 的安全性質保住)→ 進 review queue。

review queue 的**人工處置選項必須包含三種**,不能只有「收錄 / 退回」:

```
(a) 收錄成新科目        → taxonomy 升級,該名字轉 CONFIRMED
(b) 退回(不是科目)      → 標記,不再提示
(c) **這是小計,頁沒找全 → 人工觸發擴頁**   ← 補償 ⑤ 的唯一出口
```

`(c)` 是**人決定的**,不是程式推論的 —— 符合使用者的規則。
且**人工觸發的擴頁不消耗重試預算**(預算存在的目的是擋自動白燒,不是擋人)。

工單上可以顯示提示(「這格有 2 列 UNCLASSIFIED,`propose()` 提不出候選」),
但**提示不得自動變成動作**。

#### 測試 T-R4

1. `test_expand_whitelist`:`may_expand()` 對「只有 ⑤ 失敗」回 False;
   對「① 失敗」回 True。把 ⑤ 加進白名單 → **必須紅**。
2. `test_expand_not_cross`:「只有 ③ 失敗」回 False。
3. `test_expand_budget`:分類未知的格,`retries` **不增加**;
   讓它增加 → 必須紅。
4. `test_expand_truth_arithmetic`:對 M4 的 5 個算術案例,
   斷言第一層抄錄的失敗訊號**落在白名單內**(行為不變)。
5. `test_expand_truth_classification`:對玉山 5 格,斷言
   `may_expand() == False` 且該格 **Gate 1 通過(可歸檔)** 且 **Gate 2 不通過(不可發布)**。

---

## 2. Phase A —— 建立唯一建置主幹

**目標(只有這個):消除雙管線、過期 verdict、產物回讀、多寫入者。**
**明確不做:不修分類語意。分類行為維持現狀。**

### 2.1 目錄與模組

```
core/
  contracts.py   資料契約。唯一知道磁碟形狀的地方                    Ring 1
  store.py       facts/ anchors/ taxonomy/ ledger 讀寫 + 雜湊        Ring 0/1 邊界
  classify.py    分類唯一入口(Phase A 只是轉呼叫 buckets/rules)      Ring 1
  reconcile.py   (cell, anchor) → Verdict。純函數                    Ring 1
  ingest.py      抄列迴圈唯一實作                                     Ring 0
  route.py       純函數:submission → PASS/RETRY/BLOCKED/REJECT       Ring 1*
  publish.py     Verdict + 快照 + ledger → data.json + manifest       Ring 1
  cli.py         唯一入口

anchors/{doc}.json      新:錨值 + 候選頁 + pdf_sha256
published_ledger.json   新:每個 unit 最後一次發布的 provenance(R2 ratchet)
taxonomy/               C2 才動(見 §2.5)
state/                  取代 work/;state/inbox/ 是 agent 寫入的唯一位置
out/                    所有產物。.gitignore
facts/ snapshots/       不動
```

`route.py` 標 Ring 1* 是因為它是純函數,但被 Ring 0 呼叫。

### 2.2 資料契約

```python
Row      = (name, group|None, cols: dict[str,int])
Record   = (doc, cls, source_page, source_kind, total_col,
            printed_total, printed_totals|None, rows, _by|None)   # 逐欄 == 現行 facts/
Cell     = (key, doc, cls, records)
Anchor   = (doc, cls, amount, bs_page|None, pages, pdf_sha256, located_by)   # 新
Verdict  = (key, passed, checks, views, anchor)                    # verdict+audit 合併
Unit     = (period, bank, cls,                                     # ← R1:三元組
            provenance: "v3"|"v2", state: "ADOPTED"|"NOT_YET"|"BLOCKED"|"CONTRADICTION",
            reason, projections: {"data","wide","wide_cost"})
```

`Record` 逐欄等於今天的 `facts.REQUIRED_REC + OPTIONAL_REC` → **磁碟格式零變更,
36 格一格都不用遷移**,`facts.validate()` 可以直接當第二 oracle。

### 2.3 唯一入口

```bash
python3 -m core status
python3 -m core anchors [--verify]
python3 -m core ingest next|submit
python3 -m core verify
python3 -m core build [--write]
python3 -m core publish
```

`make_web.py` 與網站格式不動。

### 2.4 四道等價閘門 + 抄列重播

| 閘門 | 比什麼 | 判準 |
|---|---|---|
| **E1 錨值** | `anchors/*.json` vs 當場 `locate.locate()` | 逐項相同 |
| **E2 判定** | `core.reconcile` vs `results.build()` | verdict 逐格逐欄相同;`checks` 訊息**逐字相同** |
| **E3 分類** | `core.classify` vs `buckets.bucket()` | 75 名 × 20 group 全組合相同 |
| **E4 發布** | `core.publish` vs `build.py --diff` | 除 `_build` 外逐位元組相同 —— **但 R1 改了單位規則,所以 E4 改成:先證明「四元組模式」下逐位元組相同,再切到三元組並逐格解釋 31→24 的差異** |
| **E5 抄列** | `core.ingest` 走 `transcriber.replay` | 36/36 PASS、rows 逐列相同、level 相同;四條出口各一個合成案例 |

E2 的「訊息逐字相同」不是潔癖 —— 那些訊息是拒收的證據,也是 `/fill` skill 明令
agent 照抄的東西。訊息漂移 = 護欄行為改變。

### 2.5 階段

| 階段 | 做什麼 | 閘門 |
|---|---|---|
| **R** | 先寫 T-R1 / T-R2 / T-R3 / T-R4(此時紅在該紅的地方) | 四組測試存在且會失敗 |
| **C0** | `contracts` + `store` + `anchors/` 固化 + Ring 分層 | E1 綠 ∧ T-R3 綠 ∧ 九支測試綠 ∧ `facts/` 零變更 |
| **C1** | `reconcile`(包 `transcribe`+`wide`) | E2 綠 ∧ `verify` 全格 < 1 秒 |
| **C2** | `classify` 單一入口 + taxonomy 單一來源 | E3 綠 ∧ `test_rules`/`test_synonyms` 綠 ∧ 新增「SYN 每條要有背書」閘門 |
| **C3** | `ingest` + `route` + `state/` | E5 綠 ∧ 3 個新格實跑 ∧ 四條出口實跑 ∧ **T-R4 綠(擴頁白名單上線)** |
| **C4** | `publish` + `cli` + **`data` 改成同源投影**(R1 推論) | E4 綠 ∧ T-R1 綠 ∧ T-R2 綠 ∧ `test_build` 五命題移植且 < 60 秒 |
| **C5** | 依 §4 退場 | 每刪一檔重跑全部閘門 |

**C2 是 Phase A 唯一有真實行為風險的一步**(併三份編碼一定會改變某些輸出,除非證明沒有)。
閘門是全稱的:75 名 × 20 group 全組合。**過不了就不做 C2**,`classify.py` 退化成
純轉呼叫,分類法維持三份 —— 編排層照樣乾淨。這是 Phase A 唯一允許中止的階段。

### 2.6 ⚠️ C2 / C3 沒有解掉分類的根因

必須寫清楚,避免日後誤以為分類問題已經處理過:

- **C2 解的是「同一份分類法被編碼三次」**(格式問題),不是「分類未知會怎麼樣」(語意問題)。
- **C3 解的是「升級迴圈有兩份實作、失敗路由混住」**(編排問題)。
  C3 **會**帶進 R4 的擴頁白名單(那是使用者裁示的規則,不能等),
  但它照樣把 `check_buckets` 當成**存檔閘門** —— 分類不出來的格,raw facts 照樣被丟掉重抄。
  也就是說:**C3 之後分類不再驅動擴頁,但分類仍然阻止歸檔。** 兩個根因只解掉一半。
- 分類仍然只回一個 bucket 字串,沒有 occurrence、沒有 state、沒有 provenance。

這兩個根因由 Phase B 處理。**Phase A 結束時,系統仍然帶著它們,只是主幹乾淨了。**

---

## 3. Phase B —— 語意邊界修正

**前提:Phase A 穩定(C5 完成、四道閘門在 CI 上連續綠)。**

### 3.1 要修的兩個根因

| 根因 | 今天的形狀 | 代價(實測) |
|---|---|---|
| **B-I 分類未知阻止 raw facts 保存** | `fill.cmd_submit` → `verify` → `check_buckets` 不過 → RETRY/BLOCKED → **整格抄錄丟棄** | 國泰 202504 Trading:「基金受益憑證」擴到 8 頁仍卡,**白燒約 8 輪**;每一輪抄到的列全部丟掉 |
| **B-II classify 只回 bucket** | `buckets.bucket(row) -> str|None`。沒有 occurrence 身分、沒有狀態、沒有依據 | 兆豐 REIT 改名、玉山「股票及基金」改名,靠**人比對比較年度金額**才確認 —— 那個依據沒有任何地方記錄得下來 |

### 3.2 Decision 型別

```python
Occurrence = (cell_key, source_page, row_index)          # 唯一識別「某一列的某一次出現」
Reference  = (kind: "human"|"rule"|"synonym"|"prior_year"|"group", detail, at)
Decision   = (occurrence, name, group,                   # 原名照抄,來自 raw fact
              mapping: bucket|None,
              state: "CONFIRMED"|"PROVISIONAL"|"UNCLASSIFIED",
              references: [Reference], at, by)
```

#### 三個狀態的定義(使用者裁示,依「有沒有合理候選」切,不依「像不像對的」切)

| 狀態 | 定義 | 今天對應得到的東西 | 可發布 |
|---|---|---|---|
| **CONFIRMED** | 明確 taxonomy 命中,**或**人工確認。⚠️ **`buckets.SYN` 要先完成批准遷移並建立 reference,才有資格當 CONFIRMED 的來源**(使用者裁示) | 75 個相異列名今天全部直接命中 SYN,但**遷移完成前一律視為 PROVISIONAL** | ✅ |
| **PROVISIONAL** | 規則、案例或 agent **提得出合理候選** | `rules.propose()` 有值(如「基金受益憑證」→ 股票)、`synonyms.candidates()` 配到、agent 建議 | ❌ |
| **UNCLASSIFIED** | **提不出合理候選** | `propose()` 回 None 且無同義詞證據(如玉山兩列小計、兆豐 REIT 初次出現時) | ❌ |

三條推論,每條都要寫成測試:

- **正式發布只允許 CONFIRMED。** PROVISIONAL 與 UNCLASSIFIED 都不得上網站。
- **所有機器推論與 agent 輸出只能是 PROVISIONAL。** 狀態由**來源**決定,不由內容像不像決定。
  `decide()` 的回傳型別上就不該存在 CONFIRMED;只有 `ratify()` 能升級,而它只吃人工輸入。
- **SYN 命中不會自動變成 CONFIRMED。** `buckets.py` 的規矩是「不准手工塞,要
  `rules.propose()` / `synonyms` 背書 + git diff 審核」,所以**每一條 SYN 原則上都已經是
  一次人工確認的結果** —— 但「原則上」不等於「查得到證據」。
  使用者裁示:**必須先完成批准遷移、為每一條建立 reference,SYN 才有資格當 CONFIRMED 的來源。**
  在那之前(B1 完成前),SYN 命中一律是 PROVISIONAL。
  這也意味著 **G15 從「好習慣」升格成承重結構**:SYN 若能被機器偷偷塞進去,
  CONFIRMED 就沒有意義了。

**為什麼是 occurrence-level 而不是 name-level** —— 實測反例:
富邦 202304 Trading p38 同一份附註裡「其他」出現兩次(有價證券段 5,891,015、
衍生金融資產段 4,826,250),**名字一樣、桶不一樣**。今天靠 `group` 湊合過去了,
但決定本身沒有身分,也就無從記錄「這一次是憑什麼決定的」。

五條不變式,每條都要有測試:

| # | 不變式 | 測試形狀 |
|---|---|---|
| I1 | 機器推論與 agent 輸出**只能**是 PROVISIONAL。狀態由**來源**決定,不由內容決定 | `decide()` 的回傳永遠不是 CONFIRMED;只有 `ratify()` 能升級,且 `ratify()` 只吃人工輸入 |
| I2 | `mapping is None ⟺ state == UNCLASSIFIED` | 注入 `(mapping=None, state=CONFIRMED)` → 拒絕 |
| I3 | 每個 Decision 至少一條 reference;CONFIRMED 至少一條 `kind=="human"` | 注入無 reference 的 CONFIRMED → 拒絕 |
| I4 | UNCLASSIFIED **保留金額、參與對帳**,但**不得落進任何 wide 桶**,不得冒充 OTHER 或 null | 注入未知科目 → 金額出現在三段恆等式、不出現在七桶任一、該格不可發布 |
| I5 | 正式發布只允許全格 CONFIRMED | 把一格的任一 Decision 降成 PROVISIONAL → 該 unit 立刻不可發布 |

I4 有一半今天已經做對了:`wide.view()` 把認不得的列放進 `unknown`,
且 `View.ok` 在 `unknown` 非空時回 False —— **Phase B 是把它形式化,不是發明它**。
`GENERIC = {"其他", ...}` 那條要保留:表上**印著**「其他」的列合法對到 OTHER;
禁止的是把 **UNCLASSIFIED** 自動塌成 OTHER。兩件事必須分得開。

### 3.3 兩道閘門(B-I 的解法)

```
Gate 1 存檔閘門(Ring 0,ingest)
    來源:source_page 在候選頁集合內
    結構:facts.validate()
    算術:check_identity · check_col_totals · check_anchor · check_cross
    → 通過就寫進 facts/,**不管分不分得出桶**

Gate 2 發布閘門(Ring 1,publish)
    check_buckets · coarse · wide 三段恆等式 · 全格 Decision == CONFIRMED
    → 不過就不發布,但 raw facts 已經在 git 裡了
```

**G1 會不會因此失守?** 安全性質不會,自動回收會 —— 兩者必須分開講。

玉山 2021H1 OCI 那個案例(主附註兩列小計相加剛好 == 錨,前四道全綠而產出是廢的)
今天由 `check_buckets` 在**存檔閘門**擋下,並順手觸發擴頁找到 p24。Phase B 之後:

| 性質 | 變化 |
|---|---|
| raw facts 被存起來 | **新增**(來源、結構、算術都對,存起來是誠實的) |
| 那兩列 → UNCLASSIFIED → Gate 2 擋住,該格不可發布 | **保住**(G1 的安全目的達成) |
| 自動擴頁到 p24 找到明細 | **失去** —— R4 禁止分類驅動擴頁 |
| 進 review queue,由人選擇處置 | **新增**(補償出口,見 §1 R4) |

⚠️ **初版寫的機制(「提不出提案 → 可能是小計 → 擴頁」)已作廢。**
M3 證明那個推論是擲硬幣:提不出候選的名字裡,玉山那兩個是小計,
兆豐 REIT 與玉山「國外機構發行債券」是真科目。
`rules.propose()` 從此**只決定狀態(PROVISIONAL / UNCLASSIFIED),不決定路由**。

所以差別有兩個,一好一壞,都要寫進驗收:

- **好**:抄到的列不再被丟掉(玉山 5 格、國泰 202504 那種白燒 8 輪的情形都不再發生)。
- **壞**:玉山家族要靠人在 review queue 按下「這是小計,頁沒找全」才會擴頁。
  **這是使用者明確接受的取捨** —— 寧可讓人多按一次,也不要程式用擲硬幣的訊號自動燒預算。

覆寫保護:同一格重新提交(擴頁後的超集)覆寫前,舊版寫進
`facts/_superseded/{doc}__{cls}__{n}.json`。這樣「不得因分類未知而丟失」是字面成立的。

**統計口徑要跟著改**:`status` 的「已完成」要拆成 **已存檔** 與 **可發布** 兩個數字。
今天 36 格兩者相等,Phase B 之後會分岔 —— 分岔本身是這個修正的**產出**,不是退步。

### 3.4 起步:批准遷移是 CONFIRMED 的前提,不是事後補登

使用者裁示:**SYN 要先完成批准遷移並建立 reference,才能當 CONFIRMED 的來源。**
所以遷移不是可有可無的整理動作,而是**擋在 I5(只發布 CONFIRMED)之前的前置條件**:

```
B1 遷移未完成  →  SYN 命中 = PROVISIONAL  →  若此時就開 I5,可發布單位 = 0
B1 遷移完成    →  有 reference 的 SYN = CONFIRMED  →  可發布單位 = 24
```

**因此 B1 必須早於 I5 上線(B5),中間不得留下「I5 已開但遷移未完」的狀態。**
這條寫進 B 階段的順序約束,不是建議。

遷移內容(今天 facts 裡 75 個相異列名全部直接命中 SYN,實測零 unknown):

- 對 74 條 SYN 逐條跑 `git log -S`,找到引入它的 commit →
  reference = `{kind:"human", detail:<sha>, at:<commit date>}`。
- 找不到 commit 的 → 降為 **PROVISIONAL**,列成待批清單由人逐條看。
  **這一格就是 G15 的實測**:若真有名字是被機器偷偷塞進 SYN 的,這裡會把它揪出來。
- 閘門:遷移後可發布單位數 **== 24**(不變)。若掉了,逐條說明是哪個名字沒有人工來源
  —— **那是發現了一個真問題,不是遷移失敗。**

⚠️ **不准為了讓數字回到 24 而放寬 reference 的認定。** 找不到 commit 就是找不到,
該名字就停在 PROVISIONAL 等人看。這一條的價值全在它會不會誠實地掉下來。

### 3.5 Phase B 階段

| 階段 | 做什麼 | 閘門 |
|---|---|---|
| **B1** | `Decision` 型別 + 批准遷移(把今天的隱性決定顯性化,不改行為) | 可發布單位數不變(24)∧ I1–I3 注入測試綠 ∧ 74 條 SYN 逐條有 reference |
| **B2** | 拆兩道閘門 + `facts/_superseded/` | facts 格數**上升** ∧ 可發布單位數不變 ∧ **玉山 2021H1 OCI 存得進去且發不出去** |
| **B3** | UNCLASSIFIED 參與對帳但不冒充 | I4 注入測試綠 ∧ `status` 顯示「已存檔 / 可發布」兩個數字 |
| **B4** | review queue 三種處置 + 人工觸發擴頁 | 對玉山 5 格按 `(c)` → 擴到 p24 → 重抄後可發布 ∧ **retries 未因分類未知而增加** |
| **B5** | 人工確認流程 + taxonomy 升級 | `ratify` 一條 → 某格由不可發布轉可發布,且 git diff 可審 ∧ I5 綠 |

---

## 4. 既有函式:重用 vs 停用 vs 退場

### 4.1 直接包裝重用(**一行都不改,只 import**)

`bs_anchor.read` · `locate.locate`/`expand`/`CENSUS_BASELINE`/`census` · `resolve.download` ·
`transcribe` 的六道檢查 + `coarse`/`align`/`context_pages`/`NA_*` ·
`wide.View`/`pick`/`view`/`cell` · `buckets` 的 `norm`/`bucket`/`pending`/`is_adj`/`basis_of` + `SYN`/`GROUP_SYN` ·
`rules.propose`/`audit`/`KEYS` · `synonyms.candidates`/`classify`/`scan` · `holdout` ·
`facts.validate` · `config` 的資料常數 · `make_web.py` 整支。

**包裝 = `from transcribe import check_cross` 這種程度。** 不是抄過來改名,不是順手整理。

### 4.2 停止使用

`fill.cmd_*` · `fill.RULES` · `fill._taxonomy_gap` 的 monkeypatch 手法 ·
`pipeline.run/drive/Outcome` · `results.main()` 與 `results/` 落地 ·
`bridge_v3.apply/write/main` · `bridge_v3.cell_of/to_yi` 被 build.py import ·
`build.py` · `bridge_v2`/`batch_v2`/`extract_v2` · `config.LEGACY_*` 與 6 個死常數 ·
`work/current.json` · `更新網站.command`。

### 4.3 退場條件

| 檔案 | 條件(全部成立才刪) | 階段 |
|---|---|---|
| `results.py` | E2 在**連續兩次分類表變更**後仍等價 ∧ 零 import ∧ `results/` 已刪 | C1 |
| `pipeline.py` | E5 綠 ∧ 四條出口綠 ∧ `test_pipeline`/`test_drive` 已改指向 `core.ingest` ∧ `MAX_LEVEL`+`EXPAND_TRUTH` 實測記錄已搬 | C3 |
| `fill.py` | 同上 ∧ **`core ingest` 真的抄成功 ≥3 個新格**(非重播)∧ `.claude/skills/fill/SKILL.md` 已改寫 | C3 |
| `bridge_v3.py` | E4 綠 ∧ `cell_of`/`to_yi` 已在 `core.publish` 且各有單元測試 ∧ 零 import | C4 |
| `build.py` | E4 綠 ∧ T-R1/T-R2 綠 ∧ `test_build` 五命題移植且 < 60 秒 ∧ 五條鐵則在護欄清冊有對應測試 | C4 |
| `bridge_v2`/`batch_v2`/`extract_v2`/`extract_v2_results.json` | 快照 sha256 閘門綠(已綠)∧ `core.publish` 能單靠 `snapshots/` 回退。**不需要等 v3 覆蓋 100%** | C4 |
| `更新網站.command` | `core publish` 成功發布過一次 | C5 |
| `archive/` `legacy/` `scratchpad/` `phase0.py` `app.py` `fetch_test.py` `make_charts.py` `build_native.py` `*.bak_*` | 零 import ∧ 九支測試綠 | 隨時 |

**不退場**:`locate` `bs_anchor` `resolve` `transcribe` `wide` `buckets` `rules`
`synonyms` `holdout` `facts` `config`(瘦身後) `make_web` `snapshots/` `facts/`。

---

## 5. 護欄:怎麼確保不弄丟

### 5.1 三個機制

1. **機械搬移。** Phase A 的 C0/C1/C3/C4 唯一合法搬移方式是 `import`。
   不准抄程式碼、不准改名、不准順手整理。
   `transcribe.py` 是 god module 是真的,但**拆它不屬於這份計畫**(獨立一步,
   零行為改變單獨驗收)—— 綁在一起,等價閘門就分不出差異來自搬家還是拆分。
2. **護欄清冊 `docs/guardrails.md`(C0 就建)。** 每列四欄:護欄 / 實測案例 /
   證明它會失敗的測試 / 新核心誰擁有。
   **一個舊檔案要退場,它擁有的每一道護欄都必須在清冊裡有新主人,而且注入錯誤時是紅的。**
3. **錨值固化的專屬閘門**(見 5.3)。

### 5.2 首批清冊

| # | 護欄 | 實測案例 | Phase B 是否變形 |
|---|---|---|---|
| G1 | 第 5 道擋兩層附註 | 玉山 2021H1 OCI:前四道全綠但產出是廢的 | **是** —— 安全性質由存檔閘門改為發布閘門;**自動擴頁能力移除**,改由 review queue 人工觸發(§1 R4、§3.3) |
| G2 | `coarse()` 排除跨桶合併列 | 富邦 202404:六道全綠但每一桶都錯 | 否 |
| G3 | 三值檢查,`NA_*` 不畫綠燈 | 恆真閘門是頭號死因 | 否 |
| G4 | 缺欄不補 0(未揭露 ≠ 0) | 88 列缺欄;衍生無取得成本 | 否 |
| G5 | 合計欄印 `-` 記 0,其他欄不放 key | `facts.validate` total_col 檢查 | 否 |
| G6 | 驗不到的成本欄不採用 | 沒抄 `printed_totals` 的明細表 | 否 |
| G7 | 三段恆等式 7桶+衍生+評價調整==合計 | 兩者會計意義相反 | **是** —— UNCLASSIFIED 要進恆等式(I4) |
| G8 | `bond_mv` 只扣衍生 | 中信曾算出子集 > 全集 | 否 |
| G9 | v3 的 null 不得抹掉 v2 | 8 處衝突 | **是** —— 由逐欄改為 unit 級 + 三態(R2) |
| G10 | 保留集永不進發布 | holdout 3 格 | 否 |
| G11 | `bs_anchor` 截斷偵測寧可回 None | OCR 掉逗號 | 否 |
| G12 | `CENSUS_BASELINE` 定位普查基準 | 96 / 2 / 169 | 否 |
| G13 | `facts.validate` 未知欄位與型別 | 邊界驗證 | 否 |
| G14 | 分類表缺口短路,不白燒擴頁 | 國泰 202504:擴到 8 頁,白燒 8 輪 | **是** —— 由「模擬後短路」升級成 R4 的**白名單**:分類根本不在觸發清單上,短路變成不必要 |
| G15 | `SYN` 不准手工塞,要背書 | 今天靠人工儀式 | **是** —— C2 變 CI 閘門,B1 變 Decision reference |
| G16 | 錨讀不到 → 拒收不猜 | `pipeline.run` 第一個分支 | 否 |
| G17 | 一格只有數字或 null,不留舊值 | `bridge_v3` 裁示 | **是** —— 分層陳述(R2) |
| **G18** | **同一格三個投影不得混來源** | M1:21 處 data/wide 不一致 | 新增(R1) |
| **G19** | **發布過 v3 的 unit 不得倒退** | ratchet | 新增(R2) |
| **G20** | **Ring 1 不得碰 PDF / state / 時鐘** | T-R3 | 新增(R3) |
| **G21** | **分類狀態不得觸發擴頁,也不得消耗重試預算** | M3:`propose()=None` 裡玉山 2 個是小計、兆豐+玉山 2 個是真科目 | 新增(R4) |
| **G22** | **UNCLASSIFIED 不得冒充 OTHER / null** | 今天 `wide.view()` 的 `unknown` + `View.ok` 已做對一半 | 新增(I4) |

「Phase B 是否變形」那一欄是重點:**變形的護欄要重寫測試,不變形的一行都不准動。**
**變形的護欄一律要在 `docs/guardrails.md` 裡保留舊版本的描述與失效日期** ——
否則半年後沒有人記得「G1 曾經會自動擴頁」,而那正是最容易被當成 bug 修回去的東西。

### 5.3 錨值固化的三道守

把錨值從「每次重推」改成「記錄下來」,新增了一種以前不可能的錯:**錨過期**。

1. `anchors/{doc}.json` 存 `pdf_sha256`;PDF 換了 → 該檔作廢,**拒絕使用**(不是重算)。
2. `core anchors --verify` 重新推導全部並逐項比對 → **CI 閘門**,不是選配。
3. `check_anchor()` **照樣留著**。它今天「定義上必然成立」,錨改成快取之後
   變成一道**真的檢查** —— 印出合計對不上快取錨 = 快取錯了。
   這道護欄的價值在 C0 之後**上升**,絕不能因為「反正必然成立」而拿掉。

### 5.4 明確不做

- ❌ 不重寫 `locate`/`bs_anchor`/`expand`/六道檢查/`wide` 的算術。
- ❌ 不在 Phase A 拆 `transcribe.py`。
- ❌ 不改 `facts/` 磁碟格式、不改網站格式、不改 `make_web.py`。
- ❌ 不上資料庫。
- ❌ 不做自動抄列(API transcriber)—— 那是覆蓋率問題,與編排正交。
- ❌ 不在 C4 之前碰 `data.json`。
- ❌ **不在 Phase A 宣稱分類根因已解決**(§2.6)。
- ❌ **不修 M5 那個潛伏 bug**(見下)。

### 5.5 已知潛伏問題(記錄,本計畫不修)

`transcribe.check_cross(recs, bk=None)` 一跑就 `AttributeError`:
`_by_bucket()` 在 `bucket is None` 時把 `bad` 回成 list(`transcribe.py:337`),
而 `_merged()` 與呼叫端都當 dict 用(`transcribe.py:293`、`:269`)。

- **今天無害**:唯一的呼叫端 `verify()` 永遠傳 `buckets` 進去,這條路徑沒人走。
- **為什麼不順手修**:`transcribe.py` 在禁改清單裡;而且修它會動到第 3 道的行為,
  E2 就分不出差異來自搬家還是修 bug。
- **什麼時候修**:拆 `transcribe.py` 那一步(獨立於本計畫),或有人真的需要
  「無分類知識的跨表比對」時 —— 而 R4 已經裁定第 3 道不當擴頁訊號,所以不急。
