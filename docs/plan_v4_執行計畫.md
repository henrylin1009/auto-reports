# v4 執行計畫 —— 給執行者的逐步指令

> **這份文件是自足的。** 你不需要讀過任何審查報告或先前對話,照著做即可。
> 依據:`docs/architecture_review_20260727.md`(架構審查)。有疑問時那份是「為什麼」,這份是「怎麼做」。
> 制定日期 2026-07-27。

---

## 0. 你在做什麼

這個專案從 89 份台灣銀行財報 PDF 抽出「每家 × 每期 × 每個會計分類 × 7 個債券桶 × 2 種口徑」的數字,發布到靜態網站。

**最高原則:任何發布出去的數字,都必須有算術證明它對得上資產負債表;證不了的一律是 `null`,不准猜。**

現有管線(v3)六個核心模組都在,而且是對的:

| 模組 | 職責 | 狀態 |
|---|---|---|
| `bs_anchor.py` | 讀 BS 三個數字(錨)。純 Python | ✅ 不要動 |
| `locate.py` | 把錨值格式化成 `"518,009,809"` 全文 grep → 候選頁 | ✅ 不要動 |
| `transcribe.py` | 產生 agent 輸入 + 六道驗收檢查 | ⚠️ T7 才拆 |
| `buckets.py` | 原名 → 桶(查表) | ⚠️ T8 才改格式 |
| `wide.py` | rows + 桶 → 網站的 7 桶 | ✅ 不要動 |
| `results.py` | 產生 rows / verdict / audit 三份產物 | ⚠️ 小改 |
| `pipeline.py` | 定位 → 抄列 → 驗收 → 對不上就擴張 → 再抄 | ⚠️ T2 補實作 |

**唯一的大洞:「抄列」(把候選頁的文字變成 rows)沒有工具化**,目前是人在互動式 session 裡
一格一格手貼。結果:**169 格只完成 19 格(7%)**,而線上網站還在跑已知有錯的舊管線。

### 抄列由誰做:**Claude Code 自己**(已定案)

**不呼叫任何模型 API。** 這個專案的成品是一支**跑在 Claude Code 上的程式** ——
任何人 clone 下來、在自己的 Claude Code 開起來、打一個 slash command,
就能把抄列跑完。讀表的 agent 就是那個 Claude Code session。

所以真正的交付物有兩半,**兩半都要做,缺一邊都不能用**:

| | 是什麼 | 誰執行 |
|---|---|---|
| **CLI** `fill.py` | 找頁 · 驗收 · 擴張 · 歸檔 · 記進度 | Python,確定性 |
| **skill** `.claude/skills/fill/SKILL.md` | 驅動迴圈的指令:拿一格 → 抄 → 交 → 看結果 → 下一格 | Claude Code |

```
   /fill  ──►  fill.py next          → 印出一格的候選頁文字
                    ▲                        │
                    │                   Claude Code 讀表、寫 rows JSON
                    │                        │
                    └── 下一格 ◄── fill.py submit ──┬─ PASS → 歸檔進 facts/
                                                    ├─ FAIL → 自動擴張鄰頁,印出新的頁,再抄一次
                                                    └─ REJECT → 進人審佇列
```

#### 這個設計的關鍵性質:**狀態全在檔案裡,agent 不持有任何狀態**

169 格 × 每格 2–4 頁文字,遠遠塞不進一個 context window。所以迴圈必須能在
**context 被壓縮、session 被關掉、換一台電腦、換一個人**之後照樣接著跑。
做法就是:agent 每一輪只認得「現在這一格」,做完就忘掉;
「跑到哪了」由 `facts/` 與 `work/` 的檔案決定,`fill.py next` 自己算得出來。

**這條性質是整個 T3 的驗收標準。** 如果 skill 需要 agent 記住前面抄過什麼,那就是設計錯了。

**T0–T4 是主線**,其餘是主線通了之後的清理。

---

## 1. 鐵律(違反就是做錯,不是風格問題)

1. **不准為了讓某格通過而放寬檢查。** 六道檢查的嚴格度是這個系統唯一的資產。
   拒收是正確輸出,不是 bug。
2. **不准針對某一家銀行 / 某一個版型寫規則。** 包含魔術常數(容差、視窗大小、門檻)。
   要加任何常數之前,先跑全語料掃描證明它有安全區間。
3. **不准手工往 `buckets.SYN` 塞名字。** 塞錯了**沒有任何檢查抓得到**(金額照樣加得對、
   兩表照樣對得上,錯的只有那一桶)。一律走 `synonyms.py` 產生提案 → 人審 → 貼進去。
