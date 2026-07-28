# 施工單 —— B1-fix(批次歸屬修正)+ ratify() 實作

> 給執行者(Sonnet)。上游規格 `docs/plan_phaseB.md`、前一單 `docs/brief_phaseB_B0_B1.md`。
> **衝突時以本單為準,不確定就停下來問,不要自行裁示。**
>
> 本單做三步:**F1(批次歸屬修正)→ F2(GENERIC 證據誠實化)→ F3(實作 `ratify()`)**。
> **做完 F3 就停下來回報。**
>
> **B1.5(實際批准、實際產生 CONFIRMED)是使用者本人的動作,本單不得執行。**
> 本單只把 `ratify()` 這個**工具**做出來並測到它會失敗,**不准拿它去批准任何東西**。
> C3 / B2 / B3 / B4 / B5 都不在本單範圍。

---

## 0. 先讀這段(硬性約束)

### 0.1 絕對不准做

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` `results.py` `build.py` `bridge_v2.py` `bridge_v3.py` `fill.py` `pipeline.py` | 已驗證的底層能力。**唯一合法的重用方式是 `import`** |
| 修改 Phase A 的 `core/` 既有檔(`units.py` `expand_policy.py` `contracts.py` `store.py` `reconcile.py` `cli.py`) | 等價閘門已經綠了,動它就要重跑全部 |
| 修改 `core/decisions.py` 的**既有**函式行為 | B0 的 24 項注入測試綠著。本單只**新增**(見 F3.2),不改既有 |
| 改寫 `facts/` —— **一個 byte 都不准變** | facts 是原始層,分類永遠不得改寫它 |
| **執行 `ratify()` 去批准任何 rule 或 derivation** | 那是 B1.5,使用者本人的動作。本單只做工具與測試 |
| 產生任何 `state == "CONFIRMED"` 的 rule 或 decision **進到真實 `taxonomy/`** | 同上。測試裡在 tmp 造 CONFIRMED 是可以的 |
| 跑 `build.py` / `bridge_v3.py` / 任何 `--write` | 會動到已發布的 `data.json` |
| 修改 `data.json` `snapshots/` `preview/` `anchors/` | 唯讀輸入 |
| 測試寫進真實 `facts/` `taxonomy/` `decisions/` | 一律寫 tmp,用參數注入根目錄。測試後還原 |
| 呼叫任何模型 API | 使用者已定案:程式不呼叫 |
| 「順手」重構、改名、整理、補型別 | 等價閘門會分不出差異來自搬家還是整理 |
| 為了讓測試變綠而放寬測試 | 測試紅了要回報,不是改判準。**唯一例外見 §0.2** |
| 做 C3 / B2 / B3 / B4 / B5 | 不在本單。做完 F3 停 |

### 0.2 本單**明確授權**的兩處變更(不是放寬判準)

前一單的 `test_taxonomy_migration.py` 有兩條斷言會因為 F1 而改變。
**這是修正,不是放寬** —— 因為舊數字本身反映的是一個 bug。逐條說明:

| 測試 | 舊斷言 | 新斷言 | 為什麼這是修正 |
|---|---|---|---|
| M7 批次條數 | `63 / 8 / 3` | **`68 / 12 / 3`** | 舊工單把 5 條 GROUP_SYN + 4 條 GENERIC 印在「第 1 批」的統計裡,`applies_to` 卻收不到它們(見 §1)。修正後 GROUP_SYN 真的進第 1 批(68),GENERIC 移到第 2 批(12) |
| M7b 第 3 批名單 | 政府債券 / 貨幣交換 / 外匯換匯合約 | **不變** | 第 3 批不受影響,**不准動** |

**除了上面這兩格,任何其他測試斷言都不准改。** 改了要回報。
特別是 `test_decide_equiv.py` 的 583 列等價 —— 本單三步**都不應該**改變任何一列的
`mapping`,那條閘門紅了代表你動到了不該動的東西。

### 0.25 `docs/plan_local_first.md` 不影響本單

`docs/` 裡有一份 2026-07-28 的 local-first 轉向計畫(產品改成本機工作台,
不再以 GitHub Pages 為目標)。**那份計畫改的是 C3 / C4 與發布層,與本單無關。**

本單動的是 `core/migrate_syn.py` `core/ratify.py` `taxonomy/` 與測試 ——
沒有一項碰到路徑、UI、發布層。**看到那份計畫不要改變本單的做法,
也不要開始做任何工作台/伺服器/UI 的東西。**

### 0.3 環境

```bash
source .venv/bin/activate
```

沒有 pytest。測試是可執行腳本,`python3 test_x.py`,exit 0 = 綠。

`test_e2_equiv.py` 跑約 **60 秒**、`test_build.py` 約 **460 秒**。
**本單不必跑 `test_build.py`** —— 不碰發布層。`test_e2_equiv.py` 要跑。

### 0.4 已量到的基準(2026-07-28 實測,不要重新推導,直接用)

```
taxonomy/rules.json    83 條 = name 74 / group 5 / generic 4,全部 PROVISIONAL
taxonomy/derivations.json   []
derivation applies_to  63 條(全是 scope=="name")
不在 applies_to 的 rule 20 條 = 11 條 name(第 2、3 批)+ 5 group + 4 generic

