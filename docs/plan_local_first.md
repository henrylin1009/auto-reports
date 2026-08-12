# Local-first 工作台 —— 產品與架構計畫

> 制定 2026-07-28。**本文件只做計畫與現況盤點,不改任何程式碼。**
>
> 定位改變:產品不再是「產生一個公開網站」,而是
> **使用者在自己電腦上操作的財報資料工具**。不需要帳號、伺服器、上傳、GitHub Pages。
> HTML 是**本機**查看結果/證據/待審/執行狀態的介面;公開發布降級為**未來可選的 export**。
>
> 與既有文件的關係:
> `plan_clean_core.md`(Phase A)與 `plan_phaseB.md`(Phase B)的**語意層全部保留**,
> 本文件只改 **C3 / C4 的定義**與**發布層的去留**。衝突時:
> **語意與不變量以 `plan_phaseB.md` 為準;交付形態與 C3/C4 範圍以本文件為準。**

---

## 0. 先講結論:這個轉向划算,但有一件事不是包裝

### 0.1 「核心邏輯一樣,只是包裝不一樣」—— 大致成立,有一個例外

**成立的部分(這是好消息,而且是可驗證的)**:`core/` 的五個 Phase A 模組
(`units` `expand_policy` `contracts` `store` `reconcile`)加上 Phase B 的
`decisions` `migrate_syn`,**沒有任何一行知道結果會變成網站還是本機報表**。
它們吃 `facts/`、吐 verdict 與 decision。發布形態換掉,這些一行都不用動。

**唯一的例外,而且是真的**:整個專案的資料根目錄都是**寫死的相對路徑常數**(實測):

```
facts.py:12          DIR = "facts"
core/store.py:24,25  ANCHORS_DIR = "anchors" / PDF_DIR = "pdf_cache"
build.py:39,41,42    SNAP_DIR = "snapshots" / PREVIEW_DIR = "preview" / DATA = "data.json"
results.py:31        OUT = "results"
fill.py:31           WORK_DIR = "work"
bridge_v3.py:27      SRC, DATA = "results/verdict.json", "data.json"
```

要支援「使用者自己的 workspace」,直覺做法是**把路徑注入每一支** ——
那會動到 `facts.py` `build.py` `results.py` `fill.py`,**全部在禁改清單上**,
而且會讓 Phase A 好不容易綠掉的四道等價閘門全部要重跑。

**所以本計畫的核心設計決定是:不做路徑注入,改用 `chdir`。**
工作台把每個作業當**子行程**啟動,`cwd` 設成 workspace 根目錄。
所有相對路徑原封不動地繼續成立,**禁改檔一個 byte 都不用改**。
這一個決定,就是「只是包裝不一樣」這句話能不能成立的關鍵。

副作用是好的:`chdir` 是行程級的,所以作業**必須**是子行程 ——
而子行程本來就是我們要的(可取消、可逾時、可擷取 log、一個作業壞掉不會拖垮工作台)。

> **2026-07-28 使用者已裁示:採 chdir。** 以下三條是裁示後補上的實作細則。

#### 路徑解析的三條規則(各管各的,不互相覆蓋)

```
① cwd = workspace        → 使用者資料(facts/ taxonomy/ decisions/ out/ pdf_cache/ …)
② __file__ 相對          → app / seed 唯讀資源、import 解析、挖工具自己的 git 史
③ 參數注入(相對預設值)  → 測試塞 tmp,不污染真實目錄
```

Phase B 的新碼**已經同時做到②和③**(實測):

```
core/ratify.py            def ratify_rule(..., taxonomy_dir="taxonomy")   ← ③
core/migrate_syn.py:23    _PROJ = dirname(dirname(__file__))              ← ②
              :24            sys.path.insert(0, _PROJ)      import 解析
              :217,230        subprocess(..., cwd=_PROJ)     git log -S
```

①只需要在子行程進入點加一行 `os.chdir(workspace)`。

#### 細則 A:`chdir` 必須在 `import` 之前

實測有三支模組**在載入當下就讀檔**:

```
make_web.py:12       D=json.load(open("data.json"))
make_charts.py:16    同上
build_native.py:13   同上
```

`import` 若發生在 `chdir` 之前,它們會讀到錯的檔。
**這是紀律不是改碼**:子行程進入點第一件事 `chdir`,然後才 import。
(這三支都在 C4 的退場清單上,問題會自然消失,但在那之前紀律要守。)

#### 細則 B:`core/migrate_syn.py` 是**建 seed 的工具**,不是 workspace runtime

它用 `cwd=_PROJ` 跑 `git log -S`,挖的是**工具自己的 `buckets.py` 演進史** ——
那是產品知識,不是使用者資料。所以它應該在 **app 打包時跑一次產生 seed taxonomy**,
不在使用者的 workspace 裡跑。使用者的 workspace 沒有那段 git 歷史,跑了也挖不到東西。

→ 對 §2.1 的影響:`seed/taxonomy/rules.json` 是 `migrate_syn` 的**建置產物**,
不是手寫的檔案。

### 0.2 不成立的部分:git 不能再當人審介面