4. **不准補 0。** 缺欄 = 未揭露 ≠ 0。取不到就是 `null`。
5. **不准退回 `archive/` 或 `legacy/` 的舊管線。**
6. **每個任務結束都要能獨立驗證、可回滾。** 沒跑過驗收指令就不算做完。
7. **改了行為就要說。** 六支測試全綠不代表沒改行為 —— `locate.py --census --check` 那類
   基準數字若變了,要嘛是 bug,要嘛要在文件裡寫明為什麼。

### 每次開工前先跑這個

```bash
cd /Users/henrylin/Desktop/work && git status --short && for t in test_locate test_rules test_synonyms test_pipeline test_cross test_wide; do printf "%-16s " $t; python3 $t.py >/dev/null 2>&1 && echo OK || echo FAIL; done
```

六支全 OK 才開始。做完任何一個任務後再跑一次,還是要六支全 OK。

---

## 2. 任務清單

**嚴格照順序。** T0→T1→T2→T3 是關鍵路徑,**T3 是決策點,跑完要停下來回報**。
T7–T10 可以在 T4 之後平行做,但**不准提前**。

---

### T0 — 事實庫搬家 + 清垃圾

**為什麼**:目前權威事實庫是 `scratchpad/rows_v3.json`(19 格,34 份 record,296 列),
而 scratchpad 的定義就是可以隨時刪。`results/rows.json` 是它的完全複本。
根目錄還躺著 12 份 `.bak_*` / `.pre_*` 備份 —— 在一個 git repo 裡。

**動作**

1. 建立 `facts.py`,集中所有事實庫 IO(目前四個進入點各自 `json.load`):

```python
# facts.py
"""事實庫:一份文件一個檔,進 git。抄一次,除非發現抄錯否則永不重跑。"""
import glob, json, os

DIR = "facts"

def load():
    """→ {格key: [record, ...]},格key 形如 `202404_5843_AI3|Trading`。"""
    cells = {}
    for p in sorted(glob.glob(f"{DIR}/*.json")):
        cells.update(json.load(open(p, encoding="utf-8")))
    return cells

def save(cells):
    """按 doc 分檔寫回。一個大檔的 git diff 在 169 格之後沒人看得動。"""
    os.makedirs(DIR, exist_ok=True)
    by_doc = {}
    for key, recs in cells.items():
        by_doc.setdefault(key.split("|")[0], {})[key] = recs
    for doc, part in by_doc.items():
        json.dump(part, open(f"{DIR}/{doc}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
```

2. 把 `scratchpad/rows_v3.json` 拆進 `facts/`(寫一次性腳本,放 scratchpad,跑完可丟)。
3. 改四個進入點改用 `facts.load()`:`results.py:79`、`wide.py` 的 `__main__`、
   `synonyms.py:112`、`transcribe.py` 的 `--verify`。**保留 CLI 可傳路徑的能力**,
   只把預設值改成 `facts.load()`。
4. `results.py` 不再把 `cells` 原封不動當 `rows` 輸出(`results.py:61`)——
   `results/` 只放衍生物 `verdict.json` / `audit.json`。
5. 刪掉根目錄所有 `extract_v2_results.json.bak_*`、`*.pre_*.json`、`data.json.pre_bridge`。
   先 `git ls-files` 確認哪些有進 git,有的用 `git rm`,沒有的用 `rm`。
6. `.gitignore` 加 `results/`,`facts/` **不要**加(它要進 git)。

**驗收**

```bash
python3 -c "import facts; c=facts.load(); print(len(c),'格'); assert len(c)==19"
python3 results.py --print && for t in test_locate test_rules test_synonyms test_pipeline test_cross test_wide; do python3 $t.py >/dev/null || echo "FAIL $t"; done
```

`results.py --print` 的摘要必須和搬家前**逐字相同**(搬家前先存一份輸出比對)。

**不准**:趁機改任何 record 的內容。這一步是純搬移。

---

### T1 — 事實庫邊界加驗證

**為什麼**:事實庫是**人手寫的 JSON**,也就是整個系統唯一的不受信任輸入,
而它進入受信任程式碼的那一點沒有契約。實測現況:`printed_totals` 只有 12/34 份 record 有、
`group` 只有 110/296 列有、已停用的 `basis` 欄位還留在資料裡。
`transcribe.check_identity` 遇到缺 `total_col` 會 KeyError 而不是回「檢查失敗」。