5 條 GROUP_SYN 的 propose 結果(全部一致,mapping 都是「衍生」):
    衍生金融資產 / 衍生金融負債 / 衍生工具 / 衍生性金融商品 / 衍生金融工具
        → rules.propose 全回 ('衍生', 'BUCKET_RULES 關鍵字「衍生」')
    其中「衍生金融工具」另有 arithmetic 證據(中信 202504 段合計 = 附註)

4 條 GENERIC 的現況:
    其他 / 其他(註) / 其他(註一) / 其他項目
        mapping = None(通稱不帶桶)、reference kind = "rule"、**recheck = None**

rules.audit(config.BUCKET_RULES)  →  []   (無夾帶詞)
config.BUCKET_RULES 的 sha256      →  b9754a75e0c948e731b22c45794ce69309c6550fc917329160a11974b8fd54e8

受影響面(給 F1 的動機,不必重量):
    含「其他」通稱列的格數           15 / 36
    真的靠 GROUP_SYN 段落才分得出桶   7 / 36
```

---

## 1. 為什麼有這一單(背景,讀完再動手)

前一單 B0 + B1 已完成且全綠。驗收時量到**一個工單自己的矛盾**:

`out/ratify_worklist.md` 的「統計」段印:

```
第 1 批 (rule 可重驗): 63 條 SYN + 5 條 GROUP_SYN + 4 條 GENERIC
```

但同一份工單裡待批准的 Derivation,`applies_to` **只列 63 個 rule_id**,
5 條 GROUP_SYN 與 4 條 GENERIC 一個都不在。

根因在 `core/migrate_syn.py`:

- [:482](../core/migrate_syn.py) 把 group/generic rule 標成 `_worklist_batch = 1`
- [:399](../core/migrate_syn.py) 的 `batch1_rule_ids.append(...)` **只在 `scope == "name"` 時執行**

於是工單「顯示成第 1 批」、`applies_to`「收不到」。

**後果(不是今天發作,是 B5 發作)**:依 `core/decisions.py` 的降級規則 ③
(`rule_id` 不在 `derivation.applies_to` → 降回 PROVISIONAL),
使用者在 B1.5 批准這條 derivation 之後,那 9 條**永遠停在 PROVISIONAL 且沒有任何路徑**。
等 B5 開 I5(全格 CONFIRMED 才可發布),15/36 格會上不了架,其中 7 格是**真的**
只能靠 GROUP_SYN 段落才分得出桶的。

**這不是「數字誠實地掉下來」**(那指的是證據不足所以不敢發),
**是工單漏了一批** —— 證據明明在,只是沒被收進 `applies_to`。兩者要分清楚。

> ⚠️ **趁現在改是免費的,B1.5 之後就不是。** `derivations.json` 還是空的、
> `approved_by` 還是 null,沒有任何東西被批准過,所以直接重新產生即可。
> 一旦使用者批准過 `deriv:BUCKET_RULES-keyword-v1`,再改 `applies_to` 就等於
> **竄改人簽過的東西**,那時只能發 `-v2` 並讓 v1 涵蓋的 rule 走降級流程。

---

## 2. 這一單的判斷依據(使用者已裁示,照做,不要重新論證)

### 2.1 5 條 GROUP_SYN → **併進第 1 批的同一條 Derivation**

理由:它們**完全符合現有的 predicate**,不需要任何新機制。
`rules.propose(norm(段落名))[0] == mapping` 對這 5 條逐條成立(§0.4 實測),
每條也都已經帶著可重跑的 recheck。加進 `applies_to` 就結束了。

**不准**為它們另開一條 derivation —— predicate 一模一樣,分兩條只是多一個要維護的東西。

### 2.2 4 條 GENERIC → **移到第 2 批,逐條 ratify**

理由要講清楚,因為這條**不是**「順手歸類」:

GENERIC 的 `mapping` 是 `None`(通稱不自帶桶),而 derivation 的 predicate 是
`propose(name)[0] == mapping`。`propose("其他")` 回 `'其他'`,`mapping` 是 `None`
—— **predicate 對它們根本不成立**,硬塞進 `applies_to` 會讓那條 derivation 的
判定式當場變成假的。

更根本的是:GENERIC 主張的**不是**「『其他』屬於『其他』桶」,而是
**「『其他』這個名字是通稱,不自帶會計意義,要靠所在段落決定」**。
那是判斷,不是 `BUCKET_RULES` 的關鍵字比對推得出來的。`buckets.py` 自己的註解
已經說了這件事:

> 收在這裡而不是塞進 norm():norm 是零判斷的機械正規化,「哪些後綴是註腳」
> 是判斷,判斷一律留在判斷層。

所以它們該走 (a) 路徑逐條 ratify,由人簽一句「我確認這 4 個名字是通稱」。只有 4 條,成本很低。

### 2.3 GENERIC 的 reference 現在**標得不誠實**,要修

現況:`kind = "rule"`、`recheck = None`。

`kind="rule"` 在本專案的語意是「可機械重驗」,但 `recheck` 是 `None` —— 它重驗不了。
這正是 `docs/plan_phaseB.md` §2.3 要避免的:看起來是硬證據,實際上沒有任何東西會叫。
留著它,`test_taxonomy_migration.py` 的 M3(每條 rule/synonym/arithmetic reference
都能重跑)就是一個**恆真閘門** —— 它會因為「沒有 recheck 可跑」而通過。

修法見 F2。**不准**用「補一個假的 recheck」來修(例如寫
`propose('其他')[0] == '其他'`)—— 那個斷言是真的,但它證明的**不是**
「其他是通稱」這件主張,是拿一條會通過的斷言去掩護一個沒被驗證的判斷。

---

## 步驟 F1 —— 批次歸屬修正

**目的**:讓 `applies_to` 與工單的統計說同一件事。
**這一步零分類行為改變** —— 583 列的 `mapping` 一列都不准變。

### F1.1 改 `core/migrate_syn.py`

只改批次歸屬的邏輯,**不改任何 reference 的產生方式**:

```
scope == "name"      → 維持現況(63 / 8 / 3 的分法不動)
scope == "group"     → 進 batch1_rule_ids(因此進 derivation.applies_to)
scope == "generic"   → 進 batch2(逐條 ratify),**不得進 applies_to**
```

### F1.2 重新產生產物

```bash
python3 -m core.migrate_syn        # 或該檔既有的 main() 進入點,照它原本的跑法
```

產出必須是:

```
taxonomy/rules.json        83 條,**全部 state=PROVISIONAL**(CONFIRMED 仍然 0)
taxonomy/derivations.json  仍然是 []          ← **本單不得寫入任何一條**
out/ratify_worklist.md     第 1 批 68 / 第 2 批 12 / 第 3 批 3
                           derivation.applies_to = 68 個 rule_id,逐一列出