現行設計有一根承重柱寫在多份文件裡:**「git diff 就是本專案的審核介面」**
(`rules.py` 開頭、`plan_phaseB.md` §2.1「`decisions/` 是 Ring 1 產物但要進 git,
它是審核對象」)。

那個假設的前提是「使用者 == 開發者」。Local-first 工作台的使用者
**不應該需要懂 git**(你自己的目標句就是這樣寫的)。

**解法(保留不變量,換掉介面)**:workspace 仍然是一個 git repo,由工作台
`git init` 並自動 commit —— 但**使用者永遠不打 git 指令**,
所有 diff 由 **UI 算出來、UI 畫出來**。git 從「介面」降級成「儲存與稽核基底」。

這樣「所有人工決定都可稽核、可回溯、可還原」這條不變量原封不動,
而使用者看到的是「這次更新改了什麼」的可讀畫面,不是 `git diff`。

### 0.3 唯一一件會打到你目標句的事:抄列需要 agent

你的目標句是「使用者只需做:選資料、按更新、看結果、處理待審」。

盤點發現一條寫死的專案決定([fill.py:19](../fill.py)):

> ⚠️ 不准呼叫任何模型 API(使用者已定案)。**讀表的是外部的 Claude Code agent**,
> 這支程式只做確定性的機械工作:找頁、驗收、擴張、歸檔、記進度。

也就是說:**從 PDF 讀出表格數字這一步,程式不做,是外部 agent 做的。**
所以「按更新」這個按鈕,對兩種情況的意義完全不同:

| 情境 | 能不能一鍵 | 為什麼 |
|---|---|---|
| 重跑分類 / 重新對帳 / 重建報表 / 換 taxonomy 後重算 | ✅ **完全自動** | 全是確定性運算,吃已有的 `facts/` |
| 匯入**新的** PDF、抄一個**沒抄過**的格 | ❌ **需要 agent 一段工** | 讀表是 agent 做的,程式只驗收 |

**我不打算隱藏這件事,因為隱藏它會做出一個按了會假裝在跑、實際卡住的按鈕。**
本計畫的做法是把它設計成**兩級作業**(§1.4),UI 誠實顯示
「這件事需要一段 agent 工作,這是指令 / 這是進度」。

你有兩個選項,**這需要你裁示**:

- **(甲)維持現況** —— 抄列永遠是 agent 的工。工作台負責「準備工單 + 收驗收結果 + 顯示進度」。
  新財報一年 2 次(H1 約 8 月、年報約隔年 3–4 月),一次 agent 工可以接受。
- **(乙)開放程式呼叫模型 API** —— 「按更新」才能真的端到端。
  但這會推翻一條已定案的鐵則,而且會讓「抄列品質」從 agent session
  的可審核過程變成黑箱呼叫。**我不建議**,但這是你的決定。

**本計畫以(甲)撰寫。** 若你選(乙),§1.4 與 §4 的 C3 要重寫。

> **2026-07-28 使用者已裁示:採(甲)。** 程式永不呼叫模型 API,讀表永遠是外部
> Claude Code agent 的工作。工作台的角色固定為**排程者 + 驗收者 + 進度顯示者**。
> C3 的作業模型照此撰寫,不留「未來也許自動抄列」的分支 —— 留了就會有人去接。

### 0.4 這個轉向划算的三個理由

1. **它把一個假的閘門拿掉了。** 現行的 I5「只發布 CONFIRMED」是為了保護
   **公開網站**不出錯。改成本機之後,「不可發布」自然變成「報表上標成待審」——
   使用者看得到那格有問題,而不是那格神秘消失。B3 那句
   「`status` 拆成已存檔與可發布兩個數字」在本機 UI 上是**兩欄**,不是兩個要解釋的抽象概念。
2. **它讓 360MB 的 `pdf_cache/` 有了正當歸宿。** 那是實測大小,現在被 `.gitignore`
   擋著,既不能進 git 又必須存在。Workspace 概念一出現,它就明確屬於「本機 runtime,
   可清除可重抓」。
3. **它移除了一整類根本不該存在的風險。** `bridge_v2/v3` 的寫入防護、
   `data.json.pre_bridge` 備份、「按下 --write 會發布一份 25 小時前的舊 verdict」——
   這些防護存在的唯一理由是「一個動作會不可逆地公開發布」。本機沒有這件事。

---

## 1. 本機使用者工作流

### 1.1 第一次開啟:建立 workspace

```
$ python3 -m core.workbench          # 或未來的單一啟動器
→ 找不到 workspace,詢問:要建在哪裡?  [預設 ~/財報工作台]
→ 建立目錄、複製 seed(§2.1)、git init、寫 workspace.json
→ 啟動本機伺服器 127.0.0.1:<port>,自動開瀏覽器
```

`workspace.json`(workspace 的身分證):

```json
{
  "schema": 1,
  "created_at": "...",
  "seed_version": "<app 版本 + seed 內容 sha256>",
  "app_version": "...",
  "workspace_id": "<uuid>"
}
```

`seed_version` 是為了回答「工具升級了,我的 workspace 要不要遷移」——
不記這個,日後 seed 的 taxonomy 改了會無聲地與使用者的 workspace 分岔。

