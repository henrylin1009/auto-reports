# 施工單 —— C3-a:`core/ingest.py`

> 給執行者(Sonnet)。上游規格:`docs/plan_clean_core.md` §2.4/§2.5(E5、C3 閘門)、
> `docs/plan_local_first.md` §4.1(C3 的新定義)。
> **衝突時以本單為準,不確定就停下來問,不要自行裁示。**
>
> 本單分兩步:**A1(零行為搬移)→ A2(接上擴頁白名單,有行為改變)**。
> **做完 A2 就停下來回報。**
>
> **本單不做 `core/jobs.py`、不做工作台、不做伺服器、不做 UI、不做 workspace/chdir。**
> 那些是 C3-b 與之後的事。C4 / B2–B5 也都不在本單。

---

## 0. 先讀這段(硬性約束)

### 0.1 絕對不准做

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` `results.py` `build.py` `bridge_v2.py` `bridge_v3.py` `transcriber.py` | 已驗證的底層能力。**唯一合法的重用方式是 `import`** |
| 修改 `fill.py` / `pipeline.py` | **本單是「搬出來」,不是「改掉」。** 兩支要留在原地繼續能跑,退場是 C5 的事 |
| 修改 `core/` 既有檔(`units` `expand_policy` `contracts` `store` `reconcile` `cli` `decisions` `ratify` `recheck` `migrate_syn`) | 閘門都綠著。**`expand_policy.py` 特別注意:本單是「接上它」,不是「改它」** |
| 改寫 `facts/` —— **一個 byte 都不准變** | facts 是原始層。本單全程 `git diff facts/` 必須為空 |
| 修改 `taxonomy/` | B1.5 已批准(80 CONFIRMED / 3 PROVISIONAL),動它等於竄改人簽過的東西 |
| 跑 `build.py` / `bridge_v3.py` / 任何 `--write` | 會動到已發布的 `data.json` |
| 呼叫任何模型 API | 使用者已定案(甲案):讀表永遠是外部 agent 的工作 |
| 真的去抄新的格(寫進真實 `facts/`) | 見 §4:那一步是使用者/agent 的工,本單只負責讓它跑得起來 |
| 「順手」重構、改名、整理 | 等價閘門會分不出差異來自搬家還是整理 |
| 為了讓測試變綠而放寬測試 | 測試紅了要回報,不是改判準 |
| 做 `core/jobs.py` / 工作台 / UI / workspace / chdir | 那是 C3-b。**看到 `plan_local_first.md` 不要提前做** |

### 0.2 環境

```bash
source .venv/bin/activate
```

沒有 pytest。測試是可執行腳本,`python3 test_x.py`,exit 0 = 綠。
`test_e2_equiv.py` 約 60 秒要跑;`test_build.py` 約 460 秒,**本單不必跑**。

**現有 15 支測試(每一步結束都要全綠)**:

```bash
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py test_wide.py \
         test_locate.py test_gap.py test_drive.py test_pipeline.py \
         test_units.py test_expand_policy.py test_contracts.py test_ring.py \
         test_rulings.py test_decisions.py test_ratify.py \
         test_taxonomy_migration.py test_decide_equiv.py test_e2_equiv.py; do
  printf "%-28s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done
```

### 0.3 現況盤點(2026-07-28 實測,不要重新推導)

```
fill.py 的四條出口(cmd_submit,fill.py:264-357):
    PASS     verify 全過        → 寫 facts/,刪 pending
    BLOCKED  _taxonomy_gap() 有料 → 寫 work/blocked/ + work/proposals.jsonl,**不擴頁**
    RETRY    其餘失敗           → level+1、loc.expand()、retries+1、重寫 pending
    REJECT   level > MAX_LEVEL(2) 或擴不出新頁 → 寫 work/rejected/

pipeline.py     MAX_LEVEL = 2;run(doc,cls) 是 generator;drive(doc,cls,transcriber) 包它
transcriber.py  replay(cells) 重播事實庫(E5 用);submitted(p) 讀 agent 寫的 JSON

