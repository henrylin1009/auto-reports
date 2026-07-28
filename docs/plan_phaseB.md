# Phase B 施工計畫 —— 語意邊界修正

> 制定 2026-07-28,同日依使用者裁示修訂(v2)。
> 前提:Phase A 的 R / C0 / C1 已完成(`core/units.py` `core/expand_policy.py`
> `core/contracts.py` `core/store.py` `core/reconcile.py` 存在且等價閘門綠)。
>
> 目標**不是整理檔案**,是把這條語意流程修對:
>
> ```
> PDF / 表格
>   → raw facts          來源、結構、算術正確就保存(不因分類未知而丟棄)
>   → classification decisions   occurrence-level、有狀態、有依據
>   → reconcile / validate
>   → build / publish    只發布 CONFIRMED
> ```
>
> 規格衝突時:**本文件 > `plan_clean_core.md` §3**。本文件依實測與使用者裁示
> 修正了 §3 的數處落差,逐條列在 §7。

---

## 0. 硬性約束(先讀)

### 0.1 沿用 Phase A 的禁令

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` | 已驗證的底層能力。唯一合法重用方式是 `import`。**B1 讀 `buckets.SYN` 當輸入,但不改它** |
| 跑 `build.py --write` / `bridge_v3.py --write` / 任何 `--write` | 會動到已發布的 `data.json` |
| **測試寫進真實 `facts/`** | B2 的 fixture 會寫檔 —— 一律寫到 tmp 目錄,`facts/` 在本計畫全程唯讀(見 §4.6) |
| 呼叫任何模型 API | 抄列由外部 agent 做,程式不呼叫 |
| 為了讓測試變綠而放寬判準 | 測試紅了要回報 |
| 「順手」重構、改名 | 等價閘門會分不出差異來自搬家還是整理 |

### 0.2 Phase B 專屬的三條

1. **`facts/` 是原始層,分類永遠不得改寫它。** Decision 寫在別的檔,靠
   occurrence 指回去。任何「把桶寫回 facts」的設計一律拒絕。
2. **CONFIRMED 只能由 `ratify()` 這一個動作產生**(§2.5)。機器推論一律
   到 PROVISIONAL 為止。
3. **不准為了讓可發布單位數回到 25 而放寬 reference 的認定。**
   數字誠實地掉下來,是這一步的**產出**,不是失敗。

---

## 1. 實測基準(2026-07-28 新量,不要重新推導)

### M-B1 SYN 的 reference 現況 —— **「有 commit」是恆真閘門**

```
SYN 74 條 / GROUP_SYN 5 條 / GENERIC 4 條 / PENDING 0 條

天真判準「git log -S 找得到引入 commit」  → 74/74 通過   ← 恆真閘門,不能用
```

往下拆才看得到真相:

```
引入這 74 條的相異 commit:12 個
    32 條  a8b43d80  feat(v3-R3): 第 3 道改「對齊欄位再比」…
    10 條  1f31bc33  feat(v3-R4f): 抄列 17 → 19 格…
     7 條  b40d8770  feat(v3-R4d): 抄列 11 → 14 格,AC 五家補齊
     6 條  42586ad5  feat(v3-R4e): 抄列 14 → 17 格…
     5 條  5995bf5b  feat(v3-R4b): 抄列 6 → 10 格…
     4 條  cfce33c5 / 4 條 18618437 / 2 條 4db7f6be / 1 條 ×4

來自「一次塞 ≥5 條」的批量 commit:60/74
    → 訊息是**抄列進度**,不是逐條分類裁示依據
逐條人工裁示的 commit 只有 3 個:
    3d7552e3  decide(v3): 國外機構發行債券 → 公債
    166934fe  feat(v4-T4): 兆豐 REIT 裁示為資產基礎
    d6ab905d  fix(v4-T3): …收錄基金受益憑證
```

原始碼註解才是真證據,但覆蓋不全:

```
34/74  緊鄰有註解區塊(可萃取 reference)
40/74  完全裸露(多數是最早的種子表)
可辨識種類:rule 17 / synonym 11 / arithmetic 7 / human 2
```

### M-B2 規則可獨立重現的比例 —— **63/74,零衝突**

```
rules.propose(norm(key)) 與 SYN 的桶比對:
    一致    63/74    ← 可給「可機械重驗」的 rule 證據
    提不出  11/74    ← 需要其他證據
    給出不同的桶  0/74   ← **零衝突。SYN 沒有一條與 BUCKET_RULES 矛盾**