### 1.2 預設資料要有哪些(seed 的內容)

| 內容 | 為什麼要內建 | 使用者可改? |
|---|---|---|
| `taxonomy/rules.json` 基線(83 條) | 沒有它,第一次使用等於從零開始標注 74 個科目名 | ✅ 複製進 workspace 後可改 |
| `taxonomy/derivations.json` | B1.5 批准後的推導規則 | ✅ 同上 |
| 銀行清單 / 期間定義 / 桶定義(現在在 `config.py`) | 產品知識,不是使用者資料 | ❌ 唯讀(改它等於改工具) |
| `BUCKET_RULES` 散文 | 分類規則的權威來源 | ❌ 唯讀,但 UI 要看得到 |
| `holdout` 名單 | 永不進報表的保留格 | ❌ 唯讀 |
| **frozen baseline**(`snapshots/`) | 回歸比對用:證明升級沒有改變既有數字 | ❌ 唯讀 |
| 範例 workspace(**選配**) | 讓使用者不必先有 PDF 就能看到工具長什麼樣 | 只讀,不可寫回 |

**不內建**:PDF(360MB,且各家財報公開可抓)、`facts/`(那是使用者的抽取成果)。

> ⚠️ 一個判斷:現在 repo 裡的 `facts/`(36 格)算 seed 還是使用者資料?
> **我的建議是 seed 的「範例 workspace」**,不是預設 workspace 內容 ——
> 它是你這台機器上的抽取成果,不是每個使用者都該憑空得到的東西。
> 但如果這個工具只有你自己用,把它當 seed 也完全合理。**這需要你裁示。**

### 1.3 選銀行、期間、更新 PDF

```
Update 頁
  ┌ 銀行  [✓國泰 ✓富邦 ✓中信 ✓兆豐 ✓玉山]
  ├ 期間  [2021H1 … 2025H1]  (格狀,已有資料的格子標色)
  ├ 分類  [Trading / OCI / AC]
  └ PDF   每一格顯示:已快取 / 未下載 / 來源 URL
           [取得 PDF] —— 抓進 pdf_cache/,記 sha256
```

PDF 的取得是確定性的(有 URL、抓下來、算 hash),**這一步可以一鍵**。
`core/store.py` 已經有 `PDF_DIR` 的概念,C3 把它接起來。

### 1.4 四種操作意圖(**這是 UI 最重要的一張表**)

使用者不該面對「要跑哪支腳本」,而是選**意圖**。四個意圖對應到明確的重跑範圍:

| 使用者選的 | 實際重跑 | 需要 agent? | 典型情境 |
|---|---|---|---|
| **只重建報表** | report | ❌ | 改了顯示設定、報表壞了 |
| **重跑分類 / 對帳** | decide → reconcile → report | ❌ | ratify 了新規則、改了 taxonomy |
| **更新資料** | 上面全部 + 抓新 PDF + 抄新格 | ⚠️ **新格才需要** | 新財報季 |
| **重新抽取某一份 PDF** | 該格 ingest → 下游全部 | ✅ **一定需要** | 懷疑某格抄錯 |

「需要 agent」的作業,UI 的行為是:

```
建立一張抄列工單 → 顯示狀態「等待 agent」
  ├ 顯示要在終端機執行的指令(可一鍵複製)
  ├ 背景監看 work/pending.json 的變化
  └ agent 完成 → 自動接續跑下游 → 狀態變「完成」
```

**工作台不假裝自己會抄列。** 它是排程者與驗收者,agent 是執行者。

### 1.5 只重跑必要步驟(輸入版本與 hash)

`build.py` 已經有 `_sha(*paths)` 與 `build_manifest.json` 的雛形 ——
C4 把它從「發布層的指紋」推廣成**整條管線的作業圖**:

```
 pdf(sha256)
     ↓  ingest      指紋 = pdf_sha + locate 版本 + 候選頁
 facts/{cell}       指紋 = 內容 sha256
     ↓  decide      指紋 = facts_sha + taxonomy_sha + decisions 程式碼版本
 decisions/{cell}
     ↓  reconcile   指紋 = facts_sha + decisions_sha + reconcile 版本
 verdict
     ↓  report      指紋 = verdict_sha + holdout + 報表模板版本
 out/report/
```

規則:**每個作業把「輸入指紋」寫進 `runs/<run_id>/manifest.json`。
重跑時比對指紋,相同就跳過並標「快取命中」。**

程式碼版本也要進指紋 —— 否則改了 `decide()` 卻因為 facts 沒變而跳過,
會得到一份用舊邏輯算的報表。這是很容易漏掉的一格。

⚠️ **「跳過」必須看得見。** UI 要顯示「7 格重算 / 29 格快取命中」,
不能靜靜跳過 —— 否則使用者無法分辨「沒變」和「沒跑」。

### 1.6 Review queue 的處置

沿用 `plan_phaseB.md` §5(B4)的三種處置,**但介面是 UI 不是 CLI**:

