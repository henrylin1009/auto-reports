# v11:一條路線 —— 把 capital / pillar3 併進「抄列 → 核對 → 發布」

**一句話**:債券部位那條路線(抓 PDF → 抄列 → facts → 資料頁人工核對 → build →
發布檔)是對的,但**只有債券部位在走**。資本、損益、利息、第三支柱各自繞過去,
直接把數字寫進自己的 json 就上線了。這一份把它們併進同一條。

前置:`docs/plan_v9_不擋人.md`(已完成)、`docs/plan_v10_補四個洞.md`。

---

## 現況:四個來源,一個資料頁

```
┌─ A. 債券部位 ────────────────────────────────── data.json ─┐
│  resolve.py → pdf_cache/ → fill/fill_auto → facts/ + facts.db│
│    → 【資料頁】/api/cell · /api/row · /api/ratify            │ ← 只有這條
│    → build.py(六道檢查 + eligible)→ data.json              │
│                                       → 分析頁 + 模擬器     │
└──────────────────────────────────────────────────────────────┘

┌─ B. 資本/損益/利息 ─────────────────────────── capital.json ┐
│  capital_auto.py                                             │
│    ├─ 驗過的 → 直接寫 capital.json      ← 沒有任何人看過     │
│    └─ 驗不過 → review/capital_queue.jsonl(79 筆)           │
│                     ↑ 沒有任何程式讀這個檔                   │
│                                    → 模擬器 軸②整體 · 軸④全部│
└──────────────────────────────────────────────────────────────┘

┌─ C. 第三支柱 ──────────────────────────────── pillar3.json ─┐
│  scratchpad/extract_pillar3.py  ← 產生器在 scratchpad/       │
│    → pillar3.json(有六道對帳,但沒有頁面、不進 build)      │
│                                              → 模擬器 軸③   │
└──────────────────────────────────────────────────────────────┘

┌─ D. 估值/獲利 ─────────────────── phase0.json + pnl.json ───┐
│  產生器已進 archive/;檔案 7/14 與 7/16 之後沒動過           │
│                                        → 分析頁「更多」分頁 │
└──────────────────────────────────────────────────────────────┘
```

**D 不在這一份的範圍**,它是死資料,要嘛重生要嘛下架,那是另一個決定。

---

## 盤點(2026-08-13 實測)

### 存了多少 vs 真的在用多少

| 來源 | 存的紀錄 | 模擬器真的吃 | 現在卡在佇列 |
|---|---|---|---|
| `capital.equity` | 13 | **0 格** | 46 |
| `capital.capital` | 74 | **0 格**(軸③已改走 pillar3) | 2 |
| `capital.fair_value` | 38 | 24 格 | 15 |
| `capital.pnl` | 40 | 25 格 | 10 |
| `capital.interest` | 40 | 25 格 | 6 |
| `pillar3` | 100 + 50 筆 `_src` | 25 格 | 0 |
| `facts/`(A 路線) | 203 格 | — | 161 |

`equity` 與 `capital` 兩段**沒有任何消費端**(`sim/` grep 0 次;
`sim/state.py:174` 的 `state.capital()` 是死碼)。**這一份不把它們併進來** ——
把沒人讀的東西接上人工核對,是製造工作。

### 併軌之後真正要人動腦的筆數

佇列 79 筆裡:

```
equity      46 筆  → 不併,不看
fair_value  15 筆  → 其中 6 筆是「facts/ 沒有對應的 AC 可對帳」,
                     補完 2021–2023 的 AC 之後自己消失
pnl         10 筆  → 其中 6 筆是「還沒有同期 pnl 可對帳」,同上
interest     6 筆
capital      2 筆  → 不併
─────────────────
真正要判斷 ≈ 19 筆,加上 R1 讓靜默跳過浮出來的 ~14 筆
```

**併軌不會讓要驗的數字變多。** 那些數現在也在發布,只是沒有人看得到。

---

## §0 前置:先修那三個假數字(獨立,不屬於本計劃的任何階段)

**這一項跟併軌無關,可以今天就做,做完再開始 R0。** 但它是唯一一件
「不做就是在發布錯的東西」,所以列在最前面。

`sim/state.py:155` 的 `ac_hidden()` 從 `capital.json` 拿 AC 浮虧,分母卻用
`bonds(y, b, ("AC",))` —— 而 `bonds()` 是 `or 0` 加總,AC 逐桶整片 null 時
它安靜地回 0:

| 年 | 銀行 | 現在畫出來 | 修正後約 | 倍數 |
|---|---|---|---|---|
| 2022 | 中信 | **−28.07%** | −3.69% | 7.6× |
| 2022 | 國泰 | **−23.18%** | −6.23% | 3.7× |
| 2025 | 玉山 | **−3.55%** | −1.39% | 2.6× |

2025 玉山是最新一年,現在正在網站上。

**改法**:`has_basis()`(`sim/state.py:128`)這道防線當初就是為了擋這件事寫的,
只套在 OCI 沒套在 AC。`ac_hidden()` 開頭加 AC 版的 `has_basis` 檢查,
取不到就回 `None`(留白),**不要用 `capital.json` 的 `book` 當分母頂替** ——
那是「全帳」口徑(含貨幣市場),跟 OCI 那邊只有債券不是同一把尺。

**驗收(必須證明會失敗)**:把 `data.json` 某一格的 AC 逐桶塞回非 null,
該格的整體端必須重新算得出來;把另一格的 AC 改成整片 null,該格必須從有值
變留白。兩個方向都要動,只驗一邊會漏掉恆真。

**順帶**:`axes.flags()`(`sim/axes.py:192`)只認三種理由,「AC 逐桶不存在」
不在清單裡 —— 加第四種,否則下次還是只看得到四格。

---

## R0 單一清單來源(純重構,零行為改變)

**為什麼先做這個**:`("Trading", "OCI", "AC")` 這個清單,`config.py:37` 有一份
權威版本,然後被**逐字複製在 15 個地方**。「多一個 kind」本身是一行,
但它會踩到這 15 個地方。

這是本 repo 反覆長 bug 的同一個形狀(memory: `two-implementations-one-rule`),
只是這次是第五個、也是最大的一個實例。

### 現存的 15 份複製(生產碼)

```
config.py:37          CLASSES = ["Trading", "OCI", "AC"]     ← 權威
build.py:224          for cls in ("Trading", "OCI", "AC")
build.py:262          for cls in ("Trading", "OCI", "AC")
server.py:102         for cls in ("Trading", "OCI", "AC")
locate.py:24          CLASSES = ("Trading", "OCI", "AC")
fill_auto.py:40       CLASSES = ("Trading", "OCI", "AC")
bs_anchor.py:85       for k in ("Trading", "OCI", "AC")
make_web.py:50,64,65  for c in ("Trading","OCI","AC")   ×3
make_web.py:288       const CATS=["Trading","OCI","AC"]  ← Python 字串裡的 JS
v4/witness.py:32      CLASSES = ("Trading", "OCI", "AC")
v4/reader.py:35       CLASSES = ("Trading", "OCI", "AC")
sim/state.py:31       CLASSES = ("AC", "OCI", "Trading")   ← 順序不同
web/workbench.js:147  const CLS = ["AC", "OCI", "Trading"] ← 順序不同
web/v4.js:134         const CLS = ["Trading", "OCI", "AC"]
```

加測試 5 處:`test_v4_to_facts.py:91,182`、`test_report.py:51`、
`test_rulings.py:68`、`test_js.js:15`。

⚠️ **兩個順序不同的地方要先確認順序有沒有語意。** `sim/state.py:31` 與
`web/workbench.js:147` 是 `AC, OCI, Trading`。如果只是顯示順序,收斂時要保留
(拆成 `CLASSES` 與 `DISPLAY_ORDER` 兩個名字);如果是無意義的,直接統一。
**先查清楚再動** —— 把顯示順序當成資料順序偷偷改掉,畫面會變而沒有人知道為什麼。

### 做法

1. `config.py` 明確定義兩件事:`CLASSES`(資料維度)與 `CLASS_ORDER`(顯示順序)
2. 生產碼 15 處全部改讀 config
3. 前端兩處:由後端 `/api/overview` 帶下來,不在 JS 裡寫死
4. 測試 5 處**先不動** —— 它們寫死清單是刻意的(測試不該跟被測物共用常數)

### 驗收