**動作**:在 `facts.py` 加 `validate()`,`load()` 內部呼叫。

```python
REQUIRED_REC = ("doc", "class", "source_page", "source_kind", "total_col", "printed_total", "rows")
OPTIONAL_REC = ("printed_totals", "note")
REQUIRED_ROW = ("name", "cols")
OPTIONAL_ROW = ("group",)

def validate(cells):
    """回傳問題清單。空 list = 通過。**不修資料,只報告。**"""
```

至少檢查:
- record 必要欄位齊全;沒有 `REQUIRED_REC + OPTIONAL_REC` 以外的欄位
  (`basis` 已停用 —— 若還在資料裡,列為問題並在 T0 的搬家腳本裡刪掉)
- `rows` 非空;每列有 `name`(非空字串)與 `cols`(dict)
- `cols` 的 value 全是 int(**不是 float、不是字串**)
- `total_col` 一定出現在至少一列的 `cols` 裡
- `key` 的 `doc` / `class` 與 record 內的 `doc` / `class` 一致
- `printed_totals`(若有)的 key 都是字串、value 都是 int

**驗收**:寫 `test_facts.py`,注入 5 種壞資料各驗一次會被抓到
(缺 `total_col` / `cols` 有 float / rows 空 / key 與內容不一致 / 出現未知欄位),
再驗現有 19 格全部通過。

```bash
python3 test_facts.py && python3 -c "import facts; assert not facts.validate(facts.load())"
```

**不准**:改成 dataclass 全面重構。那會動到 `transcribe` / `wide` / `synonyms` 每一處
`rec["..."]` 存取,是大 diff 高風險而且現在沒有好處。等 T4 之後再議。

---

### T2 — transcriber 介面 + replay 實作

**為什麼**:`pipeline.drive(doc, cls, transcriber)` 這個介面已經存在(`pipeline.py:100`),
但**沒有任何生產實作**。這一步先做 `replay`(重播已抄好的 19 格)當回歸基準,
用來證明「換成自動抄列」不會改變迴圈本身的行為。

**動作**

1. 改 `pipeline.drive` 與 `run` 的協定,讓 transcriber 拿得到 `doc` / `cls`:

```python
def drive(doc, cls, transcriber):
    """`transcriber(doc, cls, prompt) -> recs | None`(抄不出來回 None)。"""
```

（`run()` 這個 generator 本身**不動** —— 它仍然只 yield prompt。只有 `drive` 多傳兩個參數。）

2. 新增 `transcriber.py`:

```python
# transcriber.py
"""抄列器:候選頁純文字 → rows。**唯一的非確定性元件。**

實作走同一個介面,所以「誰去讀表」是部署決定,不是架構決定:
    replay(cells)  重播已抄好的事實庫,給回歸測試用
    submitted(p)   讀 Claude Code 剛寫好的 rows JSON(T3 的 `fill.py submit` 用)

⚠️ 驗收由 `transcribe.verify()` 做,抄列器本身**不做任何檢查、不做任何判斷**。
   抄不出來就回 None,不准猜、不准補 0、不准分桶。

⚠️ **這裡不准出現任何模型 API 呼叫**(使用者指示)。抄列由外部 agent 完成。
"""
def replay(cells):
    def _t(doc, cls, prompt):
        return cells.get(f"{doc}|{cls}")
    return _t
```

**驗收**:新增 `test_drive.py` —— 對事實庫裡的每一格跑 `pipeline.drive(doc, cls, replay(cells))`,
每格都要 `outcome.ok` 且 `outcome.recs` 與事實庫**逐列相同**。

```bash
python3 test_drive.py    # 19 格全部重現
```

**不准**:在這一步碰任何模型 API。這一步是純介面。

---

### T3 — `fill.py` CLI + `/fill` skill

**這是整個計畫最重要的一步。做完要實測 5 格並回報,不要自己往下做 T4。**

**為什麼**:抄列一格的真正成本不是「讀表」,是圍繞它的手工:找候選頁、組 prompt、
貼回結果、跑驗收、對不上時判斷要不要擴張鄰頁、再重來一次。這些**每一項都是機械的**,
現在卻都由人做 —— 這才是 7% 覆蓋率的成因,不是讀表本身慢。

`fill.py` 把機械的部分全部吃掉,skill 讓 Claude Code 自己轉迴圈,
agent 只做一件它非做不可的事:**看著文字抄數字。**

#### T3.1 `fill.py` —— agent 面向的 CLI

**設計原則(每一條都是為了讓 agent 好用,不是為了讓人好用):**