```

`rules.propose()` 提不出的 11 條(B1.5 逐條批准的核心清單):

```
政府債券 → 公債            貨幣交換 → 衍生         外匯換匯合約 → 衍生
不動產投資信託受益證券 → 資產基礎   (166934fe 有使用者裁示)
國外機構發行債券 → 公債            (3d7552e3 有使用者裁示)
CMO → 資產基礎   RMBS → 資產基礎    (註解:富邦明細表 CMO+RMBS 相加 = 附註)
定存單 → 可轉讓定存單  定期存單-可轉讓 → 可轉讓定存單  (註解:兆豐一列 = 明細表兩列)
換匯 → 衍生      商品交換 → 衍生     (註解:中信明細表八列相加 = 附註)
```

### M-B3 identity 的實測(item 3 的依據)

```
36 格 / 65 record / 583 列 / 75 個相異列名
(cell_key, source_page, row_index)              583/583 唯一   ← **僅現況樣本**
同一格同一頁有多份 record                          0 格
(source_kind, total_col, printed_total) 格內撞號    0 格
  再加 printed_totals + 列數                      0 格
record 內 (norm名, group, 合計欄金額) 重複          0 筆
```

→ 兩組 fingerprint 在今天的 583 列上都夠用,**但都只是樣本結果**(§2.2)。

### M-B4 name-level 不夠用的實證

```
正規化後同一個名字對到多個桶:2 個
    其他      → {其他, 衍生}
    其他(註)   → {其他, 衍生}
```

靠 `group` + `GROUP_SYN` 分開(富邦 202304 Trading p38:有價證券段 5,891,015 /
衍生金融資產段 4,826,250)。→ **決定的身分必須是 occurrence,不是 name。**

### M-B5 B2 具名 fixture 的現況 —— **多數已在 facts 裡,不能拿現況當斷言**

```
202102_5847_AI3|OCI       已在 facts  level=None   ← 早期遷移,無 _by
202102_5847_AI2|OCI       **不在 facts**(從未抄過)
202302_5847_AI3|OCI       **不在 facts**
202402_5847_AI3|OCI       **不在 facts**
202502_5847_AI3|OCI       **不在 facts**
202504_5835_AI3|Trading   已在 facts  level=[2,2]  ← 白燒 8 輪後、SYN 補上才過
holdout(永不進發布):202304_5847_AI3|Trading · 202502_5835_AI3|OCI · 202502_5843_AI3|OCI
```

**這直接推翻「facts 格數上升」當閘門的寫法**:兩個主角今天都已經在 facts 裡,
斷言「它在 facts 裡」恆真;另外 4 格從未抄過,B2 也變不出來(要等 C3 的 ingest
真的跑)。正確的 fixture 形狀見 §4.5。

### M-B6 今天的 routing(`fill.cmd_submit`)

```
PASS     verify 全過 → 寫 facts/
BLOCKED  _taxonomy_gap() 模擬收錄後會過 → 寫 work/blocked/ + 提案,不擴頁
RETRY    其餘失敗 → level+1、擴頁、retries+1
REJECT   擴到 MAX_LEVEL(2)仍不過 → work/rejected/
```

`_taxonomy_gap()` 已做對一半(分類缺口不擴頁),但兩個限制 B2 要解:
`rules.propose()` 提不出來時它回 `None` → **交回給擴張**(正是 R4 禁止的路徑,
玉山 5 格落在這裡);且不論走哪個出口,**抄到的 rows 都沒進 `facts/`**。

---

## 2. 資料模型與儲存邊界

### 2.1 目錄

```
facts/{doc}.json                原始事實。**分類永不改寫**。格式零變更
facts/_superseded/{doc}__{cls}__{n}.json   被覆寫的舊版(B2)
taxonomy/rules.json             可重用規則 + reference + 狀態(B1)
taxonomy/derivations.json       已批准的**推導規則**(B1.5,見 §3.3)
decisions/{doc}.json            occurrence-level 決定(B0 定型別、B2 開始寫)
review/queue.jsonl              待處置佇列(B4)
out/                            所有產物,不回讀
```

`facts/` `taxonomy/` 是輸入;`decisions/` 是 Ring 1 產物但**要進 git**
(它是審核對象);`out/` 只准寫。

### 2.2 Occurrence —— locator 與 identity 分開

> **使用者裁示(item 3):`(cell_key, source_page, row_index)` 只能視為
> 現況樣本唯一,不可作為未來資料契約。**

實測(M-B3)它在 583 列上確實唯一,但那是**樣本性質**,不是保證:
`source_page` 會因擴頁重抄而變,`row_index` 會因多抄一列而整排位移。
所以身分拆成三層,**契約是後兩層,第一層只給人看**:

```python
# ① locator —— 人類可讀的定位。**不是 key,不得用來比對或綁定**
Locator = (cell_key, source_page, row_index)

# ② record identity —— 記錄層的穩定身分
RecordIdentity = (
    cell_key,           # "202404_5843_AI3|OCI" → 拆得出 bank/period/doc/class
    record_fp,          # sha256 of (source_kind, total_col, printed_total,
                        #            printed_totals)   ← **不含 source_page、不含 rows**
)

