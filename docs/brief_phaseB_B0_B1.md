# 施工單 —— Phase B 的 B0 / B1

> 給執行者(Sonnet)。規格見 `docs/plan_phaseB.md`,**衝突時以本單為準,
> 不確定就停下來問,不要自行裁示。**
>
> 本單只做兩步:**B0(型別與不變式)→ B1(SYN 遷移與批准工單)**。
> **做完 B1 就停下來回報。**
>
> **B1.5(人工 ratify)是使用者本人的動作,本單不得執行。**
> C3 / B2 / B3 / B4 / B5 都不在本單範圍。

---

## 0. 先讀這段(硬性約束)

### 0.0 使用者親自裁示的鐵則(2026-07-28)

**這些是使用者的原話。任何一條與其他文件衝突,以這些為準。**

| # | 鐵則 | 本單範圍? |
|---|---|---|
| 1 | **`ratify()` 是唯一能建立或升級 CONFIRMED taxonomy rule 的動作,只吃人工輸入** | ✅ B0 要實作型別與檢查。**B1 不得呼叫它** |
| 2 | **`decide()` 不得憑機器推論產生 CONFIRMED,但可引用已 ratify 的 CONFIRMED rule 產生 CONFIRMED occurrence decision** | ✅ B0 的 I1,要落成注入測試 |
| 3 | **CONFIRMED occurrence 必須引用已批准的 taxonomy rule;human reference 存在 rule 上,不要求每筆 occurrence 重複帶** | ✅ B0 的 I3a / I3b |
| 4 | **occurrence key 必須含穩定 record identity / fingerprint。`(cell_key, source_page, row_index)` 只能視為現況樣本唯一,不可作為未來資料契約** | ✅ B0 的型別設計 |
| 5 | **B1.5 由人批准一個具體、版本化、可重跑的 derivation,不是逐條簽 63 個名稱。批准綁定 derivation id + BUCKET_RULES revision hash + 適用 rule ids + 批准人與時間;recheck 失效或依據 revision 改變時,相關 rule 自動降回 PROVISIONAL** | ✅ B0 實作降級純函數 + 注入測試;**B1 只產出「提案」,不得批准** |
| 6 | **不准為了讓可發布單位數回到 25 而放寬 reference 的認定。數字誠實地掉下來是產出,不是失敗** | ✅ 見 §B1.2 |
| 7 | **一次性回報。** B0 + B1 全部做完、跑完總表之後才回報一次 | ✅ 見 §回報格式 |

### 0.1 絕對不准做

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` `results.py` `build.py` `bridge_v2.py` `bridge_v3.py` `fill.py` `pipeline.py` | 已驗證的底層能力。**唯一合法的重用方式是 `import`** |
| 修改 Phase A 的 `core/` 既有檔(`units.py` `expand_policy.py` `contracts.py` `store.py` `reconcile.py` `cli.py`) | 等價閘門已經綠了,動它就要重跑全部。B0 只**新增**檔案 |
| 改寫 `facts/` —— **一個 byte 都不准變** | facts 是原始層,分類永遠不得改寫它(鐵則:§0.0 表外,見 plan_phaseB §0.2 第 1 條) |
| 執行 `ratify()` / 批准任何 derivation / 產生任何 CONFIRMED | 那是 B1.5,使用者本人的動作 |
| 跑 `build.py` / `bridge_v3.py` / 任何 `--write` | 會動到已發布的 `data.json` |
| 修改 `data.json` `snapshots/` `preview/` `anchors/` | 唯讀輸入 |
| 測試寫進真實 `facts/` `taxonomy/` `decisions/` | 一律寫 tmp,用參數注入根目錄。測試後還原 |
| 呼叫任何模型 API | 使用者已定案:程式不呼叫 |
| 「順手」重構、改名、整理、補型別 | 等價閘門會分不出差異來自搬家還是整理 |
| 為了讓測試變綠而放寬測試 | 測試紅了要回報,不是改判準 |
| 做 C3 / B2 / B3 / B4 / B5 | 不在本單。做完 B1 停 |

### 0.2 環境

```bash
source .venv/bin/activate
```

沒有 pytest。測試是可執行腳本,`python3 test_x.py`,exit 0 = 綠。

**現有測試(每一步結束都要全綠)**:

```bash
# 九支既有
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done
# Phase A 新增六支
for t in test_units.py test_expand_policy.py test_contracts.py \
         test_e2_equiv.py test_ring.py test_rulings.py; do
  printf "%-20s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done