1. **一個指令 = 一個決定。** `next` 只印一格,不印清單、不分頁、不給選單。
2. **每個指令的最後一行都要明講下一步該做什麼。** agent 不必推理流程。
3. **狀態全在檔案。** 任何指令都可以在全新的 session 裡跑,結果一樣。
4. **輸出要省 context。** 除了不得不印的頁文字,其餘一律壓到幾行。

```
python3 fill.py next
    → 印出一格:格key、錨值、事實層規矩、候選頁文字、要寫去哪個路徑
    → 沒有待辦時印 `ALL DONE`,exit 0

python3 fill.py submit work/current.json
    → 驗收剛寫好的 rows,印出三種結果之一:
        PASS      已歸檔進 facts/。下一步:python3 fill.py next
        RETRY     沒過,差額 150,477。已擴張加入鄰頁 [30, 32]。
                  下一步:重讀下面的頁再抄一次(頁文字接在後面)
        REJECT    擴張到上限仍對不上,已進 work/rejected/。
                  下一步:python3 fill.py next

python3 fill.py status
    → 已完成 x / 待抄 y / 人審佇列 z(三行,不印清單)
```

**`next` 印出來的內容**(順序很重要:規矩在前、資料在後):

```
# 202404_5843_AI3 | Trading      錨(BS 合計)= 9,082,587 仟元

把下面來源頁裡的表格逐列抄成 JSON,寫到 work/current.json,然後跑
    python3 fill.py submit work/current.json

## 事實層規矩(違反會被退回)
- name 存**表上印的原名** —— 不正規化、不翻譯、不分桶、不改錯字
- cols 的 key 存**原欄名**(「取得成本」「公允價值總額」「帳面金額」…)
- **缺的欄不放 key,不准補 0** —— 未揭露與 0 是不同的事實
- **小計 / 合計不是資料列**,不進 rows;它們放 printed_total / printed_totals
- 同一格可能有多份 record(年報通常是「附註」+「明細表」),一份對一個來源頁
- **抄不出來就寫 {"records": []}。不要猜** —— 猜錯比空白糟糕得多

## 自己先對一次(對得上就不必來回一輪)
每份 record:sum(每列的 total_col 那一欄) == printed_total,且 printed_total == 9,082,587

## 格式
{"records": [{"source_page": 31, "source_kind": "附註", "total_col": "...",
  "printed_total": 9082587, "printed_totals": {"取得成本": ...},
  "rows": [{"name": "公司債", "group": "有價證券", "cols": {"取得成本": ..., "公允價值總額": ...}}]}]}

## 來源頁
===== page 31 =====
（純文字）
```

**要點**
- **錨值放兩次**(標題列 + 自我檢查區),它是唯一的自我檢查手段。
- `RETRY` 時要**講明白多出來的頁是怎麼來的** —— `transcribe.context_pages()` 已經會產生
  這段警語,照用:「上一輪對不上,已擴張加入鄰頁 [x],這些頁不印錨值,
  要找的是能補足差額的小計或子附註」。
- `submit` 內部就是 `facts.validate()` → `transcribe.verify()` → 通過寫 `facts/`,
  不過就 `loc.expand(cls, level+1)`。**擴張邏輯 `pipeline.run()` 已經寫好了,直接用,
  不要重寫。** 判準是算術不是版型 —— 對不上就擴、對上就停,所以不需要分辨遇到的是
  哪一種漏抓(實測有三種:子附註在另一頁 / 表格跨頁 / 同頁多段小計,同一招都治)。
- `work/` 加進 `.gitignore`,但 `work/rejected/` 要進 git(那是待辦清單)。
- **每格通過時記 provenance**,寫進 record 的 `_by` 欄位:
  `{"at": "2026-07-27T14:03", "retries": 1, "level": 1, "via": "claude-code"}`。
  `facts.validate()` 要認得這個欄位(不然 T1 的「未知欄位」檢查會擋下來)。
  **為什麼**:`facts/` 是這個專案最貴的資產,而抄列是唯一非確定性的一步。
  API 版天然有 request/response 可查,agent 版沒有 —— 記個時間戳與輪數就把缺口補起來了。
  ⚠️ 這是**稽核欄位,不是事實** —— `wide` / `buckets` / `verify` 一律不准讀它。

#### T3.2 `.claude/skills/fill/SKILL.md` —— 驅動迴圈

`.claude/` 目前只有 `launch.json`,**沒有任何 skill,這是要新建的**。