# ③ occurrence identity —— 決定層的穩定身分
Occurrence = (
    record_identity,    # 上面那個
    scope,              # "row" | "column" | "record"
    ordinal,            # row 的 row_index / column 的欄名 / record 的 None
                        #   ← ordinal 只在同一次快照內有意義,重綁時**不看它**
    row_fp,             # sha256 of (norm(name), group, cols[total_col])
                        #   scope != "row" 時為 None
)
```

**為什麼 `record_fp` 不含 `source_page`**:擴頁重抄後同一份 record 的頁碼會變,
含進去等於每次重抄都變成新 record,舊決定全部孤兒化。
**為什麼不含 `rows`**:多抄到一列是「同一份 record 的更完整版本」,不是另一份。

**重綁協定(重抄後必跑)**:
1. 用 `record_fp` 找到對應的舊 record;找不到 → 全部視為新 occurrence。
2. 在該 record 內用 `row_fp` 綁定;綁上的沿用舊 Decision 的 mapping 與 state。
3. 綁不上的舊 occurrence → 標 `superseded`,**不刪**。
4. 綁不上的新 occurrence → 建新 Decision,state 由 `decide()` 算。
5. **絕不用 `ordinal` 硬對。** 那會把「第 3 列的決定」套到重抄後完全不同的一列。

⚠️ **實測是樣本,不是保證(要寫進程式碼註解)**:今天 record 內 `row_fp`
零重複(M-B3),但兩列同名同段同額在原理上可能發生。`decisions` 寫入時要
**偵測 `row_fp` 碰撞並 raise**,不要靜靜覆蓋 —— 碰撞時加 `ordinal` 當
disambiguator 是可以的,但那要在碰撞真的出現時才做,且要留下紀錄。

`cell_key` 已帶得出 bank / period / doc / class(`bridge_v3.cell_of()` 就在做
這件事),**不要再另存一份**,那會出現兩個真相。

### 2.3 Taxonomy rule 與 Decision

**可重用的規則**與**某一次表格的決定**分開存,否則改一條規則就得重寫 583 筆
決定,而且看不出哪些決定是因為規則變了才變的。

```python
Reference = (
    kind,      # "human" | "rule" | "synonym" | "arithmetic" | "prior_year" | "group"
    detail,    # 人:ratify 記錄 id;規則:命中的關鍵字;同義詞:配對金額與對造名;
               # 算術:那條等式
    at,
    recheck,   # str|None:可機械重跑的驗算式(見下)
)

TaxonomyRule = (
    rule_id,            # "tax:政府公債" —— 正規化後的名字或段落名
    scope,              # "name" | "group" | "generic" | "column"
    mapping,            # bucket | None(generic 規則不帶桶)
    state,              # CONFIRMED | PROVISIONAL
    references: [Reference],     # CONFIRMED 必須有 ≥1 kind=="human"(I3b)
    derivation_id,      # str|None:由哪條已批准的推導規則背書(§3.3)
    approved_by, approved_at,    # ratify 記錄;PROVISIONAL 時為 None
)

Decision = (                       # occurrence-level
    occurrence,                    # §2.2 的三層身分
    locator,                       # 人類可讀,**不參與比對**
    name, group,                   # 原名照抄,來自 raw fact,**不正規化**
    mapping,                       # bucket | None
    state,                         # CONFIRMED | PROVISIONAL | UNCLASSIFIED
    taxonomy_ref,                  # str|None:引用的 rule_id + taxonomy 版本雜湊
    references: [Reference],       # 這一次決定自己的證據(可為空,若靠 taxonomy_ref)
    at, by,
)
```

**`recheck` 是本計畫加的**(`plan_clean_core.md` §3.2 沒有)。理由:
`kind="rule"` 的 reference 若只存關鍵字字串,`BUCKET_RULES` 改了它不會叫。
存下可重跑的驗算式(如 `rules.propose("金融債券") == "金融債"`),CI 就能對
**每一條** reference 重驗 —— 這是把 G15 從「好習慣」變成承重結構的實際做法。
**recheck 失敗的 CONFIRMED rule 必須自動掉回 PROVISIONAL 並大聲報錯。**

### 2.4 三個狀態

| 狀態 | 定義 | 可發布 |
|---|---|---|
| `CONFIRMED` | occurrence:引用了一條**已批准**的 CONFIRMED taxonomy rule<br>rule:經 `ratify()` 批准,有 human reference | ✅ |
| `PROVISIONAL` | 提得出合理候選,但未經批准(規則 / 同義詞 / 算術 / agent) | ❌ |
| `UNCLASSIFIED` | 提不出合理候選 | ❌ |

### 2.5 `ratify` 與 `decide` 的分工(**使用者裁示 item 1**)

這是 Phase B 的核心分界,寫成兩句話:

```
ratify()  唯一能**建立或升級 CONFIRMED taxonomy rule** 的動作。只吃人工輸入。
          它寫的是 taxonomy/,不是 decisions/。

decide()  **不得憑機器推論產生 CONFIRMED**,
          但**可以引用一條已 ratify 的 CONFIRMED taxonomy rule,
          產生 CONFIRMED 的 occurrence decision。**