```

`test_build.py` 跑約 **460 秒**(已知,C4 未把發布層改接 `core.reconcile`)。
**本單不必跑它** —— B0/B1 不碰發布層。

### 0.3 已量到的基準(2026-07-28 實測,不要重新推導,直接用)

```
分類表規模:   SYN 74 條 / GROUP_SYN 5 條 / GENERIC 4 條 / PENDING 0 條
事實庫:       36 格 / 65 record / 583 列 / 75 個相異列名
規則可重現:   rules.propose() 與 SYN 一致 63/74、提不出 11/74、**衝突 0/74**
今天分不出桶: buckets.bucket() 回 None 的列 0 / 583
identity 實測: (cell_key, source_page, row_index) 583/583 唯一 ← **僅樣本**
              同格同頁多份 record 0 格
              (source_kind, total_col, printed_total) 格內撞號 0 格
              record 內 (norm名, group, 合計欄金額) 重複 0 筆
同名多桶:     其他 → {其他, 衍生};其他(註) → {其他, 衍生}(靠 group 分開)
SYN commit:   引入 74 條的相異 commit 12 個;60/74 來自「一次塞 ≥5 條」的批量 commit
              逐條人工裁示的 commit 只有 3 個:
                3d7552e3(國外機構發行債券)· 166934fe(兆豐 REIT)· d6ab905d(基金受益憑證)
註解覆蓋:     34/74 緊鄰有註解區塊、40/74 完全裸露
```

`rules.propose()` 提不出的 11 條(B1 工單第 2、3 批的來源):

```
政府債券 → 公債            貨幣交換 → 衍生         外匯換匯合約 → 衍生
不動產投資信託受益證券 → 資產基礎   國外機構發行債券 → 公債
CMO → 資產基礎             RMBS → 資產基礎
定存單 → 可轉讓定存單       定期存單-可轉讓 → 可轉讓定存單
換匯 → 衍生                商品交換 → 衍生
```

---

## 步驟 B0 —— 型別與不變式

**目的**:把 Decision 模型寫成程式碼並讓不變式**可注入、會失敗**。
**這一步零行為改變** —— 不產生任何 taxonomy/decisions 檔案,只新增模組與測試。

### B0.1 `core/decisions.py`(新檔,純函數,Ring 1)

**零 IO**。不 import `pypdfium2` / `requests` / `locate` / `build` / `bridge`。

```python
# core/decisions.py
"""Decision 資料模型。occurrence-level、有狀態、有依據。

**`facts/` 是原始層,分類永遠不得改寫它。** 本模組只產生指回 facts 的決定,
任何「把桶寫回 facts」的函式都不准出現在這裡。
"""

# ── 狀態 ──────────────────────────────────────────────────────────
CONFIRMED    = "CONFIRMED"
PROVISIONAL  = "PROVISIONAL"
UNCLASSIFIED = "UNCLASSIFIED"

REFERENCE_KINDS = ("human", "rule", "synonym", "arithmetic", "prior_year", "group")
RULE_SCOPES     = ("name", "group", "generic", "column")
OCC_SCOPES      = ("row", "column", "record")
```

四個型別,欄位照抄 `plan_phaseB.md` §2.2 / §2.3 / §3.3,**一個欄位都不准加減**:

```python
def locator(cell_key, source_page, row_index) -> dict:
    """人類可讀的定位。**不是 key** —— 不得用來比對或綁定(鐵則 4)。"""

def record_fp(rec) -> str:
    """sha256(source_kind, total_col, printed_total, printed_totals)。

    **不含 source_page**:擴頁重抄後頁碼會變,含進去等於每次重抄都變成新 record。
    **不含 rows**:多抄到一列是「同一份 record 的更完整版本」,不是另一份。
    """

def row_fp(row, total_col) -> str:
    """sha256(norm(name), group, cols[total_col])。"""

def occurrence(cell_key, rec, scope, ordinal=None, row=None) -> dict:
    """{cell_key, record_fp, scope, ordinal, row_fp}。scope != "row" 時 row_fp 為 None。"""
```

```python
def make_reference(kind, detail, at, recheck=None) -> dict
def make_rule(rule_id, scope, mapping, state, references,
              derivation_id=None, approved_by=None, approved_at=None) -> dict
def make_decision(occ, loc, name, group, mapping, state,
                  taxonomy_ref=None, references=(), at=None, by=None) -> dict