core/expand_policy.py  **目前沒有任何production 程式碼 import 它**
                       (實測:只有 test_expand_policy.py 用到)
                       → 「擴頁白名單上線」是本單 A2 的真實工作,不是既成事實
```

---

## 1. 兩個必須先講清楚的坑

### 1.1 ⚠️ C3 **不是**單純的零行為搬移 —— 它包含一個真的行為改變

`plan_clean_core.md` §2.5 的 C3 閘門是
`E5 綠 ∧ 3 個新格實跑 ∧ 四條出口實跑 ∧ **T-R4 綠(擴頁白名單上線)**`,
而 §2.6 明說「C3 **會**帶進 R4 的擴頁白名單(那是使用者裁示的規則,不能等)」。

但「搬家」與「改行為」混在一起做,閘門一紅就分不出是搬壞的還是改壞的。
**所以本單硬性拆成兩步,中間要各自全綠**:

```
A1  零行為搬移   fill.py 的 ingest/routing → core/ingest.py
                 行為**逐字相同**,四條出口的判斷與訊息一字不差
                 閘門:E5 綠 ∧ 15 支測試綠
                 ↓ 這裡要停下來確認全綠,再做 A2
A2  接上白名單   core/ingest.py 改用 core.expand_policy 決定要不要擴頁
                 **這一步會改變行為** —— 要把改變量測出來、寫進回報
                 閘門:T-R4 綠 ∧ 四條出口實跑 ∧ 改變量逐格解釋
```

**A1 沒全綠不准做 A2。**

### 1.2 ⚠️ `verify()` 的回傳鍵是**顯示字串**,不能拿去比對

`transcribe.verify()` 回傳的 `res` 長這樣(實測 `transcribe.py:360-374`):

```python
{"①②列相加@p35": None, "④合計==錨@p35": "...", "⑤列皆可分桶@p35": "...",
 "⑥逐欄合計@p35": None, "③雙表互對": None}
```

鍵裡**嵌了頁碼**,而且是給人看的顯示字串。
但 `core/expand_policy.py` 的 `TRIGGERS` 用的是**結構化檢查名**:

```python
TRIGGERS = {"source", "check_identity", "check_anchor", "check_col_totals"}
NEVER    = {"check_buckets", "check_cross"}
```

而 `expand_policy` 自己的註解寫得很清楚:

> 判準是「哪一道檢查失敗」,**不是比對錯誤訊息字串**。
> (`fill._taxonomy_gap` 已經踩過訊息比對的坑:同一個根因會在第 3 道長出第二個症狀。)

**所以 A2 不准用字串比對 `res` 的鍵去推「哪一道失敗」。** 那正是這份設計要防的事。

**正確做法**:`core/ingest.py` 直接 `import transcribe`,呼叫個別檢查函式
(`transcribe.check_identity` / `check_anchor` / `check_buckets` / `check_col_totals` /
`check_cross`),自己組出結構化的 `{檢查名: 失敗訊息 or None}`。
`source` 那一項由 ingest 自己判(`source_page` 在不在候選頁集合內)。

⚠️ **兩份結果必須一致**:結構化的那份與 `transcribe.verify()` 的 pass/fail 結論
不得矛盾。要寫一條斷言檢查它們同進同出(見 §3 的 I2)。
**若發現不一致,停下來回報,不要自己挑一邊。**

---

## 步驟 A1 —— 零行為搬移

### A1.1 `core/ingest.py`(新檔)

把 `fill.cmd_submit` 的**判斷與路由**搬進來,**行為逐字相同**。

建議形狀(可依實作調整,但職責分界不准變):

```python
def classify_outcome(recs, loc, level, pages, retries) -> dict:
    """→ {outcome: "PASS"|"BLOCKED"|"RETRY"|"REJECT", ...}

    **純判斷,不寫任何檔案。** 這是本單最重要的分界:
    「決定要走哪條出口」與「把檔案寫到哪裡」拆開,後者才是 I/O。
    """