```

### F1.3 加兩條**會抓到這個 bug** 的不變式

加進 `test_taxonomy_migration.py`(新增,不動既有斷言除了 §0.2 那兩格):

| # | 命題 | 注入什麼 |
|---|---|---|
| M8 | **工單宣稱是第 1 批的 rule,必須全部出現在 derivation 的 `applies_to` 裡** | 從 `applies_to` 拿掉一條第 1 批的 rule_id → **必須紅** |
| M9 | **`scope=="generic"` 的 rule 不得出現在任何 derivation 的 `applies_to` 裡** | 塞一條 generic rule 進 `applies_to` → **必須紅** |

> M8 是本單的重點產出。這個 bug 之所以躲過前一單的 7 條測試,是因為**沒有任何一條
> 檢查「工單說的」與「derivation 收的」是否一致**。補上它,這一類 bug 才不會再來一次。

---

## 步驟 F2 —— GENERIC 證據誠實化

**目的**:讓「沒被機械驗證的判斷」在資料裡看得出來是沒被驗證的。

### F2.1 改 4 條 GENERIC rule 的 reference

在 `core/migrate_syn.py` 產生 GENERIC rule 時:

- reference 的 `kind` 從 `"rule"` 改成能表達「這是待人工確認的判斷」的標記。
  `core/decisions.py` 的 `REFERENCE_KINDS` 是
  `("human", "rule", "synonym", "arithmetic", "prior_year", "group")` ——
  **不准為此新增 kind**(那要改 B0 已凍結的常數)。
  用既有的 `"group"` kind,`detail` 寫清楚主張是什麼(「『其他』是通稱,
  桶由所在段落 GROUP_SYN 決定」)、`recheck` 維持 `None`。
- 若你認為 `"group"` 這個 kind 語意不合,**停下來問使用者**,不要自己挑一個或新增。

### F2.2 讓 M3 不再是恆真閘門

`test_taxonomy_migration.py` 的 M3 現在印「95 rechecks passed, **0 skipped**」。
改成:**明確數出並印出 `recheck is None` 的 reference 有幾條**,
且斷言「`kind` 在 `("rule","synonym","arithmetic")` 的 reference **必須**有 recheck」。

| # | 命題 | 注入什麼 |
|---|---|---|
| M10 | `kind` ∈ {rule, synonym, arithmetic} 的 reference 必須有非空 recheck | 造一條 `kind="rule"` 且 `recheck=None` 的 reference → **必須紅** |

---

## 步驟 F3 —— 實作 `ratify()`

**目的**:把 B1.5 的**工具**做出來,並證明它擋得住該擋的東西。
**本單不得用它批准任何東西。**

### F3.1 放哪裡

**新檔 `core/ratify.py`。**

**不准**寫進 `core/decisions.py` —— 那支是零 IO 的純函數模組(B0 的驗收條件之一),
而 `ratify()` 要讀寫 `taxonomy/`。維持 Ring 分層,跟 `core/migrate_syn.py` 同一層。

### F3.2 介面

```python
def ratify_rule(rule_id, approved_by, approved_at, reason,
                taxonomy_dir="taxonomy") -> dict:
    """路徑 (a):逐條批准一條 taxonomy rule。

    寫入 taxonomy/rules.json:該 rule 加一條 kind=="human" 的 reference
    (detail 記 reason),state 升為 CONFIRMED,approved_by/at 填入。

    **只吃人工輸入。** approved_by / reason 為空 → raise,不准給預設值。
    """