```
Review 頁,每一筆待審顯示:
  ├ 這是哪一格、哪一列、金額多少、佔該格幾 %
  ├ 原名 / 段落 / 來源頁(可直接開 PDF 該頁)
  ├ 系統提得出的候選桶 + 依據(rules.propose 的關鍵字 / 同義詞配對金額 / 算術等式)
  └ 三個按鈕:
       (a) 收錄成新科目 → 走 ratify(),寫 taxonomy,該 rule 轉 CONFIRMED
       (b) 退回(不是科目) → 標記,不再提示
       (c) 這是小計、頁沒找全 → **人工觸發 expand**
```

三條硬規則,直接來自 `plan_phaseB.md`,**UI 不得繞過**:

1. `(c)` 是**人**決定的,不是程式推論的;**人工觸發的擴頁不消耗重試預算**。
2. `(a)` 必須留下 human reference(誰、何時、依據什麼),**不准只有一個按鈕點擊**。
   UI 要有一個「依據」輸入框,空的不准送出 —— 這是 I3b 在 UI 上的樣子。
3. 分類未知**永不自動觸發 expand、永不消耗重試預算、永不丟棄 raw facts**。
   UI 可以顯示提示,**提示不得自動變成動作**。

---

## 2. 本機資料架構

### 2.1 三層:app / seed / workspace

```
<app 安裝目錄>                      ← 唯讀,使用者不該編輯
├── core/  buckets.py  rules.py  config.py  …     程式與產品知識
└── seed/
    ├── taxonomy/rules.json          分類規則基線(83 條)
    ├── taxonomy/derivations.json
    ├── snapshots/                   frozen baseline,回歸比對用
    └── example/                     (選配)範例 workspace

<workspace 根>  例如 ~/財報工作台/     ← 使用者的東西,git repo
├── workspace.json                   身分證(schema / seed_version / id)
├── pdf_cache/                       原始 PDF        [runtime,可清除可重抓]
├── anchors/                         錨值            [可重建]
├── facts/                           **原始事實**     [git,核心資產]
├── taxonomy/                        分類規則 + 批准  [git,核心資產]
├── decisions/                       occurrence 決定  [git,審核對象]
├── review/queue.jsonl               待處置佇列      [git]
├── work/                            抄列中繼        [runtime,rejected/ 例外進 git]
├── runs/<run_id>/                   執行紀錄與 manifest [runtime,保留 N 次]
└── out/                             報表產物        [不進 git,可重建]
    └── report/  index.html  report.json  manifest.json
```

### 2.2 三種資料,三種待遇

| 類別 | 判準 | 內容 | 刪掉會怎樣 |
|---|---|---|---|
| **核心資產** | 重建不出來,**丟了就是丟了** | `facts/` `taxonomy/` `decisions/` `review/` `work/rejected/` | 要重抄 PDF、重做人工裁示 |
| **本機 runtime** | 重建得出來,只是要時間/流量 | `pdf_cache/` `anchors/` `runs/` `work/*`(除 rejected) | 重抓重算即可 |
| **產物** | 純函數輸出,一定重建得出來 | `out/` | 按一下重建 |

**只有「核心資產」進 git。** 這與現況一致(實測:`facts/` 是唯一被 git 追蹤的資料目錄,
15 個檔;`results/` `pdf_cache/` `work/*` 都在 `.gitignore` 裡)——
workspace 的 `.gitignore` 直接沿用這個已經想清楚的分界。

判斷一份資料屬於哪一類,只問一句:**「刪掉之後,能不能只靠機器重建出逐位元組相同的內容?」**
能 → runtime 或產物;不能 → 核心資產。`facts/` 不能(要 agent 重讀 PDF),
所以它是核心資產,這也正是「**facts 不得被分類改寫**」這條不變量的成本理由。

### 2.3 workspace 不得覆寫 seed

三道,由弱到強:

1. **檔案權限** —— seed 目錄唯讀掛載/唯讀權限。
2. **程式層** —— 所有寫入路徑都是 workspace 相對路徑(`chdir` 之後自然成立);
   任何寫入若解析出的絕對路徑落在 app 安裝目錄內 → **raise**。
3. **啟動自檢** —— 每次啟動比對 seed 內容 sha256 與 `workspace.json.seed_version`。
   不一致 → 顯示「工具已升級,seed 有變更」並提供**逐項 diff**,由使用者決定
   要不要把新規則併進 workspace。**絕不自動覆蓋** —— 那會蓋掉使用者自己 ratify 過的東西。

### 2.4 備份 / 匯出 / 搬移

| 動作 | 做法 |
|---|---|
| **備份** | workspace 本身是 git repo → 每次作業結束自動 commit(訊息由作業類型產生)。使用者要的話可以再 push 到自己的私有 remote,**但那是選配,不是流程的一部分** |
| **匯出**(給人看) | `out/report/` 整包 —— 自足的 HTML + JSON + manifest,沒有外部依賴,可以直接寄出去 |
| **搬移**(換電腦) | 複製整個 workspace 目錄即可。`pdf_cache/` 可以不帶(360MB,能重抓);帶了就省流量 |
| **重置** | 「清除快取」只刪 runtime 三類;核心資產永不被這個動作碰到。UI 要明確列出「將刪除 X,保留 Y」 |