def make_derivation(derivation_id, description, predicate,
                    bucket_rules_revision, applies_to,
                    approved_by, approved_at, references) -> dict
```

### B0.2 不變式檢查(純函數,**每一條都要有注入測試**)

```python
def validate_rule(rule) -> list[str]:
    """I3b:state==CONFIRMED 的 rule 必須有 ≥1 條 kind=="human" 的 reference。"""

def validate_decision(decision, rules_by_id) -> list[str]:
    """I2 + I3a。
      I2  mapping is None ⟺ state == UNCLASSIFIED
      I3a state==CONFIRMED ⇒ taxonomy_ref 非空,且它指到的 rule.state == CONFIRMED
          **不要求 decision 自己帶 human reference**(鐵則 3)
    """

def decide(row, group, rules_by_name, propose_fn) -> dict:
    """唯一的狀態表(plan_phaseB §2.5),**不准另寫分支**:

        命中 CONFIRMED rule           → CONFIRMED,taxonomy_ref 指向它
        命中 PROVISIONAL rule         → PROVISIONAL,taxonomy_ref 指向它
        taxonomy 沒有但 propose 提得出 → PROVISIONAL,自帶 reference
        提不出候選                     → UNCLASSIFIED,mapping = None

    **本函數沒有任何一條路徑可以自己造出 CONFIRMED。** 它只能「轉述」
    一條已經被人批准過的 rule(鐵則 2)。
    """
```

### B0.3 降級(鐵則 5,**純函數**)

```python
def stale_confirmations(rules, derivations, bucket_rules_text) -> list[tuple[str, str]]:
    """回傳 [(rule_id, 降級原因)]。任一款成立就要降回 PROVISIONAL:

      ① derivation.bucket_rules_revision != sha256(bucket_rules_text)
      ② 該 rule 自己的 recheck 跑起來不成立
      ③ rule_id 不在 derivation.applies_to 裡

    **降級要大聲報錯並列出是哪幾條、因為哪一款,不准靜靜降級。**
    ① 是使用者 2026-07-28 加的:BUCKET_RULES 一改,整批批准的依據就變了 ——
    不是逐條 recheck 過了就算數,人當初看的是那一版散文。
    """

def apply_downgrade(rules, stale) -> dict:
    """回傳降級後的 rules。**不改輸入**。"""
```

### B0.4 重綁協定(純函數)

```python
def rebind(old_decisions, new_cell_records) -> dict:
    """重抄後把舊 Decision 綁到新 record。五步(plan_phaseB §2.2):

      1. 用 record_fp 找對應的舊 record;找不到 → 全部視為新 occurrence
      2. 在該 record 內用 row_fp 綁定;綁上的沿用舊 mapping 與 state
      3. 綁不上的舊 occurrence → 標 superseded,**不刪**
      4. 綁不上的新 occurrence → 建新 Decision
      5. **絕不用 ordinal 硬對**

    ⚠️ row_fp 碰撞要 **raise**,不准靜靜覆蓋。今天實測 0 筆碰撞,
    但那是樣本結果不是保證。
    """