```

`decide()` 的狀態表(唯一的一張,不准另寫分支):

| `decide()` 遇到 | occurrence state | 依據 |
|---|---|---|
| 命中一條 **CONFIRMED** taxonomy rule | **CONFIRMED** | `taxonomy_ref` 指向該 rule |
| 命中一條 **PROVISIONAL** taxonomy rule | PROVISIONAL | 同上 |
| taxonomy 沒有,但 `rules.propose()` / `synonyms` / 算術提得出候選 | PROVISIONAL | 自帶 reference |
| 提不出候選 | UNCLASSIFIED | mapping = None |

→ **`decide()` 沒有任何一條路徑可以自己造出 CONFIRMED。** 它只能「轉述」
一條已經被人批准過的 rule。這句話要寫進 `decide()` 的 docstring。

### 2.6 五條不變式(每條都要有注入測試)

| # | 不變式 | 注入什麼 |
|---|---|---|
| **I1** | `decide()` 產生的 CONFIRMED **必須且只能**來自引用一條已批准的 CONFIRMED taxonomy rule;機器推論(rule/synonym/arithmetic/agent)一律只能到 PROVISIONAL | 讓 `decide()` 在無 `taxonomy_ref` 時回 CONFIRMED → 必須紅 |
| **I2** | `mapping is None ⟺ state == UNCLASSIFIED` | 造 `(mapping=None, state=CONFIRMED)` → 拒絕 |
| **I3a** | **CONFIRMED occurrence 必須引用一條已批准的 taxonomy rule**(`taxonomy_ref` 非空且該 rule.state == CONFIRMED)。**不要求每筆 occurrence 自帶 human reference** | 造 CONFIRMED occurrence 引用 PROVISIONAL rule → 拒絕;造 CONFIRMED occurrence 無 `taxonomy_ref` → 拒絕 |
| **I3b** | **CONFIRMED taxonomy rule 必須有 ≥1 條 `kind=="human"` reference**(來自 `ratify()`),human 證據**存在 rule 上** | 造無 human reference 的 CONFIRMED rule → 拒絕 |
| **I4** | UNCLASSIFIED **保留金額、參與三段恆等式**,但不得落進任何 wide 桶,不得冒充 OTHER 或 null | 造未知科目 → 金額進恆等式、不進七桶、該格不可發布 |
| **I5** | 正式發布只允許全格 CONFIRMED | 把一格任一 Decision 降 PROVISIONAL → 該 unit 立刻不可發布 |

> **I3 的拆分是使用者裁示(item 2)。** 原版要求每一筆 CONFIRMED 都自帶
> human reference,那會讓 583 筆 occurrence 各複製一份人工背書 —— 既冗餘,
> 又讓「人到底簽了什麼」散在 583 個地方查不動。改成:**人簽在 rule 上,
> occurrence 引用 rule。** 稽核時看 taxonomy 那一份就夠。

⚠️ I4 有一半今天已做對(`wide.view()` 的 `unknown` + `View.ok`)。
**Phase B 是把它形式化,不是發明它。** `GENERIC = {"其他", …}` 要保留:
表上**印著**「其他」的列合法對到 OTHER;禁止的是把 UNCLASSIFIED 自動塌成 OTHER。

---

## 3. B1 —— SYN 批准遷移(機械部分)

**目標:把今天的隱性決定顯性化,不改行為。B1 不產生任何 CONFIRMED。**

### 3.1 逐條建立 reference

對 74 條 SYN + 5 條 GROUP_SYN + 4 條 GENERIC,依序試四種證據,
**取得到的全部收下**(一條可有多個 reference):

| 證據 | 怎麼取得 | 可重驗? | B1 給的狀態 |
|---|---|---|---|
| `rule` | `rules.propose(norm(key))` 的桶 == SYN 的桶 | ✅ | PROVISIONAL |
| `synonym` | 對 `facts/` 跑 `synonyms.candidates()`,同金額配到已知桶的對造 | ✅ | PROVISIONAL |
| `arithmetic` | 原始碼註解記載的等式(CMO+RMBS = 附註那類),**逐條抄成可重跑的斷言** | ✅ | PROVISIONAL |
| `human` | `git log -S` 找到的 commit,**且該 commit 是逐條裁示** | ❌ | 仍是 PROVISIONAL,**只是把證據記下來** |

**⚠️ B1 全部產出 PROVISIONAL。** 即使找到看起來像人工裁示的 commit,
B1 也**不得**自行升級成 CONFIRMED —— 升級只能經 `ratify()`(§0.2 第 2 條)。
B1 對 `human` 證據做的事,是把它整理進批准工單讓人**確認**。

**逐條裁示 commit 的判準**(給工單標註用,不是自動升級的授權):

- commit 訊息或 diff 註解**指名了這個名字**與**它的依據**;且
- 該 commit 在 `buckets.py` 動到的 SYN 條目數 ≤ 2,或訊息是
  `decide(...)` / 「人審決定」/「使用者裁示」形式。

**批量抄列 commit(一次塞 ≥5 條、訊息是抄列進度)一律不標 human。**
實測 60/74 落在這一類(M-B1);把它們當 human 就是恆真閘門。

### 3.2 預期結果(必須誠實)

```
B1 跑完:CONFIRMED 0 條(依定義)
        PROVISIONAL ~74 條(63 有 rule 證據 + 若干 synonym/arithmetic/human 待確認)
        UNCLASSIFIED 0 ~ 少數(三種可重驗證據都取不到的)