- `python3 run_tests.py` 全綠
- `python3 app.py build --diff` 的輸出**與動手前逐字相同**

  ⚠️ **不是「輸出必須是空的」**(2026-08-13 實測踩到):`data.json` 目前相對
  `facts/` 是舊的,`--diff` 現在就會吐一大段,含「138 個單位由有數字變成 null」。
  所以零行為改變的證明是「diff 不變」,不是「diff 為空」。動手前先存一份基準:

  ```
  python3 app.py build --diff > /tmp/build_diff.before 2>&1
  ```

  改完再跑一次比對。**不要順手 `--write` 把 data.json 更新掉** —— 那會同時
  改變基準與被測物,這次重構就再也證明不了自己沒改壞。

  實務數字(2026-08-13 量的):這段輸出目前 **2308 行**,跑一次要**一分鐘以上**。
  用 `diff` 比檔案,不要用眼睛看。
- 再 grep 一次,生產碼裡 `"Trading", "OCI", "AC"` 的字面量只剩 config.py 一處

### 這一階段的意義不只是清理

**做起來痛不痛,就是要不要做 R2–R4 的信號。** 如果收斂 15 處就撞到一堆
隱藏耦合,那併軌的成本會遠高於估計,應該停在這裡重新評估。

---

## R1 pillar3:把「驗不到」跟「驗過了」分開

`scratchpad/extract_pillar3.py:61` 的六道對帳是**真的檢查**(拿抄到的分子分母
去對文件自己印的比率),100 筆全過。但它是這樣寫的:

```python
if d.get("own_funds") and abs(d["cet1"] + d.get("other_t1", 0) + ... ) > 5:
    f.append("自有資本加總不符")
```

欄位缺 → 整道跳過 → `_fails` 留空 → 看起來像通過。實測 **`other_t1` 缺 14/100 筆**,
那 14 筆的「自有資本加總」與「第一類比率」兩道是靜靜跳過的。

這正是 `build.py:133-146` 那段註解在講的「v4 說驗不到 = 通過,v3 說驗不到 = 擋」,
同一個 conflation 換到另一支檔案。

**改法**:`gates()` 回傳三態而不是一個 list —— `passed` / `failed` / `no_witness`。
不要把 `no_witness` 併進 `passed`。

**驗收(必須證明會失敗)**:挑一筆 `other_t1` 齊全的紀錄,把 `cet1` 改掉一塊錢
→ 「自有資本加總」必須報 failed;把 `own_funds` 刪掉 → 必須報 no_witness
**而不是 passed**。兩種結果要看得出差別。

⚠️ **這一步做完,pillar3 的「全過」會從 100/100 掉下來。** 那是修正不是回歸
(同 v6 那次「143 個發布單位變 null」)。

---

## R2 抽取器的出口改成 facts.db

**現在**:`capital_auto.py:355` 直接 `json.dump` 到 `capital.json`;
`extract_pillar3.py` 直接寫 `pillar3.json`。

**之後**:兩者都寫進 `facts.db` 的三張表,鍵為 `{doc}|{kind}`。

### 為什麼這一步比想像中小

兩邊的紀錄**本來就是 facts 的形狀**:

```
capital.interest.rows      → rows(name / amount)
capital.* 的 period/basis  → 已經有 basis_norm,跟 facts 的 doc 語意對得上
pillar3 的 50 筆 `_src`    → file / page / sha1 / rows / cols
```

`pillar3` 那 50 筆 `_src` 存的就是來源頁與原始 rows —— 它已經滿足
「每個數字都要能點回原始頁」這個資料頁的前提,只是沒有人接線。

### 要處理的形狀差異

| | facts(A 路線) | capital | pillar3 |
|---|---|---|---|
| 一格的鍵 | `{doc}\|{class}` | `{doc}\|{kind}\|{period}` | `{bank}\|{period}\|{basis}` |
| 期別 | 隱含在 doc 裡 | 一份 doc 兩個 period(當期+前期) | 期別就是鍵的一部分 |
| 每列 | name / cols / group | name / amount | 15 個具名欄位 |

**期別是最大的差異**:capital 一份年報同時印當期與前期,facts 的模型是
「一份 doc = 一格」。`yields.interest()` 已經處理過這件事(同一年出現在兩份年報,
數字相同 = 免費的跨份對帳,不同就拋錯),**那個邏輯要保留,不要在遷移時弄丟** ——
它是目前唯一在跑的跨份驗證。

### 驗收

- 遷移後 `capital.json` / `pillar3.json` 由 facts.db **匯出**產生(`app.py export`),
  內容與現在**逐字相同**
- `python3 -c "import sim.axes; sim.axes.payload()"` 的輸出與遷移前逐格相同
- 這兩件事就是「只換儲存、不換數字」的證明

---