---

## 3. UI / 互動介面

### 3.1 形態:本機伺服器 + 瀏覽器,不做原生 App

```
python3 -m core.workbench
  → 綁定 127.0.0.1:<自動選 port>,**不綁 0.0.0.0**
  → 自動開瀏覽器
  → 伺服器單使用者、無帳號、無認證(因為只聽 loopback)
```

三個刻意的限制:

- **只綁 127.0.0.1** —— 不是設定選項,是寫死的。綁 0.0.0.0 等於在區網上開一個
  無認證的檔案讀寫介面。
- **後端只做兩件事**:啟動/監看子行程作業、讀 workspace 的檔案給前端。
  **業務邏輯一律在 `core/`**,伺服器不得有第二份。
- **前端先用 server-rendered HTML + 少量原生 JS**,不引入前端框架與建置流程。
  理由與專案一貫立場一致:多一層建置就多一層「差異來自哪裡」分不清的地方。

### 3.2 六個頁面

**① Dashboard —— 一眼看懂現在的狀態**

```
資料覆蓋率   36 / 45 格   (5 銀行 × 3 分類 × 3 期間,缺的格子標出來)
可入報表     21 格        待審 12 格      未分類 3 格
最後更新     2026-07-28 10:00   (哪個作業、跑了多久)
執行狀態     ● 閒置 / ◐ 執行中(進度) / ▲ 等待 agent / ✗ 失敗
待辦         12 筆待審 → [去處理]
```

「可入報表 / 待審」兩個數字**並排顯示**,這就是 `plan_phaseB.md` §5 B3 說的
「`status` 拆成已存檔與可發布兩個數字」—— 在 UI 上它天然是兩欄,不需要解釋。

**② Update / Run —— 選資料 + 選意圖**

上半:銀行 × 期間 × 分類的格狀選擇器,每格顯示狀態色。
下半:§1.4 的四個意圖按鈕,每個按鈕**按下前**先顯示「將會重跑什麼、跳過什麼、
需不需要 agent」的預覽 —— **預覽是必要的,不是貼心**:它讓使用者在動手前
看見「這個動作會不會蓋掉我的東西」。

**③ Review —— 三種處置**(內容見 §1.6)

**④ Results —— 報表與差異**

- 本機 HTML 報表(現在 `make_web.py` 產的那些圖表,渲染到本機)
- **與上一次 build 的差異**:哪些格變了、變多少、為什麼變
  (taxonomy 改了?facts 重抄了?)—— 這一頁回答「我按了更新,到底改了什麼」
- 待審的格子在報表裡**標記出來**,不是消失

**⑤ Trace —— 任一數字回推到來源**(這是這個工具真正的價值)

點報表上任何一個數字:

```
報表數字  玉山 2024 OCI 金融債 131,465,522
    ↓ 由哪些 decision 加總
decision  cell=202404_玉山_個體|OCI  row_fp=a3f…  mapping=金融債  state=CONFIRMED
    ↓ 依據哪條 taxonomy rule
rule      tax:金融債券(註二) → 金融債   state=CONFIRMED
          references: rule「BUCKET_RULES 關鍵字『金融債券』」
                      + human「2026-07-28 使用者批准 deriv:…-v1」
    ↓ 來自哪個 raw fact
fact      facts/202404_玉山_個體.json  rows[3]  name=金融債券（註二）
    ↓ 抄自哪一頁
pdf       pdf_cache/…pdf  p126   [開啟 PDF 該頁]
```

技術上這條鏈**已經全部存在了**,只是還沒接起來:
`core/decisions.py` 的 `locator` / `record_fp` / `row_fp` 就是為此而設計
(`plan_phaseB.md` §2.2:「locator 是人類可讀的定位」)。
Trace 頁是 locator 這個設計第一次真正被使用者看見。

**⑥ Data —— 可讀檢視,不要求使用者看 JSON**

| 檢視 | 內容 |
|---|---|
| PDF | 已快取清單、頁數、sha、來源、內嵌檢視器 |
| Facts | 表格化的 rows(不是 JSON),每列可跳 Trace |
| Taxonomy | 83 條規則的表格:名字 / 桶 / 狀態 / 證據種類 / 是誰何時批准的 |
| Snapshot | 歷次 build 的清單與兩兩差異 |

---

## 4. C3 / C4 的重新定義

### 4.1 C3:從「搬移 ingest」變成「本機作業編排」

**原定義**(`plan_clean_core.md` §2.5):
`ingest` + `route` + `state/`,閘門 = E5 綠 ∧ 3 個新格實跑 ∧ 四條出口實跑 ∧ T-R4 綠。

**新定義**:上面全部保留,**再加上作業編排層**。

```
core/ingest.py     零行為搬移 fill.py 的 ingest/routing   ← 原本就要做,不變
core/jobs.py       **新增**:作業圖 + 指紋快取 + 子行程執行 + runs/ 紀錄
core/workbench/    **新增**:127.0.0.1 伺服器 + 六個頁面
```