```

→ 此時若開 I5,可發布單位 = 0。這正是 §3.4 那句「B1 遷移未完成 →
可發布單位 = 0」的實際樣子,**不是 bug**。

### 3.3 批准工單與「推導規則」(**使用者裁示 item 5,2026-07-28 已確認**)

> **裁示原文**:B1.5 由人批准一個**具體、版本化、可重跑**的推導規則
> (derivation),**不是逐條簽 63 個名稱**。批准必須綁定 derivation id、
> `BUCKET_RULES` revision hash、適用 rule ids、批准人與時間;
> **recheck 失效或依據 revision 改變時,相關 rule 自動降回 PROVISIONAL。**

引入第四個型別:

```python
Derivation = (
    derivation_id,           # "deriv:BUCKET_RULES-keyword-v1"
    description,             # 人看得懂的一句話
    predicate,               # 可重跑的判定:rules.propose(norm(name)) == mapping
                             #             且 rules.audit(BUCKET_RULES) 無夾帶
    bucket_rules_revision,   # sha256(config.BUCKET_RULES) —— **批准當下的依據版本**
    applies_to: [rule_id],   # 這次批准涵蓋的 rule ids,**逐一列出,不准用萬用字元**
    approved_by, approved_at,
    references,              # ≥1 kind=="human" —— 人批准的是**這條推導**
)
```

**自動降級(硬性,B0 就要實作成純函數)**:

```
對每一條 state==CONFIRMED 且 derivation_id 非空的 rule,任一條成立就降回 PROVISIONAL:
  ① 該 Derivation 的 bucket_rules_revision != 現在的 sha256(config.BUCKET_RULES)
  ② 該 rule 自己的 recheck 跑起來不成立
  ③ 該 rule 的 rule_id 不在 Derivation.applies_to 裡
降級要**大聲報錯**並列出是哪幾條、因為哪一款,不准靜靜降級。
```

① 是這次裁示新增的:`BUCKET_RULES` 一改,整批批准的依據就變了,
**不是逐條 recheck 過了就算數** —— 人當初看的是那一版散文,版本換了就要重看。

一條 taxonomy rule 成為 CONFIRMED 只有兩條路:

```
(a) 逐條 ratify        人指名這一條,human reference 直接掛在 rule 上
(b) 被已批准的 Derivation 覆蓋   AND  該 rule 自己的 recheck 通過
                       rule.derivation_id 指向那條 Derivation,
                       human reference 由 Derivation 提供(滿足 I3b)
```

**(b) 為什麼不算橡皮圖章**(理由要寫進 B1.5 的文件):
人批准的是**一條可重跑的推導**,不是 63 個名字。每一條 rule 都附著
`recheck`,CI 每次重驗;`BUCKET_RULES` 一改,對不上的那條**立刻掉回
PROVISIONAL 並報錯**。人簽的是「我確認這條推導成立」,不是「我相信這 63 條」。

工單 `out/ratify_worklist.md` 分三批:

```
第 1 批  63 條 rule 可重驗   顯示:名字 / 桶 / 命中的 BUCKET_RULES 關鍵字
                            → 走 (b):批准一條 Derivation
第 2 批  ~6 條 arithmetic/synonym  顯示:那條等式或配對金額 + 出處頁
                            → 走 (a),逐條看,證據是硬的
第 3 批  ~3 條 無任何可重驗證據   政府債券 / 貨幣交換 / 外匯換匯合約
                            → 走 (a),**逐條問人**,問不出來就停在 PROVISIONAL
```

⚠️ **不准把第 3 批塞進第 1 批。** 那 3 條正是 G15 要抓的東西 —— 若真有名字
是被機器偷偷塞進 SYN 的,它們會在這裡現形。

### 3.4 GROUP_SYN / GENERIC / 欄位角色

| 對象 | 遷移成什麼 | reference |
|---|---|---|
| `GROUP_SYN`(5) | `scope="group"` 規則 | 同 §3.1;中信「衍生金融工具」註解已記載算術依據(7 列相加 = 附註) |
| `GENERIC`(4) | `scope="generic"` 的**布林規則**,不帶桶 | `kind="rule"`,依據 `BUCKET_RULES`「其他:表上真的印著『其他』的列」 |
| 欄位角色 | `scope="record"` 的 **Decision**(不是 taxonomy rule) | `kind="arithmetic"`,recheck = 「該 record 是否含 `is_adj` 列」 |
| `COST_COLS`/`BOOK_COLS` | `scope="column"` 規則 | `kind="rule"`,detail 指向 `config.py` 那段註解 |

### 3.5 B1 的閘門

```
[ ] 74 + 5 + 4 條逐條有 ≥1 reference,或明確標為「無證據」
[ ] 每條 rule/synonym/arithmetic reference 都能重跑,CI 重驗全綠
[ ] **B1 產出的 CONFIRMED == 0**(注入:讓 B1 自行升級一條 → 必須紅)
[ ] 注入:把一條 rule reference 的關鍵字改掉 → 重驗必須紅
[ ] 注入:把一個批量抄列 commit 標成 human → 必須被 §3.1 判準擋下
[ ] I1 / I2 / I3a / I3b 注入測試綠
[ ] **等價**:`decide()` 對 583 列算出的 mapping,與今天 `buckets.bucket()`
    逐列相同 —— 證明遷移沒改分類結果