def apply_outcome(outcome, ...) -> None:
    """把 classify_outcome 的結論落地(寫 facts/ / blocked/ / rejected/ / pending)。"""
```

**硬性要求**:

1. **`fill.py` 保持能跑。** 本單不改它 —— `core/ingest.py` 是**平行**的第二個實作,
   靠 E5 證明兩者等價。`fill.py` 的退場是 C5。
2. **訊息逐字相同。** 四條出口印出來的字(`PASS 已歸檔進 facts/...`、
   `BLOCKED 這格卡在**分類表缺口**...`、`RETRY 沒過:...`、`REJECT 擴張到上限...`)
   一字不准變。理由見 `plan_clean_core.md` §2.4:
   > E2 的「訊息逐字相同」不是潔癖 —— 那些訊息是拒收的證據,
   > 也是 `/fill` skill 明令 agent 照抄的東西。訊息漂移 = 護欄行為改變。
3. **`MAX_LEVEL` 從 `pipeline.MAX_LEVEL` 讀,不准另寫一份 `2`。**
4. **不准在搬移時「順手修」** `_taxonomy_gap` 回 `None` 就落到擴頁那個已知缺陷
   (`plan_phaseB.md` M-B6)。**那是 A2 的工作**,A1 要逐字保留現有行為。

### A1.2 `test_ingest_equiv.py`(新檔)—— E5 等價閘門

```
對 facts/ 的 36 格走 transcriber.replay:
    old = fill.cmd_submit 的判斷結果
    new = core.ingest.classify_outcome 的判斷結果
斷言:36/36 outcome 相同、訊息逐字相同、level 相同
```

⚠️ **一律寫 tmp 目錄。** 測試不准碰真實 `facts/` `work/` `taxonomy/` ——
用參數注入根目錄或 `tempfile.mkdtemp()`,測完還原。
`plan_clean_core.md` §2.4 的 E5 判準原文:

> `core.ingest` 走 `transcriber.replay` | 36/36 PASS、rows 逐列相同、level 相同;
> **四條出口各一個合成案例**

四條出口的合成案例(A1 就要寫,A2 會再用一次):

| 出口 | 怎麼合成 |
|---|---|
| PASS | 拿一格真實 record 原封不動送進去 |
| BLOCKED | 把某列改成 taxonomy 認不得、但 `rules.propose()` 提得出桶的名字 |
| RETRY | 把 `printed_total` 改掉,讓 ①② 或 ④ 失敗,且 level < MAX_LEVEL |
| REJECT | 同 RETRY,但 level 已達 MAX_LEVEL |

### A1.3 A1 的驗收

```
[ ] core/ingest.py 存在,判斷(classify_outcome)與落地(apply_outcome)分開
[ ] test_ingest_equiv.py 綠:36/36 outcome 相同、訊息逐字相同
[ ] 四條出口各一個合成案例,各自走到正確出口
[ ] fill.py / pipeline.py **零修改**(git diff 為空)
[ ] facts/ 零變更、taxonomy/ 零變更
[ ] 15 支既有測試全綠
```

**A1 全綠之前不准開始 A2。**

---

## 步驟 A2 —— 接上擴頁白名單(T-R4)

### A2.1 要做什麼

`core/ingest.py` 決定「要不要擴頁 / 要不要消耗重試預算」時,
**一律呼叫 `core.expand_policy.may_expand()` 與 `consumes_budget()`**,
不准自己另寫一份判斷。

```python
from core import expand_policy

may, why = expand_policy.may_expand(failed_check_names)
if not may:
    # 不擴頁、**不消耗重試預算**,走 review 出口