def ratify_derivation(derivation, approved_by, approved_at, reason,
                      taxonomy_dir="taxonomy") -> dict:
    """路徑 (b):批准一條 Derivation,連帶升級它 applies_to 涵蓋的 rule。

    1. derivation.references 必須含 ≥1 條 kind=="human"(I3b 的來源)——
       由本函式依 approved_by/reason 建立,**不准接受呼叫端傳進來的 human ref**
    2. 寫進 taxonomy/derivations.json
    3. 對 applies_to 裡的每一條 rule:**recheck 跑起來成立**才升 CONFIRMED,
       不成立的**留在 PROVISIONAL 並列出來**,不准靜靜跳過
    4. 升級後立刻重跑 core.decisions.stale_confirmations(),
       **有任何一條 stale 就 raise 並回滾**,不准寫出一個當場就該降級的狀態
    """
```

### F3.3 硬性規則(每一條都要有注入測試)

| 規則 | 說明 |
|---|---|
| `ratify()` 是**唯一**能產生 CONFIRMED 的入口 | `migrate_syn` / `decide()` 都不准產生 |
| 沒有 human 證據不准升 CONFIRMED | 違反 I3b,`validate_rule` 要擋 |
| `bucket_rules_revision` 必須是**批准當下**算的,不准沿用提案檔裡的舊值 | 提案是幾天前產生的,`BUCKET_RULES` 可能已經改了 |
| 升級後 `stale_confirmations()` 必須為空 | 否則就是寫出一個自相矛盾的狀態 |
| `applies_to` 裡 recheck 不過的 rule → 留 PROVISIONAL 並**大聲列出** | 不准為了「批准成功」而忽略它 |
| generic rule(mapping is None)出現在 `applies_to` → **raise** | §2.2 的理由,predicate 對它不成立 |
| 全部寫入必須可由 `git diff` 審 | 這是本專案的人審介面 |

### F3.4 `test_ratify.py`(新檔)

**一律寫 tmp `taxonomy_dir`,測完還原。真實 `taxonomy/` 在本單全程唯讀。**

| # | 命題 | 注入什麼 |
|---|---|---|
| R1 | `ratify_rule` 正常路徑 → rule 變 CONFIRMED 且帶 human reference | — |
| R2 | `ratify_rule` 的 `approved_by` 為空 → **raise** | 給空字串 → **必須紅** |
| R3 | `ratify_rule` 的 `reason` 為空 → **raise** | 同上 |
| R4 | `ratify_derivation` 正常路徑 → applies_to 涵蓋的 rule 全變 CONFIRMED | — |
| R5 | derivation 無 human reference → 產出的 CONFIRMED rule 被 `validate_rule` 拒絕(I3b) | 讓它不建 human ref → **必須紅** |
| R6 | `applies_to` 裡某條 rule 的 recheck 不成立 → 該條**留 PROVISIONAL** 且被列出 | 讓它一起升 CONFIRMED → **必須紅** |
| R7 | `applies_to` 含 generic rule(mapping is None)→ **raise** | 讓它靜靜通過 → **必須紅** |
| R8 | 批准後改 `config.BUCKET_RULES` 文字 → `stale_confirmations` 回報①並降級 | 忽略 revision → **必須紅** |
| R9 | 批准當下用**提案檔裡的舊 revision** 而非現算值 → **必須被擋** | 沿用舊值 → **必須紅** |
| R10 | `ratify` 全程不碰 `facts/` | 跑完 `git diff facts/` 為空 |
| R11 | 同一條 rule 重複 ratify → 不得產生重複的 human reference | 無條件 append → **必須紅** |

---

## 驗收

### F1

```
[ ] out/ratify_worklist.md 三批 = 68 / 12 / 3
[ ] derivation.applies_to = 68 個 rule_id,含 5 條 group,**不含任何 generic**
[ ] taxonomy/rules.json 83 條,**全部 PROVISIONAL**(CONFIRMED 仍為 0)
[ ] taxonomy/derivations.json 仍為 []
[ ] M8 / M9 綠,各貼一段「注入 → 紅」
```

### F2

```
[ ] 4 條 GENERIC 的 reference 不再標成無 recheck 的 "rule"
[ ] M3 印出 recheck is None 的條數(不再是 0 skipped 的恆真閘門)
[ ] M10 綠,貼一段「注入 → 紅」
```

### F3

```
[ ] core/ratify.py 存在
[ ] test_ratify.py 綠,R2/R3/R5/R6/R7/R8/R9/R11 各貼一段「注入 → 紅」
[ ] **真實 taxonomy/ 零變更**:derivations.json 仍是 []、rules.json 仍 0 條 CONFIRMED
[ ] git diff facts/ 為空
```

### 全體

```
[ ] test_decide_equiv.py 綠:583 列逐列 mapping 相同(這一單不該改變任何一列)
[ ] test_decisions.py 綠(B0 的 24 項,一項都不准紅)
[ ] 九支既有 + Phase A 六支全綠
[ ] git status:只有新增檔案 + core/migrate_syn.py 與 test_taxonomy_migration.py 的修改
```

---

## 回報格式

**一次性回報。** F1 / F2 / F3 全部做完、**且跑完下面這張總表**之後,才回報一次。

```bash
# ① 本單新增/修改的測試
python3 test_taxonomy_migration.py   # M2 M4 M5 M6 + 新增 M8 M9 M10
python3 test_ratify.py               # R2 R3 R5 R6 R7 R8 R9 R11
python3 test_decide_equiv.py         # 583 列逐列相同