[ ] out/ratify_worklist.md 產出,三批數字與 §3.3 一致
[ ] facts/ 零變更
```

**B1 的閘門不是「可發布單位 == 25」。** 那要等 B1.5 人工 ratify。

### 3.6 B1.5 的閘門(人工)

```
[ ] 第 1 批:一條 Derivation 被批准,綁定 derivation_id + bucket_rules_revision
    + applies_to(逐一列出)+ approved_by/at;63 條 rule 因此 CONFIRMED,每條 recheck 綠
[ ] 第 2、3 批:逐條 ratify 或明確留在 PROVISIONAL
[ ] 可發布單位數回到 25;**若掉了,逐條說明是哪個名字沒有人工來源**
[ ] 注入:撤銷該 Derivation → 63 條立刻掉回 PROVISIONAL,可發布數掉下來
[ ] 注入:改動 config.BUCKET_RULES(revision hash 變)→ 63 條自動降回 PROVISIONAL
    且報出「依據版本已變」,不是靜靜維持 CONFIRMED
[ ] 注入:把一條 rule_id 從 applies_to 拿掉 → 該條降回 PROVISIONAL
```

---

## 4. B2 —— 兩道閘門與新 routing

> **依賴:先做 C3。** 使用者已裁示 C3(零行為搬移 ingest/routing 進
> `core.ingest`)先於 B2(改語意)。B2 在 `core.ingest` 上改,不碰 `fill.py`。

### 4.1 四種失敗,四條路

| 失敗類 | 具體檢查 | 存進 facts? | 擴頁? | 消耗預算? | 去哪 |
|---|---|---|---|---|---|
| **schema** | `core.contracts.parse_cell()` raise | ❌ | ❌ | ❌ | 退回 agent 重抄。這不是資料問題,是格式沒抄對 |
| **來源/算術** | `source` · `check_identity` · `check_anchor` · `check_col_totals` | ❌ | ✅ | ✅ | `core.expand_policy.may_expand()` 已實作,直接用 |
| **分類** | `check_buckets` | ✅ **存** | ❌ | ❌ | Decision 記 UNCLASSIFIED/PROVISIONAL → review queue |
| **reconciliation** | `check_cross` | ✅ **存** | ❌ | ❌ | Gate 2 擋住 → review queue |

判準一律是「**哪一道檢查失敗**」,不是比對訊息字串。
`core/expand_policy.py` 的 `TRIGGERS` / `NEVER` 是唯一來源,**import 它,不要另寫**。

### 4.2 兩道閘門(**check_cross 在 Gate 2 —— 使用者已裁示**)

```
Gate 1 存檔閘門(Ring 0,core.ingest)
    來源:source_page 在候選頁集合內
    結構:core.contracts.parse_cell() 不 raise
    算術:check_identity · check_col_totals · check_anchor
          ← **恰好是 core.expand_policy.TRIGGERS 那一組,共用一個定義**
    → 通過就寫進 facts/,**不管分不分得出桶**

Gate 2 發布閘門(Ring 1,core.publish)
    check_buckets · **check_cross** · coarse · wide 三段恆等式
    · 全格 Decision == CONFIRMED
    → 不過就不發布,但 raw facts 已經在 git 裡了