```

`failed_check_names` 是 §1.2 說的**結構化檢查名集合**,不是訊息字串。

### A2.2 這一步的行為改變(要量出來,不要猜)

現行 `fill.cmd_submit` 的邏輯是:`_taxonomy_gap()` 有料才 BLOCKED,
**其餘一律 level+1 擴頁**。而 `_taxonomy_gap()` 在 `rules.propose()` 提不出桶時回 `None`
→ 落回擴頁(`plan_phaseB.md` M-B6 記載的玉山 5 格就卡在這裡)。

接上白名單之後:**只有 `source` / `check_identity` / `check_anchor` /
`check_col_totals` 失敗才擴頁**;`check_buckets`(⑤)與 `check_cross`(③)
失敗一律不擴、不消耗預算。

**回報必須包含**:對 36 格重播,A1 與 A2 的 outcome **逐格對照**,
不同的逐格列出並解釋(哪一格、原本走哪條出口、現在走哪條、因為哪一道檢查)。

⚠️ **這裡數字變了是產出,不是失敗。** 但**每一個變化都要解釋得出來**;
解釋不出來的變化 = 你搬錯了,停下來回報。

### A2.3 `test_ingest_policy.py`(新檔)

| # | 命題 | 注入什麼 |
|---|---|---|
| T1 | 只有 `check_buckets` 失敗 → **不擴頁、retries 不增加** | 讓它擴頁 → **必須紅** |
| T2 | 只有 `check_cross` 失敗 → **不擴頁、retries 不增加** | 同上 |
| T3 | `check_identity` 失敗 → 擴頁、retries +1 | 讓它不擴 → **必須紅** |
| T4 | `check_identity` + `check_buckets` 同時失敗 → 擴頁,**但理由字串只提 ①,不提 ⑤** | 理由提到 ⑤ → **必須紅** |
| T5 | ingest **不准**自己重寫一份觸發判斷 | 全域搜尋:`core/ingest.py` 裡不得出現寫死的檢查名集合;唯一來源是 `expand_policy` |
| T6 | §1.2 的一致性:結構化檢查結果與 `transcribe.verify()` 的 pass/fail 結論同進同出 | 造一個矛盾 → **必須紅** |

### A2.4 A2 的驗收

```
[ ] core/ingest.py import core.expand_policy,**沒有第二份觸發判斷**
[ ] test_ingest_policy.py 綠,T1/T2/T3/T4/T6「注入 → 紅」各貼一段
[ ] A1 vs A2 的 36 格 outcome 逐格對照表,差異逐格解釋
[ ] fill.py / pipeline.py 仍然零修改、仍然能跑
[ ] facts/ 零變更、taxonomy/ 零變更
[ ] 15 支既有測試 + test_ingest_equiv.py 全綠
```

---

## 3. 三條不變式(每條都要有注入測試)

| # | 不變式 | 注入什麼 |
|---|---|---|
| **I1** | **分類未知永不觸發 expand、永不消耗重試預算、永不丟棄 raw facts** | 讓 `check_buckets` 失敗觸發擴頁 → 必須紅(= T1) |
| **I2** | 結構化檢查結果與 `transcribe.verify()` 的結論**同進同出** | 造矛盾 → 必須紅(= T6) |
| **I3** | 擴頁觸發的**唯一來源**是 `core.expand_policy` | ingest 內出現第二份名單 → 必須紅(= T5) |

---

## 4. 本單**不做**的那一項閘門(要在回報裡講清楚)

`plan_clean_core.md` §2.5 的 C3 閘門含 **「3 個新格實跑(非重播)」**。

**那一項本單做不到,也不准假裝做到。** 理由:讀表是外部 Claude Code agent 的工作
(使用者已裁示甲案,`fill.py:19` 也寫死「不准呼叫任何模型 API」),
需要真的抓 PDF、真的抄一格、真的寫進 `facts/` —— 那是另一種工作階段。

**執行者要做的是**:
1. 確認 `core/ingest.py` 具備被那樣使用的介面(能吃 agent 寫的 rows JSON,
   走完四條出口),並在回報裡寫出**確切的操作步驟**給使用者。
2. **不要**為了讓這條閘門看起來綠而拿重播冒充實跑。
   重播是 E5,實跑是另一回事,**兩者不准混為一談**。

---

## 5. 回報格式

**一次性回報。** A1 + A2 全部做完、且跑完下面這張總表之後,才回報一次。

```bash
# ① 本單新增
python3 test_ingest_equiv.py         # E5:36/36 等價 + 四條出口
python3 test_ingest_policy.py        # T1–T6