```

### B0.5 `test_decisions.py`(新檔)

用**手寫的假 rule / 假 decision / 假 record**,不碰真實資料。

| # | 命題 | 注入什麼 |
|---|---|---|
| D1 | `decide()` 命中 CONFIRMED rule → CONFIRMED,且 `taxonomy_ref` 指向它 | — |
| D2 | `decide()` 在**無** `taxonomy_ref` 時**不可能**回 CONFIRMED(I1) | 讓 `decide()` 直接回 CONFIRMED → **必須紅** |
| D3 | `decide()` 命中 PROVISIONAL rule → PROVISIONAL(不是 CONFIRMED) | 把它升成 CONFIRMED → **必須紅** |
| D4 | `decide()` 提不出候選 → UNCLASSIFIED 且 mapping is None | — |
| D5 | I2:`(mapping=None, state=CONFIRMED)` → `validate_decision` 拒絕 | 讓它通過 → **必須紅** |
| D6 | I3a:CONFIRMED occurrence 引用 **PROVISIONAL** rule → 拒絕 | 讓它通過 → **必須紅** |
| D7 | I3a:CONFIRMED occurrence **無** `taxonomy_ref` → 拒絕 | 讓它通過 → **必須紅** |
| D8 | I3b:CONFIRMED rule **無** human reference → `validate_rule` 拒絕 | 讓它通過 → **必須紅** |
| D9 | I3a **反向**:CONFIRMED occurrence **不必**自帶 human reference → 必須通過(鐵則 3) | 要求它自帶 → **必須紅** |
| D10 | 降級①:derivation 的 `bucket_rules_revision` 與現況不符 → 該批 rule 全降 PROVISIONAL 且列出原因 | 忽略 revision → **必須紅** |
| D11 | 降級②:rule 的 recheck 不成立 → 降 PROVISIONAL | — |
| D12 | 降級③:rule_id 不在 `applies_to` 裡 → 降 PROVISIONAL | — |
| D13 | `record_fp` 不含 source_page:同一份 record 換頁碼 → fp **相同** | 把 source_page 放進 fp → **必須紅** |
| D14 | `record_fp` 不含 rows:多抄一列 → fp **相同** | 把 rows 放進 fp → **必須紅** |
| D15 | `rebind`:重抄後靠 `row_fp` 綁對,**ordinal 位移不影響** | 改用 ordinal 綁 → **必須紅** |
| D16 | `rebind`:綁不上的舊 occurrence 標 superseded 而**不刪** | 刪掉 → **必須紅** |
| D17 | `row_fp` 碰撞 → **raise**,不靜靜覆蓋 | 改成覆蓋 → **必須紅** |

### B0 的驗收

```
[ ] core/decisions.py 存在,零 IO,不 import pypdfium2/requests/locate/build/bridge
[ ] test_decisions.py 綠,D2/D5/D6/D7/D8/D9/D10/D13/D15/D17 各自「注入 → 紅」的實測輸出各貼一段
[ ] core/ 既有五個模組零修改(git diff 為空)
[ ] facts/ 零變更
[ ] 九支既有測試 + Phase A 六支全綠
[ ] git status:只有新增檔案
```

---

## 步驟 B1 —— SYN 遷移與批准工單

**目的**:把今天的隱性決定顯性化,**不改行為**。
**B1 產出 0 條 CONFIRMED**(鐵則 1、5)。

### B1.1 `core/migrate_syn.py`(新檔)

讀 `buckets.SYN` / `GROUP_SYN` / `GENERIC`(**只讀,不改**),
逐條建立 reference,寫 `taxonomy/rules.json`。

四種證據,**取得到的全部收下**(一條可有多個 reference):

| 證據 kind | 怎麼取得 | recheck 存什麼 |
|---|---|---|
| `rule` | `rules.propose(buckets.norm(key))` 的桶 == SYN 的桶 | 可重跑的斷言字串,例如 `rules.propose("金融債券") == "金融債"` |
| `synonym` | 對 `facts/` 跑 `synonyms.candidates()`,同金額配到已知桶的對造 | 配對的金額 + 兩邊名字 + 格 key |
| `arithmetic` | 原始碼註解記載的等式(CMO+RMBS = 附註那類),**逐條抄成可重跑的斷言** | 那條等式 |
| `human` | `git log -S` 找到的 commit,**且符合下面的逐條裁示判準** | `None`(一次性,不可重跑) |

**逐條裁示判準**(只給工單標註用,**不是自動升級的授權**):

- commit 訊息或 diff 註解**指名了這個名字**與**它的依據**;**且**
- 該 commit 在 `buckets.py` 動到的 SYN 條目數 ≤ 2,或訊息是
  `decide(...)` / 「人審決定」/「使用者裁示」形式。

**批量抄列 commit(一次塞 ≥5 條、訊息是抄列進度)一律不標 human。**
實測 60/74 落在這一類 —— 把它們當 human 就是恆真閘門(§0.3)。

⚠️ **`git log -S` 要用原始碼實際字面。** 衍生/評價調整那 26 條在原始碼是
`"衍生工具": DERIVATIVE`(常數,不是字串),只搜 `"衍生工具": "衍生"` 會漏掉。
兩種形式都要試。(這個坑我踩過,見 `docs/plan_phaseB.md` M-B1。)

### B1.2 全部產出 PROVISIONAL

```
B1 跑完的預期分布:
    CONFIRMED    0 條          ← **依定義,不是巧合**
    PROVISIONAL  ~74 條
    UNCLASSIFIED 0 ~ 少數(三種可重驗證據都取不到的)