# ② B0 回歸
python3 test_decisions.py            # 24 項

# ③ 回歸(九支既有)
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ④ 回歸(Phase A 六支;test_e2_equiv.py 約 60 秒,要跑)
for t in test_units.py test_expand_policy.py test_contracts.py \
         test_e2_equiv.py test_ring.py test_rulings.py; do
  printf "%-20s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ⑤ 唯讀證明
git diff --stat facts/ buckets.py config.py rules.py synonyms.py \
                core/units.py core/expand_policy.py core/contracts.py \
                core/store.py core/reconcile.py core/decisions.py
python3 -c "import json; d=json.load(open('taxonomy/derivations.json')); \
            r=json.load(open('taxonomy/rules.json')); \
            print('derivations:', d); \
            print('CONFIRMED:', sum(1 for x in r if x['state']=='CONFIRMED'))"
# 必須印出 derivations: []  與  CONFIRMED: 0
```

**任何一項紅了,不要修判準,回報它。**

### 回報這五段

1. **每一步的驗收 checklist**,逐條打勾或說明為什麼沒打勾。
2. **注入測試的實測輸出** —— M8/M9/M10 與 R2/R3/R5/R6/R7/R8/R9/R11,
   每條「注入 → 紅」各貼一段。**驗收器必須證明它會失敗,只證明會通過不算數。**
3. **F1 前後的數字對照**:三批條數、`applies_to` 條數、各 state 條數。
4. **等價閘門**:583 列逐列 mapping 相同的實測輸出。**若有任何一列不同,列出來並停下** ——
   本單不該改變任何分類結果,不同就代表動到了不該動的東西。
5. **遇到的意外**:任何「規格說 A、實際是 B」的地方。**不要自行裁示,列出來。**
   特別是 §F2.1 的 reference kind 選擇 —— 覺得不合就停下來問。

---

## B1.5 使用者操作說明(**執行者不得執行,只需確認指令跑得動**)

本單交付後,使用者會自己跑類似這樣的東西(確切寫法由 `core/ratify.py` 的介面決定):

```
第 1 批  批准 deriv:BUCKET_RULES-keyword-v1  → 68 條 rule 轉 CONFIRMED
第 2 批  逐條 ratify 12 條(8 條 SYN 的 arithmetic/human + 4 條 GENERIC 的通稱判斷)
第 3 批  逐條決定 3 條(政府債券 / 貨幣交換 / 外匯換匯合約),
        問不出來就**留在 PROVISIONAL**