## R3 後端:格宇宙 + `/api/cell` 按 kind 分派

格數 **203 → 約 340**(+67%)。

### 要改的三個地方

1. **`core/webdata.py`**(1269 行)—— 格宇宙現在寫死三個 class,改成由
   註冊表決定有哪些 kind
2. **`/api/cell`** —— 回傳的 `checks` / `tally` / `anchor` 要按 kind 組不同內容
3. **`server.py:102`** —— R0 已經處理掉這一處的寫死

### `/api/cell` 各 kind 要回什麼

檢查邏輯**全部已經寫好**,這一步是把回傳值攤平成同一個形狀,不是重算:

```
kind          既有的檢查                          位置
─────────────────────────────────────────────────────────────
Trading/OCI/AC  六道 + 三段恆等式(wide.view)      checks.py / wide.py
fair_value      對 facts/ 的 AC 合計              capital.py:419
pnl             四欄自洽                          capital.py:468
interest        rows 加總 == 小計 + 跨份對帳       capital.py:501
capital(不併)  —                                 capital.py:320
equity(不併)   —                                 capital.py:563
pillar3         六道比率對帳                      extract_pillar3.py:61 → R1 三態版
```

統一的回傳形狀:

```json
{ "rows": [...], "source_page": 149, "printed_total": 773147312,
  "checks": { "state": "pass|fail|no_witness", "items": [...] },
  "summary": { /* 每個 kind 自己的摘要,前端照著畫 */ } }
```

`summary` 刻意不強求統一結構 —— 三段恆等式和六道比率對帳本來就不是同一種東西,
硬塞進同一個 schema 只會讓兩邊都變難懂。

---

## R4 前端:核對頁的三個變體

**這一段我先前估錯過,現在是看過程式碼之後的版本。**

資料頁**深度綁著分桶模型**,不是照用:

```js
web/workbench.js:833   <span class="tag">錨 ${num(cell.anchor)}</span>
web/workbench.js:1016  <span class="bk">${r.bucket ? ... : '選桶 ▾'}</span>
web/workbench.js:977   tallyView()  已歸桶/衍生·評價調整/未歸桶/紙上印的合計/差額
web/workbench.js:945   pickBucket() → 寫進 buckets.SYN
```

這四樣 capital 與 pillar3 一樣都沒有:

| | 債券部位 | capital.fair_value | pillar3 |
|---|---|---|---|
| 錨值 | BS 資產負債表錨 | 沒有錨 | 沒有錨 |
| 每列的桶 | 七桶 + 選桶下拉 | 只有 book/fair 兩個數 | 15 個具名欄位 |
| 驗收摘要 | 三段恆等式 | 對 facts/ 的 AC 合計 | 六道比率對帳 |
| 人工動作 | 歸桶、改列、重抄 | 改數、重抄 | 改數、重抄 |

### 可原樣重用(不動)

```
左邊 PDF 檢視器 + 翻頁 + 全文搜尋              ~150 行
文件/格清單、狀態色、篩選                       ~120 行
rows 表的 名稱/數值/✎編輯/×刪除/點列跳來源頁    ~80 行
重抄按鈕、模型選單、指定頁碼、撤銷人工裁示       ~90 行
發布狀態列 publishLine()                        ~15 行
```

### 要新寫(每個 kind 家族各一份)

```
標題列的對帳 chip(錨 → 各自對到什麼)          ~5 行 × 3
驗收摘要區(tallyView 的位置)                  ~25 行 × 3
rows 表最右欄(選桶 → 該 kind 的欄位語意)       ~10 行 × 3
```

**約 120 行新前端。** 殼不動,只是 `clsDone()` 裡三個位置改成按 kind 查表取
render 函式。

### 驗收

- 現有三個 class 的畫面**逐像素不變**(這是「只加不改」的證明)
- 每個新 kind 至少走通一次完整動線:看到問題 → 點回原始頁 → 改數 → 存檔 → 檢查轉綠
- **`review/capital_queue.jsonl` 那 79 筆要在畫面上看得到**(不併的 48 筆也要看得到,
  標成「無消費端」而不是藏起來)—— 寫進去卻沒有出口正是這一份要解決的問題本身

---

## R5 build 吐發布檔,sim 改讀發布檔

1. `build.py` 的 `BASES` 從 `("wide", "wide_cost")` 擴成也吐 capital / pillar3 的表
2. `sim/state.py` 改讀發布檔,**刪掉直接 `json.load("capital.json")` /
   `json.load("pillar3.json")` 的路徑**