```markdown
---
name: fill
description: 抄列迴圈 —— 把財報候選頁的表格抄成 rows 並驗收歸檔。使用者說「跑抄列」
             「繼續抄」「fill」或直接打 /fill 時使用。
---

# 抄列迴圈

重複以下步驟,直到看見 `ALL DONE`:

1. `python3 fill.py next`
2. 照它印出的規矩,把來源頁的表格抄成 JSON,寫到 `work/current.json`
3. `python3 fill.py submit work/current.json`
4. 看結果:
   - `PASS` → 回到步驟 1
   - `RETRY` → 讀它附上的新頁,重抄一次,再 submit(不要跳過,不要回步驟 1)
   - `REJECT` → 回到步驟 1
   - `ALL DONE` → 結束,回報 `python3 fill.py status`

## 鐵律

- **只抄,不判斷。** 不分桶、不正規化、不翻譯、不改錯字。
- **抄不出來就寫 `{"records": []}`。** 猜一個數字比留白糟糕得多 ——
  留白會被擋下來進人審佇列,猜錯的數字會通過檢查然後上網站。
- **不要修改 `fill.py`、`transcribe.py` 或任何檢查邏輯。** 抄不過是資料的事,不是程式的事。
  如果你覺得檢查有 bug,停下來告訴使用者,不要自己改。
- **不要記住前面抄過什麼。** 每一格都是獨立的;進度存在檔案裡,不在你的記憶裡。
  context 快滿了也照樣繼續 —— 被壓縮或重開之後 `fill.py next` 一樣接得下去。
- 一次只處理一格。不要為了「效率」一次讀好幾格。
```

**skill 的措辭要注意**:寫給 agent 的指令要**講清楚不做什麼**,尤其是
「不要改檢查邏輯」—— 抄不過時最自然的反應就是去動閘門,而那正是這個系統最不能被動的地方。

#### T3.3 讓別人也跑得起來

成品要能被別人 clone 下來直接用,所以:

1. `README.md` 加一段 **Quickstart**:clone → `pip install -r requirements.txt` →
   抓 PDF → 在 Claude Code 裡打 `/fill`。
2. **PDF 取得**:`pdf_cache/` 是 gitignore 的(89 份 PDF 不該進 git),
   抓檔的 `resolve.py` 還在。把它收成 `fetch.py`(或在 README 寫明怎麼跑),
   讓 `fill.py next` 在 `pdf_cache/` 是空的時候印出明確的指示,而不是印 `ALL DONE`。
   —— **這個空目錄陷阱一定要處理**:沒有 PDF 時「沒有待辦」與「全做完了」
   在畫面上長得一模一樣。
3. `requirements.txt` 確認涵蓋 `pypdfium2`(`locate.py` / `bs_anchor.py` 用)。

**驗收**

1. **乾式回放**:對事實庫 19 格,用 `facts/` 裡現成的答案假裝成 `work/current.json`
   逐格 submit → 19 格全部 `PASS` 且逐列相同。這證明 next↔submit↔驗收這條路是通的。
2. **真的跑 5 格**:挑 5 格從沒抄過的(五家各一,年報半年報都要有),
   在**一個乾淨的 Claude Code session** 裡打 `/fill`,讓它自己轉。實測並回報:

| 指標 | 說明 |
|---|---|
| 第一輪通過率 | 5 格裡有幾格沒 RETRY 就過 |
| RETRY 後通過率 | 擴張之後幾格過 |
| REJECT | 幾格,理由分別是什麼 |
| **agent 有沒有做錯事** | 有沒有想改檢查、想跳過 RETRY、想一次抄多格、猜數字?**這一欄最有價值** —— 它直接告訴你 skill 的措辭要補什麼 |
| 每格耗時與 token | 用來估 169 格要跑幾個 session |

3. **狀態外置驗證**:抄完 2 格後**把 session 關掉重開**,再打 `/fill`,
   必須從第 3 格接下去,不能重跑也不能漏跑。這條是 T3 的核心設計性質,一定要實測。

**回報後停下來。** 依實測結果決定 T4 怎麼排。

**不准**
- ❌ **不准呼叫任何模型 API**(使用者已定案)。`fill.py` / `transcriber.py` 裡不准出現
  `anthropic` / `genai` / `openai` 任何一個 import。
- ❌ 不准為了提高通過率去改 `verify()` 的任何一道檢查。
- ❌ 不准在 `next` 的輸出裡塞某一家銀行的版型提示(「兆豐的附註通常在 p31」之類)。
  模板對 169 格必須是同一份 —— 那是打版,而且會讓 agent 停止看表。