```

**即使找到符合判準的 human commit,B1 也不得升級成 CONFIRMED。**
B1 對 human 證據做的事,是把它整理進批准工單讓人**確認**(鐵則 1)。

此時若開 I5,可發布單位 = 0。**這不是 bug**,是 `plan_phaseB.md` §3.2 寫的
預期結果。**不准為了讓數字好看而放寬判準**(鐵則 6)。

### B1.3 `taxonomy/` 產出

```
taxonomy/rules.json         74 + 5 + 4 條,全部 state=PROVISIONAL
taxonomy/derivations.json   **建立成空的 []** —— 批准是 B1.5,B1 不得寫入任何一條
```

### B1.4 `out/ratify_worklist.md`(批准工單)

分三批,**每批的審閱成本不同**:

```
第 1 批  63 條 rule 可重驗    每行:名字 / 桶 / 命中的 BUCKET_RULES 關鍵字 / recheck
                             → 提案一條 Derivation 給人批准(見下)
第 2 批  ~6 條 arithmetic/synonym  每行:那條等式或配對金額 + 出處頁
                             → 逐條看
第 3 批  ~3 條 無任何可重驗證據  政府債券 / 貨幣交換 / 外匯換匯合約
                             → **逐條問人**,問不出來就停在 PROVISIONAL
```

工單裡要附一份**待批准的 Derivation 提案**(填好欄位但 `approved_by`/
`approved_at` 留空,`derivations.json` 仍是空的):

```
derivation_id          deriv:BUCKET_RULES-keyword-v1
description            rules.propose(norm(name)) 的桶 == taxonomy 的桶,
                       且 rules.audit(BUCKET_RULES) 無夾帶詞
predicate              <可重跑的判定式>
bucket_rules_revision  <sha256(config.BUCKET_RULES) 當下的值>
applies_to             <63 個 rule_id,逐一列出,不准用萬用字元>
approved_by / at       (留空,B1.5 由使用者填)
```

⚠️ **不准把第 3 批塞進第 1 批。** 那 3 條正是 G15 要抓的東西 —— 若真有名字
是被機器偷偷塞進 SYN 的,它們會在這裡現形。

### B1.5(本單**不做**)

人工 ratify。**這是使用者本人的動作,Sonnet 不得執行。**

### B1.6 `test_taxonomy_migration.py`(新檔)

| # | 命題 | 注入什麼 |
|---|---|---|
| M1 | 74 + 5 + 4 條逐條有 ≥1 reference,或明確標為「無證據」 | — |
| M2 | **B1 產出的 CONFIRMED == 0** | 讓遷移自行升級一條 → **必須紅** |
| M3 | 每條 `rule`/`synonym`/`arithmetic` reference 的 recheck 都能重跑且成立 | — |
| M4 | 注入:把一條 rule reference 的關鍵字改掉 → 重驗**必須紅** | 見左 |
| M5 | 注入:把一個批量抄列 commit(≥5 條)標成 human → 必須被 §B1.1 判準擋下 | 見左 |
| M6 | `taxonomy/derivations.json` 是**空的** | 讓 B1 寫進一條 → **必須紅** |
| M7 | 工單三批的條數與 §0.3 的實測一致(63 / ~6 / ~3) | — |

### B1.7 `test_decide_equiv.py`(新檔)—— **B1 的等價閘門**

```python
# 對 facts/ 的 583 列逐列比對
new = core.decisions.decide(row, group, rules_by_name, rules.propose)["mapping"]
old = buckets.bucket(row)
```

斷言:**583 列逐列 `mapping` 相同**。這證明遷移沒有改變分類結果。

⚠️ 注意 `GENERIC` + `group` 的路徑:「其他」「其他(註)」要靠段落才分得出
{其他, 衍生}(§0.3),`decide()` 必須把 `group` 傳進去,否則這兩個名字會分錯。

### B1 的驗收

```
[ ] taxonomy/rules.json 產出,74+5+4 條,**全部 PROVISIONAL**
[ ] taxonomy/derivations.json 存在且為空 []
[ ] out/ratify_worklist.md 產出,三批數字與 §0.3 一致
[ ] test_taxonomy_migration.py 綠,M2/M4/M5/M6「注入 → 紅」各貼一段
[ ] test_decide_equiv.py 綠:583 列逐列 mapping 相同(貼數字)
[ ] git diff facts/ 為空(一個 byte 都沒變)
[ ] git diff buckets.py 為空(只讀,不改)
[ ] 九支既有測試 + Phase A 六支全綠
```

---

## 回報格式

**一次性回報(鐵則 7)。** B0 / B1 兩步全部做完、**且跑完下面這張總表**之後,
才回報一次。中間不要逐步回報,也不要做完 B0 就來問要不要繼續 —— 除非遇到
§0.0 說的「停下來問使用者」那種情況。

### 回報前必須跑完的總表

```bash
# ① B0 注入測試
python3 test_decisions.py            # D2 D5 D6 D7 D8 D9 D10 D13 D15 D17