3. `sim/state.py:174` 的 `state.capital()` 死碼一併刪掉

### ⚠️ 做完模擬器的滿格數會掉

現在 capital / pillar3 是「抽到什麼算什麼」,套上 `eligible()` 之後驗不過的
會誠實變 null:

```
軸③ 槓桿  現在 25/25/25  →  R1 之後那 14 筆 other_t1 缺的會浮出來
軸② 軸④   現在的假數字(§0 那三格)已經先修掉了
```

**這是修正不是回歸。** 先寫在這裡,免得做完看到數字掉了以為做壞了。

### 驗收

- `payload()` 的每一格,值要嘛跟 R2 之前相同,要嘛從有值變 null **且有 flag 說明理由**
- 沒有第三種情況(值變了但不是變 null)—— 出現第三種就是遷移弄錯了

---

## 平行軌:補抄 2021–2023(不依賴上面任何一階段)

跟併軌無關,可以隨時做。這是模擬器留白的**主因**:

```
data.json wide AC 逐桶   14/25   缺 2021×4 · 2022×5 · 2023富邦 · 2025玉山
data.json cost OCI 逐桶  18/25
data.json wide OCI 逐桶  20/25
data.json wide Trading   17/25
```

根因:`facts/` 的 202104 / 202204 只抄了**附註**那一張,明細表沒抄。而 AC 附註
沒有評價調整列 → `buckets.basis_of()` 判「成本」→ `wide.pick()` 的帳面路徑
整條走不通 → 整格 null。

明細表在 PDF 裡而且已經在手上,例如 `202204_富邦_個體.pdf` p149「明細表五」,
帳面金額欄合計 **773,147,312**,與 `capital.json` 的 `book` 逐字相同。

順帶兩個一字之差的事故:
- 玉山 2022 AC 帳面算得出七桶(397,744,237),卡在「國外定期存單（註二）」
  3 億不在 `buckets.SYN` → `View.ok=False` → 整格 null
- 兆豐 2021/2022 的 302,258 仟元:附註印「其他有價證券」→ 其他桶,
  明細表印「受益憑證」→ 股票桶,同一份文件同一筆錢兩個桶
  (`buckets.py:192` 自己記了這件事,標註「刻意不處理」)。
  影響量過:0.08 個百分點。乾淨的出路是把「其他有價證券」收進 `GENERIC`、
  靠 `group`(兆豐附註印的是「權益工具」)判桶 —— 那是文件自己的段落標籤,
  不是打版

### 真的找不到的:富邦 2025 的 OCI 利息(1 格)

`202504_富邦_個體.pdf` p66 附註三三只印四列,OCI 利息被併進「其他 9,013,522」,
而「其他」裡還混著非證券利息,拆不開。明細表目錄(p147)「利息收入明細表」
直接指回附註三三;p206 那張有 OCI 那列的是**證券部門**,不是全行。

影響量過:分子分母同步縮到只有 AC,誤差 **0.0–0.2pt**。維持「僅AC」是對的處理,
不要為這一格做事。

---

## 順序與停損點

```
§0  修三個假數字        獨立,今天就能做      ← 唯一「不做就是錯的」
R0  單一清單來源        純重構,測試能證明    ← 停損點:痛就停下來重估
R1  pillar3 三態        小,獨立
R2  抽取器 → facts.db   中,有逐字相同的驗收
R3  後端格宇宙 + API    最大一塊(webdata.py 1269 行)
R4  前端三個變體        ~120 行
R5  build + sim 改線    小,但會讓滿格數掉

平行軌:補抄 2021–2023   不依賴上面任何一階段
```

**R0 是停損點。** 如果收斂 15 處寫死清單就撞到一堆隱藏耦合,那 R3 的成本會遠
高於估計 —— 那時候應該停下來,先把耦合清乾淨,而不是硬推併軌。

---

## 這一份刻意不做的事

- **不併 `equity` 與 `capital` 兩段** —— 沒有消費端。要併的前提是先有人要用
- **不碰 D 路線**(`phase0.json` / `pnl.json`)—— 那是「重生還是下架」的決定,
  不是併軌
- **不新寫任何檢查公式** —— 五個 `verify_*` 加 `gates()` 都已經在跑,
  這一份只改它們的出口
- **不為富邦 2025 的 OCI 利息想辦法** —— 找不到,而且影響 0.2pt 以內