- ❌ 不准讓 skill 需要 agent 記住跨格的東西。需要記 = 設計錯了。
- ❌ 不准在 `submit` 裡「順手修」交回來的資料(補 0、改名字、刪小計)。
  格式不對就退回重抄 —— 修過的資料沒有人驗得到。

---

### T4 — 跑滿 169 格(**要等 T3 實測回報後才開始**)

**T0–T3 之後程式面已經沒有工作了**,剩下的是開 session 打 `/fill` 讓它轉,
轉到 context 滿了就重開一個再打一次 —— 進度在檔案裡,接得下去。

**動作**

1. **先確認分母。** 跑 `python3 locate.py --census --check`,應符合基準
   `錨讀不到 96 / 錨有但無候選頁 2 / 可進agent 169`。
   那 96 格全是 2022 以前、BS 是掃描影像,走不了純文字路徑 —— **這一輪不做**,
   `fill.py next` 自然會跳過(`locate()` 讀不到錨就不產工單)。
   現役範圍(2023+)與回填範圍是乾淨切開的兩塊。
2. **分批跑,不要一口氣衝完。** 建議先跑 10–20 格就停下來看一次
   `git diff facts/`:skill 的措辭問題一定會在前一兩批暴露(T3 驗收表的
   「agent 有沒有做錯事」那一欄),先修 skill 再繼續,否則等於把同一個缺陷複製 150 份。
3. **順序**:`fill.py next` 的排序要**先年報後半年報**。年報有雙來源(附註 + 明細表),
   第 3 道「雙表互對」會跑 —— 那是**唯一驗得到「名字↔金額配對」的檢查**,驗證強度最高,
   問題會早一點暴露;半年報只有附註一份,第 3 道天生不適用。先做強的那批比較划算。
4. 每批之後 `python3 fill.py status` 並回報。

**驗收**

```bash
python3 fill.py status
python3 -c "import facts; print(len(facts.load()),'格')"
python3 results.py --print
```

回報:覆蓋率(x/169)、`work/rejected/` 的清單與理由分佈、skill 改了哪幾句話。

**不准**
- 不准為了讓拒收的格變綠而新增任何接受分支。拒收就是拒收,進人審佇列。
- 不准一口氣跑完 150 格才第一次檢查產出。

---

### T5 — 重切保留集(**必須在 T6 之前**)

**為什麼**:分桶表、同義詞、檢查門檻,全都是看著已抄的格子長出來的。
看得越多,表越貼合那些格子 —— 而「貼合」與「通用」在只看訓練資料時**長得一模一樣**。
目前 `holdout.py` 只切了 3 格,而在切它之前已經有 16 格被同一個人抄過並拿來調過表。分母不對。

**T3 的外包抄列已經解掉一半這個問題** —— 抄的人不再是調表的人。但另一半還在:
你(調表的人)在 T6 會看遍訓練集的所有名字。保留集就是唯一分得出「貼合」與「通用」的東西。

**順序關鍵**:T4 只是把數字抄下來(不調表),所以 T4 之後、**任何人看那些新格子的名字之前**,
就要把保留集切出來。

**動作**:改 `holdout.py`,切 **15 格**。選格要涵蓋已知會出事的結構,不是隨機抽:
- 兆豐半年報(逐項成本 + 一整筆評價調整 → 帳面在文件裡不存在,驗「該 null 時真的 null」)
- 單一附註無明細表的半年報(驗第 3 道確實不適用而不是假裝通過)
- 附註含大量衍生的年報(驗三段恆等式)
- 五家 × 三類都要有代表
把舊的 3 格標記作廢(保留註解說明為什麼作廢),不要直接刪掉那段歷史。

**驗收**:`results.py` 不加 `--holdout` 時,保留集的 15 格必須被擋在門外(現有機制,
`results.py:81`)。跑一次確認會 exit 1。

**不准**:切完之後為了讓某格通過而回頭調整保留集的組成。

---

### T6 — 分類表擴張 + CI 閘門

**動作**

1. 對訓練集(全部格 − 保留集)跑 `python3 synonyms.py --check`,把「可自動推定」
   那段的提案逐條**看過**再貼進 `buckets.SYN`。「衝突」那段是**失敗**,先去查抄列。
2. 未涵蓋的名字按金額排序,逐條處理:
   - `rules.propose()` 提得出來的 → 提案裡有出處關鍵字,貼進去
   - 提不出來的 → **進 `buckets.PENDING`,拿去問使用者**,不要自己決定