```

**執行者要做的只有一件事**:在回報裡寫清楚使用者該怎麼下這些指令(參數、順序、
跑完怎麼驗)。**不准替他跑,不准先幫他填 approved_by。**

---

## 常見誤區(這些都真的會發生)

| 誤區 | 正解 |
|---|---|
| 「順手」把 4 條 GENERIC 也塞進 `applies_to`,湊成 72 | §2.2:它們的 `mapping` 是 `None`,derivation 的 predicate 對它們不成立。M9 會紅 |
| 為 GENERIC 補一個 `propose('其他')[0] == '其他'` 的 recheck | §2.3:那個斷言是真的,但它證明的不是「其他是通稱」那個主張。是拿會過的斷言掩護沒驗的判斷 |
| 為 5 條 GROUP_SYN 另開一條 derivation | §2.1:predicate 一模一樣,分兩條只是多一個要維護的東西 |
| 本單順手把 `ratify()` 拿去批准,好讓數字回到 25 | 那是 B1.5,使用者本人的動作。本單產出仍是 **CONFIRMED 0 條** |
| `ratify()` 寫進 `core/decisions.py` | F3.1:那支是零 IO 純函數(B0 驗收條件),ratify 要寫 taxonomy/ |
| 批准時沿用提案檔裡的 `bucket_rules_revision` | F3.3:提案是幾天前產生的,要用批准當下現算的值。R9 驗這個 |
| `applies_to` 裡 recheck 不過的 rule 一起升 CONFIRMED | F3.2 第 3 點:留 PROVISIONAL 並列出來。R6 驗這個 |
| 因為 M7 數字變了就順手改別的測試斷言 | §0.2 只授權 M7 那一格。其他都不准動,動了要回報 |
| 583 列等價紅了就去調 decide() | 本單不該改變任何分類結果。紅了是你動到不該動的,停下來回報 |
| 測試寫進真實 `taxonomy/` | 一律 tmp,真實 taxonomy 在本單全程唯讀 |
| 做完 F3 順手跑 B1.5 / C3 / B2 | 本單明確停在 F3 |
| 做完 F1 就回報問要不要繼續 | 一次性回報 |