```

`check_cross` 移進 Gate 2 的理由(已裁示):它今天切不開(`bk=None` 一跑就
AttributeError),且會**因分類未知而失敗**(國泰 202504:「兩邊都對不到桶」)。
留在 Gate 1 會擋住歸檔,正好打掉 B-I 想解的那個 case。

### 4.3 覆寫保護與重綁

同一格重新提交(擴頁後的超集)覆寫前,舊版寫進
`facts/_superseded/{doc}__{cls}__{n}.json`,並依 §2.2 的重綁協定處理 Decision。
這樣「不得因分類未知而丟失」是**字面成立**的,不是靠承諾。

### 4.4 分類未知的完整處置(不准打折)

> **分類未知永不觸發 expand,永不消耗重試預算,永不丟棄 raw facts。**
> 最多在工單顯示提示,**提示不得自動變成動作**。

玉山家族會變成:第一層兩列小計 → ①②④⑥ 全綠 → **Gate 1 通過 → raw facts 歸檔**
→ 兩列 UNCLASSIFIED → **Gate 2 擋住,不可發布** → 進 review queue。

**代價要說實話**:失去自動擴頁到 p24 的能力。補償是 B4 的人工出口 `(c)`。

### 4.5 B2 的驗收 —— **具名 fixture + idempotence**(**使用者裁示 item 4**)

M-B5 已證明「facts 格數上升」不能當閘門:兩個主角今天都已在 facts 裡
(斷言恆真),另外 4 格從未抄過(B2 變不出來)。所以改成:

**(1) 具名 replay fixture(合成輸入,內容取自實測)**

| fixture | 輸入 | 必須成立的斷言 |
|---|---|---|
| **F1 玉山 202102_5847_AI3 OCI 第一層** | p23 兩列小計:權益 16,018,428 + 債務 271,692,749 = printed_total = 錨 287,711,177 | Gate 1 **通過** ∧ facts 寫入(tmp) ∧ 2 筆 Decision 皆 UNCLASSIFIED ∧ Gate 2 **不通過** ∧ review item 建立 1 筆 ∧ **未擴頁** ∧ **retries 未增加** |
| **F2 玉山家族其餘 4 格** | 同型態合成(202102_AI2 / 202302 / 202402 / 202502) | 同 F1。**這 4 格今天不在 facts,fixture 是合成的,不得宣稱「已抄錄」** |
| **F3 國泰 202504_5835_AI3 Trading** | 真實 record,但 taxonomy **移除**「基金受益憑證」 | Gate 1 通過 ∧ 歸檔 ∧ Decision PROVISIONAL(`rules.propose()` 提得出「股票」)∧ Gate 2 擋住 ∧ **未擴頁、retries 未增加**(對照:今天實測白燒 8 輪) |
| **F4 反向** | schema 壞掉的輸入(拿掉 `printed_total`) | Gate 1 **不通過** ∧ **facts 未寫入** ∧ 無 Decision ∧ 無 review item |

**(2) idempotence(同一輸入重跑)**

```
[ ] 同一輸入連跑兩次:facts 不得出現重複格或重複 record
[ ] 同一輸入連跑兩次:decisions 不得重複建立(同 occurrence 只有一筆)
[ ] 同一輸入連跑兩次:review/queue.jsonl 不得重複 append 同一 item
[ ] 第二次跑完,三者的檔案內容**逐位元組相同**
[ ] 注入:把 review item 改成無條件 append → idempotence 測試必須紅
```

### 4.6 fixture 的寫檔紀律(**硬性**)

B2 的 fixture 會寫 `facts/` `decisions/` `review/`。**一律寫進 tmp 目錄**,
用注入路徑或環境變數把根目錄換掉。測試結束用 try/finally 還原。
**`facts/` 在整個 Phase B 全程唯讀,`git diff facts/` 必須為空。**

---

## 5. B3 / B4 / B5

### B3 —— UNCLASSIFIED 參與對帳但不冒充

- `wide.view()` 今天已把認不得的列放進 `unknown` 且 `View.ok` 回 False。
  B3 是把它接上 Decision,**不是重寫 wide**。
- `status` 的「已完成」拆成 **已存檔** 與 **可發布** 兩個數字。今天 36 格
  兩者相等,B2 之後會分岔 —— **分岔是產出,不是退步**。
- 閘門:I4 注入綠 ∧ `status` 顯示兩個數字。

### B4 —— review queue 三種處置

```
(a) 收錄成新科目        → 走 ratify(),taxonomy 升級,該 rule 轉 CONFIRMED
(b) 退回(不是科目)      → 標記,不再提示
(c) **這是小計,頁沒找全 → 人工觸發擴頁**   ← 補償 ⑤ 的唯一出口
```

`(c)` 是**人決定的**,不是程式推論的。**人工觸發的擴頁不消耗重試預算。**

閘門:對玉山家族按 `(c)` → 擴到正確頁 → 重抄後可發布 ∧ **retries 未因分類未知增加**
∧ 重抄後 Decision 依 §2.2 重綁正確(不是全部孤兒化)。

### B5 —— I5 上線

- `ratify()` 是唯一能產生 CONFIRMED 的函式(§2.5)。
- 閘門:`ratify` 一條 → 某格由不可發布轉可發布,且 git diff 可審 ∧ I5 綠。

⚠️ **順序約束(不是建議)**:B1.5 的人工 ratify 必須做完才能開 I5,
中間不得留下「I5 已開但遷移未完」的狀態 —— 那會讓網站瞬間清空。

---

## 6. 階段與閘門總表

| 階段 | 做什麼 | 閘門 | 依賴 |
|---|---|---|---|
| **B0** | `core/decisions.py` 型別(Occurrence / TaxonomyRule / Decision / Derivation)+ `taxonomy/` schema,零行為改變 | I1–I3b 注入綠 ∧ 九支測試綠 | 無 |
| **B1** | SYN/GROUP_SYN/GENERIC 遷移 + reference + 批准工單。**產出 0 條 CONFIRMED** | §3.5 | B0 |
| **B1.5** | **人工 ratify**:批准 1 條 Derivation(第 1 批)+ 逐條批准第 2、3 批 | §3.6 | B1 + **使用者** |
| **C3** | (Phase A)零行為搬移 ingest/routing 進 `core.ingest` | E5 綠 ∧ 四條出口實跑 | Phase A |
| **B2** | 兩道閘門 + `_superseded/` + 新 routing + 重綁協定 | §4.5 | B1 **且** C3 |
| **B3** | UNCLASSIFIED 進恆等式不冒充 | I4 綠 ∧ status 兩個數字 | B2 |
| **B4** | review queue 三處置 + 人工擴頁 | 玉山家族走完 `(c)` | B2 |
| **B5** | I5 上線 | I5 綠 | B1.5 + B4 |

---

## 7. 與 `plan_clean_core.md` §3 的差異(都已裁示,照本文件做)

| # | §3 原本 | 本文件 | 依據 |
|---|---|---|---|
| 7.1 | B1 閘門 = 可發布數不變(24);`git log -S` 找到 commit → human reference | 拆成 B1(機械,產出 0 CONFIRMED)+ B1.5(人工 ratify,回到 25) | 實測 M-B1:74/74 有 commit = 恆真閘門;60/74 來自批量抄列 commit。**使用者已裁示** |
| 7.2 | `check_cross` 在 Gate 1 | 移到 Gate 2 | 它切不開且會因分類未知而失敗,留 Gate 1 會擋住歸檔。**使用者已裁示** |
| 7.3 | B2 與 C3 先後未定 | **先 C3 再 B2** | 兩者都改 routing;先 B2 等於改一個排在 C3 退場清單上的 `fill.py`。**使用者已裁示** |
| 7.4 | I1:`decide()` 回傳型別上不該存在 CONFIRMED | `decide()` **可以**回 CONFIRMED,但只能靠引用已 ratify 的 rule | **使用者裁示 item 1** |
| 7.5 | I3:每個 CONFIRMED Decision ≥1 human reference | 拆 I3a(occurrence 引用已批准 rule)/ I3b(human 存在 rule 上) | **使用者裁示 item 2**。避免 583 筆各複製一份人工背書 |
| 7.6 | Occurrence = (cell_key, source_page, row_index) | 加入 record identity + fingerprint;原三元組降為**僅供人閱讀的 locator** | **使用者裁示 item 3**。實測它 583/583 唯一但只是樣本 |
| 7.7 | B2 閘門「facts 格數上升」 | 改具名 fixture(F1–F4)+ idempotence | **使用者裁示 item 4**;實測 M-B5 證明原寫法恆真 |
| 7.8 | 25 vs 24 | 基準 **25**(`test_rulings.py` 已更新) | 2026-07-28 使用者裁示,採 U2 字面規則 |

---

## 8. 常見誤區

| 誤區 | 正解 |
|---|---|
| 把「git log 找得到 commit」當成 human reference | 74/74 全過 = 恆真閘門。判準見 §3.1 |
| B1 自行把看起來像人工裁示的 commit 升成 CONFIRMED | §0.2 第 2 條:升級只能經 `ratify()`。B1 產出 0 條 CONFIRMED |
| 為了讓可發布數不掉,把批量 commit 算成人工背書 | §0.2 第 3 條。**數字誠實地掉下來是產出** |
| `decide()` 自己造 CONFIRMED | I1。它只能「轉述」一條已批准的 rule(§2.5 那張表) |
| 每筆 CONFIRMED occurrence 都塞一份 human reference | I3 已拆:人簽在 rule 上,occurrence 引用 rule(§2.6) |
| 用 `(cell_key, source_page, row_index)` 當契約 key | §2.2:那是 locator,不是 identity。重抄會位移 |
| 重抄後用 `ordinal` 硬對舊 Decision | 用 `record_fp` + `row_fp` 重綁(§2.2 五步協定) |
| 斷言「玉山 5 格在 facts 裡」當 B2 閘門 | M-B5:1 格已在、4 格從未抄過。fixture 要用**第一層提交**(§4.5) |
| B2 的 fixture 寫進真實 `facts/` | §4.6:一律寫 tmp,`git diff facts/` 全程必須為空 |
| 把桶寫回 `facts/` | §0.2 第 1 條。facts 是原始層,分類永不改寫它 |
| 把 UNCLASSIFIED 塞進「其他」 | I4。表上印著「其他」才進 OTHER,兩件事必須分得開 |
| 分類未知時「擴一下頁也沒差」 | 已裁示不准。M3 證明那訊號一半指向小計、一半指向真科目 |
| 在 B2 另寫一份「哪些失敗可以擴頁」 | `core/expand_policy.py` 是唯一來源,import 它 |
| 先做 B2 再做 C3 | §7.3 已裁示:先 C3 |
| 順手修 `check_cross(bk=None)` 的 AttributeError | 禁改檔案,今天無人呼叫。拆 `transcribe.py` 那一步才處理 |
| 以為 Phase A 已解掉分類根因 | `plan_clean_core.md` §2.6:C2/C3 只解格式與編排,語意根因在這裡 |
| B1 做完就開 I5 | §5 順序約束:中間必須有 B1.5 人工 ratify |