`core/jobs.py` 的職責,寫死三條:

1. **每個作業是一個子行程,`cwd` = workspace**(§0.1 的決定)。
2. **每個作業宣告輸入指紋**,相同就跳過並標「快取命中」(§1.5)。
3. **需要 agent 的作業不假裝自己會做** —— 建立工單、顯示指令、監看結果(§1.4)。

閘門新增:

```
[ ] 同一輸入連跑兩次:第二次全部快取命中,out/ 逐位元組相同
[ ] 注入:改 taxonomy 一條 → 只有下游重跑,ingest 不重跑
[ ] 注入:改 decide() 程式碼 → 即使 facts 沒變也必須重跑(程式碼版本進指紋)
[ ] 作業失敗 → runs/ 留下完整 log,workspace 核心資產未被寫壞
[ ] 任何寫入解析出的絕對路徑落在 app 目錄內 → raise
```

### 4.2 C4:從「publish to website」變成「build local report」

**原定義**:`publish` + `cli` + `data` 改成同源投影,閘門 E4 = 與 `build.py --diff`
逐位元組相同。

**新定義**:

```
core/report.py     由 verdict + decisions 產生本機報表產物
out/report/
  ├── index.html      自足(CSS/JS 內嵌,無外部依賴,離線可看)
  ├── report.json     結構化資料,給 Trace 與程式化使用
  └── manifest.json   **可追溯清單**
```

`manifest.json` 必須包含(這是「所有結果可回推來源」的載體):

```
run_id / 產生時間 / app 版本 / workspace_id
每個輸入的 sha256:  pdf / facts / taxonomy / decisions / holdout
每個作業的:        指紋、是否快取命中、耗時
報表每個數字的:     來源 decision id 清單
排除項:            holdout 名單、待審而未入表的格 + 原因
```

**E4 閘門怎麼改**:原本是「與現行 `build.py` 逐位元組相同」。
現在產物形態變了,逐位元組沒有意義。改成:

```
[ ] **數值等價**:新報表的每一格數字,與現行 build.py 產的 data.json 逐格相同
    (形態可以變,數字不准變 —— 這才是等價閘門真正要守的東西)
[ ] manifest 覆蓋率:報表上每一個數字都追得回 ≥1 個 decision,無孤兒
[ ] 離線可看:斷網開 index.html 完全正常
```

### 4.3 現有發布層的去留與退場順序

| 檔案 | 現況(實測) | 去留 | 何時 |
|---|---|---|---|
| `更新網站.command` | 呼叫 `bridge_v2.py`,而它已凍結會 raise → **這支現在就是壞的** | **刪** | **立刻**,不必等 C3 |
| `bridge_v2.py` | `main()` 已改成 raise,`_main_frozen()` 保留當快照來源說明 | 刪 | C5 |
| `bridge_v3.py` | `--write` 已擋。但 `cell_of()` / `to_yi()` **還被 `build.py` import** | 兩個函式搬進 `core/report.py`,再刪本檔 | C4 |
| `build.py` | `data.json` 的唯一寫入者;有 `_sha` 指紋雛形 | 職責搬進 `core/report.py` + `core/jobs.py` | C4 |
| `data.json` | 96K,進 git,現在是網站的資料源 | 降級成 `out/report/report.json` 的**一種 export 格式**,不再是真相 | C4 |
| `make_web.py` | 直接 `json.load("data.json")` 產網頁 | 改寫成本機報表 renderer(吃 `report.json`) | C4 |
| GitHub Pages / `site/` | 現行公開發布出口 | **移出主流程**,變成 `export --github-pages` 選配 | C4 之後,不急 |
| `app.py` / `build_native.py` / `銀行債券_*.xlsx` | 更早的 exe + Excel 產線,與 v3 管線無關 | 盤點後決定;**不在本計畫範圍** | 另議 |

**退場順序的原則**(沿用 `plan_clean_core.md` §4):
**每刪一個檔,重跑全部閘門。** 且 `bridge_v3.py` 必須等 `cell_of/to_yi` 搬完才刪 ——
現在刪會直接打斷 `build.py`。

---

## 5. 不變量(逐條對應到閘門)

你列的八條,我對應到**已經有測試 / 還沒有測試**,沒有測試的就是後面幾輪要補的:

| # | 不變量 | 現況 | 缺什麼 |
|---|---|---|---|
| 1 | **facts 不被分類改寫** | ✅ 每份施工單都有 `git diff facts/` 為空 | 執行期強制:任何寫入 `facts/` 的路徑必須經 Gate 1(B2) |
| 2 | **decisions / review / taxonomy 分開** | ✅ 目錄契約已定(`plan_phaseB.md` §2.1) | `decisions/` 目錄還沒真的產生(B2 才開始寫) |
| 3 | **未知 ≠ OTHER / null / 0** | ◐ `wide.view()` 有 `unknown` + `View.ok` | I4 注入測試(B3);**UI 上要顯示成「待審」而不是消失** |
| 4 | **agent 不直接寫正式結果** | ✅ `fill.py` 已如此:agent 寫 `work/`,驗收過才進 `facts/` | decisions 層要比照:agent 不得直接寫 `decisions/` |
| 5 | **所有結果可回推來源** | ◐ `locator` / `record_fp` / `row_fp` 型別已備(B0) | manifest + Trace 頁(C4)。**閘門:報表無孤兒數字** |
| 6 | **本機不需上傳** | ✅ 轉向後天然成立 | 綁 127.0.0.1 寫死;export 必須是明示動作 |
| 7 | **build 是唯一產生報表資料的入口** | ✅ `build.py` 已是 `data.json` 唯一寫入者,bridge 都已凍結 | C4 移交給 `core/report.py` 時保持唯一 |
| 8 | **重跑不得無聲覆寫 raw facts 或人工確認** | ◐ 設計已有(`facts/_superseded/`,B2 §4.3) | 尚未實作。**UI 層再加一道**:覆寫前顯示 diff 並要求確認 |