# ② B1 注入 + 等價
python3 test_taxonomy_migration.py   # M2 M4 M5 M6
python3 test_decide_equiv.py         # 583 列逐列相同

# ③ 回歸(九支既有,一支都不准紅)
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ④ 回歸(Phase A 六支,一支都不准紅)
for t in test_units.py test_expand_policy.py test_contracts.py \
         test_e2_equiv.py test_ring.py test_rulings.py; do
  printf "%-20s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ⑤ 唯讀證明
git diff --stat facts/ buckets.py core/units.py core/expand_policy.py \
                core/contracts.py core/store.py core/reconcile.py
```

**任何一項紅了,不要修判準,回報它。**
(`test_build.py` 本單不必跑 —— 它 460 秒且不碰 B0/B1 的範圍。)

### 回報這六段

1. **每一步的驗收 checklist**,逐條打勾或說明為什麼沒打勾。
2. **注入測試的實測輸出** —— B0 的 D2/D5/D6/D7/D8/D9/D10/D13/D15/D17 與
   B1 的 M2/M4/M5/M6,每條「注入 → 紅」各貼一段。
   規矩是:**驗收器必須證明它會失敗,只證明會通過不算數。**
3. **遷移結果的數字表**:CONFIRMED / PROVISIONAL / UNCLASSIFIED 各幾條,
   四種 reference kind 各幾條,與 §0.3 的差異(若有,逐項解釋)。
4. **等價閘門**:583 列逐列 mapping 相同的實測輸出。若有不同,逐列列出。
5. **批准工單的三批條數**,以及第 3 批(無可重驗證據)的**確切名單**。
6. **遇到的意外**:任何「規格說 A、實際是 B」的地方。**不要自行裁示,列出來。**
   已知會遇到、不必再回報的兩件:
   - `git log -S` 對衍生/評價調整那 26 條要用 `"名字": DERIVATIVE` 的字面(§B1.1)
   - `core/classify.py` 是 Phase A C2 的規劃檔名,與本單的 `decide()` 有職責重疊
     —— **本單不要建立 `classify.py`**,把重疊列進回報即可

---

## 常見誤區(這些都真的會發生)

| 誤區 | 正解 |
|---|---|
| B1 找到「像人工裁示」的 commit 就升成 CONFIRMED | 鐵則 1:升級只能經 `ratify()`,那是 B1.5。**B1 產出 0 條 CONFIRMED** |
| 把「git log 找得到 commit」當成 human reference | 實測 74/74 全過 = 恆真閘門。判準見 §B1.1 |
| 為了讓可發布數不掉,把批量 commit 算成人工背書 | 鐵則 6。**數字誠實地掉下來是產出** |
| `decide()` 自己造 CONFIRMED | 鐵則 2 / I1。它只能「轉述」已批准的 rule |
| 每筆 CONFIRMED occurrence 都塞一份 human reference | 鐵則 3:人簽在 rule 上,occurrence 引用 rule。D9 就是驗這個 |
| 用 `(cell_key, source_page, row_index)` 當契約 key | 鐵則 4:那是 locator。重抄會位移 |
| `record_fp` 把 source_page 或 rows 放進去 | D13/D14 會紅。擴頁重抄後頁碼會變、列數會變 |
| 重抄後用 `ordinal` 硬對舊 Decision | 用 `record_fp` + `row_fp` 重綁(B0.4 五步) |
| `row_fp` 碰撞時靜靜覆蓋 | D17:必須 raise。今天實測 0 筆碰撞,但那是樣本不是保證 |
| `decide()` 忘了傳 `group` | 「其他」「其他(註)」會分錯桶,等價閘門會紅(§B1.7) |
| 把桶寫回 `facts/` | facts 是原始層,分類永不改寫它 |
| 測試寫進真實 `taxonomy/` `facts/` | 一律寫 tmp,測完還原 |
| 順手建 `core/classify.py` | 那是 C2 的規劃檔名,不在本單。重疊列進回報就好 |
| 做完 B1 順手跑 B1.5 / C3 / B2 | 本單明確停在 B1。B1.5 是使用者本人的動作 |
| 做完 B0 就回報問要不要繼續 | 鐵則 7:一次性回報 |