# ② 回歸(15 支,一支都不准紅;test_e2_equiv.py 約 60 秒)
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py test_wide.py \
         test_locate.py test_gap.py test_drive.py test_pipeline.py \
         test_units.py test_expand_policy.py test_contracts.py test_ring.py \
         test_rulings.py test_decisions.py test_ratify.py \
         test_taxonomy_migration.py test_decide_equiv.py test_e2_equiv.py; do
  printf "%-28s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ③ 唯讀證明
git diff --stat facts/ taxonomy/ fill.py pipeline.py transcribe.py locate.py \
                core/expand_policy.py core/decisions.py core/ratify.py
python3 -c "import json; r=json.load(open('taxonomy/rules.json')); \
            print('CONFIRMED:', sum(1 for x in r if x['state']=='CONFIRMED'))"
# 必須印出 CONFIRMED: 80(B1.5 的批准沒被動到)
```

**任何一項紅了,不要修判準,回報它。**

### 回報這六段

1. **A1 / A2 各自的驗收 checklist**,逐條打勾或說明為什麼沒打勾。
2. **E5 實測輸出**:36/36 outcome 相同、訊息逐字相同的證據。
3. **注入測試輸出**:T1/T2/T3/T4/T6 每條「注入 → 紅」各貼一段。
   **驗收器必須證明它會失敗,只證明會通過不算數。**
4. **A1 vs A2 的 36 格逐格對照**:哪幾格的出口變了、為什麼變、是哪一道檢查造成的。
5. **§4 那條做不到的閘門**:明講「3 個新格實跑」沒做,並附上使用者要怎麼做的步驟。
6. **遇到的意外**:任何「規格說 A、實際是 B」的地方。**不要自行裁示,列出來。**

---

## 6. 常見誤區

| 誤區 | 正解 |
|---|---|
| A1 和 A2 一起做 | §1.1:混在一起,閘門紅了分不出是搬壞還是改壞。A1 全綠才做 A2 |
| 用字串比對 `verify()` 的鍵推「哪一道失敗」 | §1.2:那些鍵是嵌了頁碼的顯示字串。要呼叫個別檢查函式組結構化結果 |
| 在 `core/ingest.py` 另寫一份「哪些失敗可以擴頁」 | `core/expand_policy.py` 是唯一來源,import 它(I3 / T5) |
| A1 順手修掉 `_taxonomy_gap` 回 None 就擴頁的缺陷 | 那是 A2 的工作。A1 要逐字保留現有行為 |
| 改 `fill.py` 讓它呼叫 `core.ingest` | 本單是「搬出來」不是「改掉」。`fill.py` 的退場是 C5 |
| 四條出口的訊息「意思一樣就好」 | 訊息逐字相同。`/fill` skill 明令 agent 照抄那些字 |
| 拿重播冒充「3 個新格實跑」 | §4:兩者不是一回事,不准混 |
| 測試寫進真實 `facts/` `work/` `taxonomy/` | 一律 tmp,測完還原 |
| 看到 `plan_local_first.md` 就開始做 jobs/workbench/chdir | 那是 C3-b。本單只做 ingest |
| A2 的數字變了就去調判準讓它不變 | 變了是產出,但每個變化都要解釋得出來。解釋不出來才是搬錯了 |
| 做完 A2 順手做 C3-b / C4 | 本單明確停在 A2 |
| 做完 A1 就回報問要不要繼續 | 一次性回報 |