### 5.1 「not confirmed」是顯示狀態,不是隱藏條件(**2026-07-28 裁示**)

Phase B 的 I5 寫的是「**正式發布只允許全格 CONFIRMED**」。那條規則的動機是保護
**公開網站**不出錯 —— 網站上一個沒把握的數字,讀者無從分辨。

Local-first 之後這個動機消失了,因為**使用者就是那個知道狀況的人**。所以:

```
舊(發布模型)   不是 CONFIRMED → 該格不可發布 → 從產出中消失
新(工作台模型) 不是 CONFIRMED → 照樣進報表,但**標成 not confirmed** → 使用者看得到
```

三條硬規則:

1. **報表不得因為 not confirmed 就隱藏數字。** 隱藏會讓使用者以為那筆錢不存在 ——
   那比顯示一個標了記號的數字危險得多。
2. **每個數字都必須帶得出狀態**:`CONFIRMED` / `PROVISIONAL` / `UNCLASSIFIED`。
   Dashboard 的「可入報表 / 待審 / 未分類」三個數字就是這個狀態的彙總。
3. **export 時狀態必須跟著走。** 若日後真的要匯出給外人看,not confirmed 的部分
   要嘛帶著標記,要嘛明確排除並在 manifest 列出 —— **不准靜靜消失**(第 9 條)。

**對 B1.5 的實際影響**:因為 not confirmed 不再讓資料消失,
**你不需要為了「讓數字出得來」而勉強批准任何東西**。
批准的意義回到它本來該有的樣子:**「我確認過這條規則」**,而不是「我需要這格出現」。
第 3 批那 3 條(政府債券 / 貨幣交換 / 外匯換匯合約)可以**永遠停在 not confirmed**,
報表照樣有它們的數字,只是帶著記號。這正是 `plan_phaseB.md` §3.3 說的
「問不出來就停在 PROVISIONAL」在本機模型下的自然結果。

**我要加第 9 條**(local-first 才出現的):

> **9. 任何「跳過」必須看得見。** 指紋快取命中、holdout 排除、待審未入表 ——
> 三者都必須在 UI 與 manifest 裡列出來。
> 理由與這個專案一路的立場一致:**看不見的跳過就是恆真閘門**。
> 使用者分不出「沒變」和「沒跑」,就會信任一份其實沒更新的報表。

---

## 6. 最小可行實作順序

### 6.1 現在可以繼續做、**完全不受影響**的

**F1 / F2 / F3 工單(`docs/brief_phaseB_B1fix_ratify.md`)原封不動照跑。**
理由:它動的是 `core/migrate_syn.py` `core/ratify.py` `taxonomy/` 與測試,
**沒有一個碰到路徑、UI、發布層**。`ratify()` 在 local-first 架構裡照樣是
「唯一能產生 CONFIRMED 的入口」,只是日後多一個 UI 呼叫它而已。

同樣不受影響:**B1.5(你本人批准)**、B2 的語意設計、B3、B4 的三種處置邏輯。

> 換句話說:**這個轉向不需要你停下任何正在進行的工作。**

### 6.2 必須在 **C3 之前**決定的(四件)

| # | 決定 | 我的建議 |
|---|---|---|
| D1 | workspace 根目錄怎麼解析 | **`chdir` + 子行程**,不做路徑注入(§0.1) |
| D2 | agent 邊界 —— 甲案還是乙案 | **甲案**(維持不呼叫模型 API)(§0.3) |
| D3 | `runs/` 的 layout 與保留策略 | 每次作業一個目錄,保留最近 N 次,可清除 |
| D4 | 現有 36 格 `facts/` 算 seed 還是使用者資料 | 傾向「範例 workspace」,但你自用的話當 seed 也行(§1.2) |

D1、D2 是硬的 —— 錯了整個 C3 要重寫。D3、D4 改起來便宜。

### 6.3 必須在 **C4 之前**決定的(三件)

| # | 決定 | 我的建議 |
|---|---|---|
| D5 | 報表產物契約(HTML / JSON / manifest 的欄位) | 先把 manifest 欄位定死(§4.2),HTML 可以慢慢長 |
| D6 | `data.json` 的命運 | 降級成 export 格式,保留一段時間當回歸比對基準 |
| D7 | Trace 的 id 方案 | 直接用 B0 已經有的 `record_fp` / `row_fp`,**不要另發明一套 id** |