3. 新增 `test_syn_source.py` —— **每一條 `SYN` 都要有背書**:
   能被 `rules.propose()` 提出、或能被 `synonyms.candidates()` 從事實庫推出、
   或在一份明確的人審決定清單裡(`buckets.py` 註解已有這種標記,收成一個常數)。
   三者皆非 → exit 1。
   **測試本身要先證明會失敗**:注入一條手寫別名,確認 exit 1。

**為什麼要 T6.3**:「不准手工塞 `SYN`」目前只是一段 docstring 警告。19 格時人做得到,
169 格時做不到。知識寫在註解裡,代表架構還沒把那個錯變成不可能犯。

**驗收**

```bash
python3 synonyms.py --check     # 零衝突
python3 test_syn_source.py      # 每條 SYN 都有背書
python3 results.py --print      # 通過率 / null 格數
```

回報:訓練集通過率 vs **保留集**通過率。兩者差距 > 10 個百分點 = 表過擬合了,回報不要硬推。

---

### T7 — 拆 `transcribe.py`(純機械搬移)

**為什麼**:398 行、六個職責:prompt 組裝 · 六道檢查 · 兩表對帳 · 欄位對齊 ·
合併列偵測 · 桶層降級。而且 `wide.py:85` 從**驗收層**import `coarse()` 來做
**取值來源選擇**,`synonyms.py:55` 借用 `align()` —— 視圖層與同義詞層都得跟驗收層借東西。
根因:`align` / `_amounts` / `_merged` / `_by_bucket` / `coarse` 是**對帳原語**,
`check_*` 是**閘門**,兩者生命週期不同。

**動作**

| 新檔 | 從 `transcribe.py` 搬什麼 |
|---|---|
| `prompt.py` | `context()` `context_pages()` |
| `recon.py` | `align` `_amounts` `_names` `_merged` `_by_bucket` `coarse` |
| `checks.py` | `check_*` × 6 · `verify` · `report` · `NA_*` / `PARTIAL` 常數 |

`checks.py` 的 `verify()` 改成跑一張註冊表,不要繼續手寫 f-string 組 dict
(現在的 `transcribe.py:353-361`,加一道檢查要改三個地方):

```python
CHECKS = [("①②列相加", check_identity, "每份"), ("④合計==錨", check_anchor, "每份"), ...]
```

`wide.py` 改 import `recon.coarse`,`synonyms.py` 改 import `recon.align`。

**驗收**:**六支測試全綠,零行為改變。** 拆之前先存一份
`python3 results.py --print` 的輸出,拆完必須**逐字相同**。

**不准**:趁機「順便」改任何一道檢查的邏輯。這是純搬移。要改邏輯另開一次 commit。

---

### T8 — `taxonomy.yaml` 統一分類法

**為什麼**:同一套分類法目前被編碼**三次**:
`config.BUCKET_RULES`(散文,權威)→ `rules.KEYS`(關鍵字表,由 `rules.audit()` 對散文)
→ `buckets.SYN`(精確別名表,由人 git diff 把關)。
再加上散落的 `GROUP_SYN` / `GENERIC` / `PREFIX_ONLY` / `COST_COLS` / `BOOK_COLS` / `BUCKET_MAP`
跨兩個檔。根因是 `BUCKET_RULES` 原本是**寫給 LLM 的 prompt**,後來被追認為規格 ——
**prompt 不是規格**。

**動作**:一份 `taxonomy.yaml`:

```yaml
公債:
  wide: GB
  kind: asset            # asset | derivative | adjustment
  aliases: [政府公債, 政府債券, 國外機構發行債券]   # 精確比對,生效
  keywords: [政府公債, 公債]                        # 只產生提案,不生效
  notes:
    國外機構發行債券: 2026-07-26 人審決定,證據見 buckets.py 原註解
衍生:
  wide: null             # 刻意不進 7 桶
  kind: derivative
```

- `buckets.py` 改成讀 yaml,只剩查表邏輯。
- 給 LLM 的散文 prompt 若還需要,**從這份表生成**,不要反過來。
- `rules.audit()` 與 `config.py:79` 那個 `LEGACY_*` assert 隨之消失。
- **所有現有註解裡的證據與警語必須完整搬進 `notes`**,一條都不准掉。
  那些是這張表最貴的部分(例:REITs 歸「資產基礎」而不是直覺的「股票」)。

**驗收**:`test_synonyms.py` / `test_rules.py` / `test_syn_source.py` 全綠;
`results.py --print` 輸出與改之前逐字相同。

---