### 6.4 可以最後才做的

報表差異檢視器、PDF 內嵌檢視、Data 頁的美化、export to GitHub Pages、
範例 workspace、多 workspace 切換、深色模式。

**這些一個都不擋 C3/C4。** 先做會拖慢真正的骨架。

### 6.5 建議的導入順序

```
第 0 輪(現在)   F1/F2/F3 → B1.5(你批准)          ← 與本計畫無關,照跑
第 1 輪          決定 D1–D4;刪 更新網站.command
第 2 輪  C3-a    core/ingest.py(原定的零行為搬移,E5 閘門不變)
第 3 輪  C3-b    core/jobs.py(作業圖 + 指紋快取 + 子行程)—— **無 UI,純 CLI 可驗**
第 4 輪  C3-c    workbench 伺服器 + Dashboard + Update/Run  ← 第一次看得見東西
第 5 輪  B2/B3/B4 的語意工作(在 core.ingest 上改)+ Review 頁
第 6 輪  C4      core/report.py + manifest + Results/Trace 頁
第 7 輪  C5      退場:bridge_v2/v3、data.json、make_web
```

⚠️ **第 3 輪(`jobs.py`)刻意排在 UI 之前,而且要求純 CLI 可驗。**
先做 UI 會讓作業圖的正確性藏在點擊行為後面,測不動。
指紋快取這種東西,錯了會「靜靜給你一份舊報表」—— 正是這個專案最怕的那種錯。

---

## 7. 最終使用者流程圖

```
┌─────────────────────────────────────────────────────────────────┐
│  使用者操作(瀏覽器 127.0.0.1)                                  │
│    選銀行/期間 → 選意圖 → [預覽會跑什麼] → 按下                  │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  本機 workspace(~/財報工作台,git repo)                          │
│    pdf_cache/   anchors/   facts/   taxonomy/   decisions/       │
│    review/      work/      runs/    out/                         │
│         ↑ seed 唯讀複製而來,啟動時比對版本,絕不自動覆蓋          │
└───────────────────────────┬─────────────────────────────────────┘
                            ↓  core/jobs.py:比對指紋,只跑必要的
┌─────────────────────────────────────────────────────────────────┐
│  core pipeline(子行程,cwd = workspace)                         │
│                                                                  │
│   locate ─→ ingest ─→ facts ─→ decide ─→ reconcile ─→ report     │
│               ▲                   │                              │
│               │                   ↓                              │
│         [需要 agent]        UNCLASSIFIED /                       │
│          抄列工單            PROVISIONAL                          │
│          Claude Code               │                              │
└────────────────────────────────────┼─────────────────────────────┘
                                     ↓
┌──────────────────────────┐   ┌─────────────────────────────────┐
│  Review(待審)            │   │  Report(本機 HTML + JSON)      │
│   (a) 收錄 → ratify()    │   │   Dashboard / Results / Trace   │
│   (b) 退回               │   │   每個數字都追得回 PDF 頁        │
│   (c) 人工 expand ───────┼──→│   待審的格子**標記**而非消失     │
│   ↳ 人工決定寫回 taxonomy │   └──────────────┬──────────────────┘
└──────────────────────────┘                  │
                                              ↓  (選配,明示動作)
                                    ┌──────────────────────┐
                                    │  Export              │
                                    │   整包 HTML / xlsx   │
                                    │   GitHub Pages(選配)│
                                    └──────────────────────┘
```

**日常使用者只碰最上面那一層與 Review**:選資料、按更新、看結果、處理待審。
CLI、JSON、git、發布腳本全部在下面,而且**不需要理解就能用**。

---

## 8. 需要你裁示的六件事(彙整)

### 已裁示(2026-07-28)

| # | 問題 | **裁示** | 落在哪 |
|---|---|---|---|
| 1 | agent 邊界 | **甲案** —— 程式永不呼叫模型 API | §0.3、§4.1 |
| 2 | workspace 路徑模型 | **chdir**(三條規則見 §0.1) | §0.1 |
| 3 | not confirmed 怎麼處理 | **當顯示狀態,不當隱藏條件**;可永遠停在 not confirmed | §5.1 |

### 仍待裁示

| # | 問題 | 我的建議 | 不決定會怎樣 |
|---|---|---|---|
| 4 | 現有 36 格 facts 算 seed 還是使用者資料 | 範例 workspace(自用當 seed 也行) | seed 內容定不下來,C3 前要決定 |
| 5 | `runs/` 保留策略(留幾次、怎麼清) | 留最近 N 次,UI 可清除 | C3 前要決定,但改起來便宜 |
| 6 | `data.json` 留多久 | 留到 C4 當回歸基準,之後降 export | 太早刪就沒有數值等價的對照 |
| 7 | GitHub Pages 完全退場,還是留選配 export | 留選配,但移出主流程 | 影響 C4 的產物契約 |
| 8 | `app.py` / `build_native.py` / xlsx 那條舊產線 | 另議,不在本計畫 | 現在不決定沒關係 |