### T9 — 切換上線(**要等 T6 的保留集數字合格**)

**為什麼**:`data.json` 目前由 `bridge_v2` ← `extract_v2` 產生,而 `bridge_v3 --write`
**一次都沒跑過**。已知差異:玉山「國外機構發行債券」線上歸「其他」,v3 判「公債」,
單格量級 368 億。

**切換條件(先寫死成可執行的判準,達標才切)**

```
2023+ 的 169 格通過率 ≥ 95%,且保留集 15 格與訓練集通過率差距 < 10 個百分點
```

**動作**

1. `python3 bridge_v3.py`(不加 `--write`)—— 印出所有差異。
2. **逐格人工確認差異是預期的,把確認結果貼給使用者。** 這一步不准跳過。
3. 確認後 `python3 bridge_v3.py --write`。
4. **同一天**刪掉:`extract_v2.py`、`batch_v2.py`、`bridge_v2.py`、`test_oracle.py`、
   `config.py:63-80` 的 `LEGACY_*` + assert、`config.py` 的 `MODEL` / `MIN_GAP` /
   `TOL` / `TOL_REL` / `MAX_EXPAND` / `PANEL_JUMP_REL`(實測:v3 完全沒用到這些)、
   `.env` 裡的 Gemini 金鑰輪替相關程式碼。
5. `更新網站.command` 改呼叫 `bridge_v3.py`。

**不准**:兩套管線並存超過一個階段。並存的每一天都在製造相容層。

---

### T10 — 清遺物 + 拆 `config.py`

刪:`archive/`(11 檔)、`legacy/`(10 檔)、`phase0.py`、`fetch_test.py`、
`make_charts.py`、`build_native.py`、`app.py`、`scratchpad/` 除必要外全部。

⚠️ **`resolve.py` 不要刪** —— 它是 TWSE 抓檔器,而 `pdf_cache/` 是 gitignore 的,
別人 clone 下來就是靠它取得 89 份 PDF。T3.3 會把它收成一個明確的取檔步驟。
`run.sh` 目前呼叫的 `build_report.py` 在根目錄不存在(在 `legacy/`)—— 順手修掉或刪掉 `run.sh`。

`config.py` 目前混了四種生命週期(品牌色 · 銀行代碼 · 會計分類法 · 已死的 API 設定),
**改一個顏色跟改一個桶的定義動的是同一個檔**。拆成:
`taxonomy.yaml`(T8 已做)· `theme.py`(色與顯示名)· `corpus.py`(銀行代碼、表別白名單)。

**驗收**

```bash
python3 -c "import results, wide, synonyms, facts, checks, recon, prompt"
for t in test_locate test_rules test_synonyms test_pipeline test_cross test_wide test_facts test_drive test_syn_source; do printf "%-18s " $t; python3 $t.py >/dev/null 2>&1 && echo OK || echo FAIL; done
python3 make_web.py    # 網站還產得出來
```

---

## 3. 明確不做

- ❌ **呼叫任何模型 API 做抄列**(使用者已定案)。抄列由 Claude Code 自己做,
  `fill.py` / `transcriber.py` 裡不准出現 `anthropic` / `genai` / `openai` 任何一個 import
- ❌ 讓 skill 需要 agent 跨格記住任何東西 —— 進度存檔案,不存記憶
- ❌ 重寫 `locate.py` / `bs_anchor.py` / `expand()` —— 它們有全語料實測基準,而且是對的
- ❌ 上 sqlite / postgres —— 169 格,git diff 就是審核介面
- ❌ 座標重建 / 讓模型調座標參數 —— 已實測,收益為 0
- ❌ 為單一格新增接受分支
- ❌ 回填 2022 以前那 96 格 —— BS 是掃描影像,要走視覺路徑,是另一個題目
- ❌ 先做 T7–T10 再做 T2–T4 —— 先解決 7% 覆蓋率,其餘都是在裝修一棟沒人住的房子

---

## 4. 回報規範

每個任務做完,回報三件事,不要多:

1. **驗收指令的實際輸出**(貼原文,不要轉述)
2. **有沒有行為改變** —— 基準數字(`--census --check`、`results.py --print` 摘要)
   變了就要說,並說明是 bug 還是預期
3. **卡住的地方** —— 卡住就停下來問,不要繞路。特別是 T3(要實測 5 格並回報工單缺陷)
   與 T6(需要人審決定桶)這兩處,**設計上就是要停下來的**

如果某個任務只做完一半,**明講哪一半沒做、為什麼**。不要把「大部分做完了」報成「做完了」。
