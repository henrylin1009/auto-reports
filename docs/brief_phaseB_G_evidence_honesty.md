# 施工單 —— G:第 3 批證據誠實化(收尾單)

> 給執行者(Sonnet)。上游:`docs/brief_phaseB_B1fix_ratify.md`(F1/F2/F3,已完成)。
> **衝突時以本單為準,不確定就停下來問,不要自行裁示。**
>
> 本單**只有一步**,而且很小:把第 3 批那 3 條 rule 的假證據拿掉,讓 `M3` 轉綠。
> **做完就停,一次性回報。**
>
> **不得執行 `ratify()` 去批准任何東西。** 那是 B1.5,使用者本人的動作。
> 本單產出必須仍然是 **CONFIRMED 0 條、`derivations.json` 仍為 `[]`**。

---

## 0. 先讀這段(硬性約束)

### 0.1 絕對不准做

| 禁止 | 原因 |
|---|---|
| 修改 `locate.py` `bs_anchor.py` `transcribe.py` `wide.py` `buckets.py` `rules.py` `synonyms.py` `facts.py` `holdout.py` `config.py` `make_web.py` `results.py` `build.py` `bridge_v2.py` `bridge_v3.py` `fill.py` `pipeline.py` | 已驗證的底層能力。**唯一合法的重用方式是 `import`** |
| 修改 Phase A 的 `core/` 既有檔(`units.py` `expand_policy.py` `contracts.py` `store.py` `reconcile.py` `cli.py`) | 等價閘門已經綠了 |
| 修改 `core/decisions.py` | B0 的 24 項注入測試綠著。**本單完全不需要動它**(見 §2.2) |
| 修改 `core/ratify.py` | F3 剛做完,R1–R11 全綠。本單不碰 |
| **執行 `ratify()` 批准任何 rule 或 derivation** | 那是 B1.5,使用者本人的動作 |
| 改寫 `facts/` —— **一個 byte 都不准變** | facts 是原始層 |
| 跑 `build.py` / `bridge_v3.py` / 任何 `--write` | 會動到已發布的 `data.json` |
| 測試寫進真實 `facts/` `taxonomy/` `decisions/` | 一律寫 tmp,測完還原 |
| 呼叫任何模型 API | 使用者已定案:程式不呼叫 |
| 「順手」重構、改名、整理 | 等價閘門會分不出差異來自搬家還是整理 |
| 為了讓測試變綠而放寬測試 | **本單的重點就是不放寬 M3**。見 §2.3 |
| 做 C3 / C4 / B2–B5 / 任何工作台 / 伺服器 / UI | 不在本單 |

### 0.15 `docs/plan_local_first.md` 不影響本單

`docs/` 裡有一份 local-first 轉向計畫(產品改成本機工作台,不再以 GitHub Pages
為目標),使用者已裁示三件事(chdir / 甲案 / not confirmed 當顯示狀態)。
**那份計畫改的是 C3 / C4 與發布層,與本單無關。**

**看到它不要開始做工作台、伺服器、UI、workspace、chdir 的任何東西。**
本單只動 `core/migrate_syn.py` 與兩個測試檔。

### 0.2 環境

```bash
source .venv/bin/activate
```

沒有 pytest。測試是可執行腳本,`python3 test_x.py`,exit 0 = 綠。
`test_e2_equiv.py` 約 60 秒要跑;`test_build.py` 約 460 秒,**本單不必跑**。

### 0.3 現況(2026-07-28 實測,不要重新推導)

```
taxonomy/rules.json        83 條,全部 PROVISIONAL   (CONFIRMED 0)
taxonomy/derivations.json  []
工單三批                    68 / 12 / 3
applies_to                 68(含 5 條 group,0 條 generic)

測試現況:
  test_decisions.py           24 項全綠
  test_ratify.py              20 項全綠(R1–R11)
  test_decide_equiv.py        583/583 相同
  test_taxonomy_migration.py  16 綠 / **1 紅(M3)**   ← 本單要修的
  九支既有 + Phase A 六支      全綠
```

`M3` 現在紅在這 3 條(實測輸出逐字):

```
FAIL M3: all rule/synonym/arithmetic rechecks pass when re-run: 3 failures:
  tax:政府債券   kind='rule' has recheck=None — dishonest evidence
  tax:貨幣交換   kind='rule' has recheck=None — dishonest evidence
  tax:外匯換匯合約 kind='rule' has recheck=None — dishonest evidence
```

它們現在的實際內容:

```
tax:政府債券     mapping=公債   state=PROVISIONAL
    references[0]  kind="rule"  recheck=None
                   detail="無可重驗證據 — 需人工裁示 (§B1 第3批)"
```

---

## 1. 為什麼要修(讀完再動手)

`detail` 自己寫著「**無可重驗證據**」,`kind` 卻標成 `"rule"` ——
而 `"rule"` 在本專案的語意是「**可機械重驗**」(`plan_phaseB.md` §2.3:
`recheck` 存下可重跑的驗算式,CI 就能對每一條 reference 重驗)。

**同一筆資料的兩個欄位互相矛盾。** 這不是「兩種都說得通」的選擇題,是 bug。

而且 `plan_phaseB.md` §3.5 的閘門原文早就寫了正確做法:

> `[ ] 74 + 5 + 4 條逐條有 ≥1 reference,**或明確標為「無證據」**`

「無證據」這個出口計畫裡本來就有,只是遷移程式沒用它。
F2 只授權修 4 條 GENERIC,前一輪的執行者守住授權沒有越權(**這是對的**),
本單就是把剩下 3 條補完。

> ⚠️ **這 3 條與 GENERIC 那 4 條不是同一件事,不要混。**
> GENERIC(其他 / 其他項目 / 其他(註) / 其他(註一))是**通稱判斷**,
> F2 已改成 `kind="group"` 並說明主張內容。
> 本單這 3 條是**真的沒有任何證據** —— 連主張都還沒有人提出來。
> 兩者的正確標記法不同,**不要把這 3 條也改成 `kind="group"`**。

---

## 2. 步驟 G1 —— 第 3 批標成「無證據」

### 2.1 使用者裁示的做法(2026-07-28)

> **不要再給它們一個假裝可重驗的 reference。狀態本來就是 PROVISIONAL
> (= not confirmed),誠實地讓證據欄空著。**

具體:第 3 批那 3 條 rule 的 `references` 改成 **空 list `[]`**,
`state` 維持 `PROVISIONAL`,`mapping` 維持不變。

改完之後這 3 條讀起來是:

```
政府債券 → 公債   PROVISIONAL   references: []      (無任何證據,待人工裁示)
```

**這就是「not confirmed」的字面樣子**,不需要新欄位、不需要新 kind。

### 2.2 為什麼不需要動 `core/decisions.py`

`REFERENCE_KINDS` 是 B0 凍結的常數,**不准新增 kind**。
`TaxonomyRule` 的欄位也是 B0 凍結的,**不准加 `no_evidence` 之類的新欄位**。

空的 `references` 已經足夠表達,而且**行為上正好正確**:
`validate_rule()` 要求 `state=="CONFIRMED"` 的 rule 必須有 ≥1 條 `kind=="human"`
的 reference(I3b)。空 references 的 rule 因此**在型別上就不可能變成 CONFIRMED**,
除非有人跑 `ratify_rule()` 幫它加一條 human reference —— 那正是我們要的行為。

**若你發現空 `references` 會讓 `core/decisions.py` 或 `core/ratify.py` 出錯,
停下來回報,不要去改那兩支。**

### 2.3 測試要怎麼改(**只有這一處授權**)

| 測試 | 怎麼改 | 為什麼不是放寬 |
|---|---|---|
| `M1` | 現在斷言「每條有 ≥1 reference **或明確標為無證據**」。要確認空 `references` 走的是「無證據」那條分支,**且該分支有被真的走到**(印出是哪 3 條) | 計畫 §3.5 原文就有這個出口 |
| `M3` | **判準一個字都不准改**。它應該因為假 reference 消失而自然轉綠 | 這是本單的重點:**靠修資料轉綠,不靠改判準轉綠** |

⚠️ **`M3` 若不是自然轉綠,而是你動了它的判準才綠 —— 那就是本單失敗。**
判準是 F2 定的:「`kind` ∈ {rule, synonym, arithmetic} 的 reference 必須有非空 recheck」。
這句話是對的,不准為了配合資料而鬆動它。

### 2.4 新增一條防回歸的不變式

加進 `test_taxonomy_migration.py`:

| # | 命題 | 注入什麼 |
|---|---|---|
| M11 | **第 3 批(無機械證據)的 rule,`references` 必須是空的;反之,`references` 空的 rule 必須都在第 3 批** | 給第 3 批某條塞一個假的 `kind="rule"` reference → **必須紅** |

> M11 是雙向的,這是刻意的。單向(「第 3 批必須空」)擋不住「把有證據的條目
> 誤清成空的」那個方向的錯。

### 2.5 工單要跟著重新產生

```bash
python3 -m core.migrate_syn        # 或該檔既有的進入點,照它原本的跑法
```

`out/ratify_worklist.md` 的第 3 批那一段,要能看出這 3 條是**零證據**,
不是「有一條寫著無證據的 rule 證據」。三批數字 **68 / 12 / 3 不變**。

---

## 2.6 步驟 G2 —— `migrate_syn` 不得覆寫人工批准(**新增,重要**)

### 為什麼

`core/migrate_syn.py` 的 `write_outputs()` 是**整檔覆蓋**(實測 :552):

```python
with open(rules_path, "w", encoding="utf-8") as f:   # ← "w",全檔重寫
    json.dump(rules_clean, f, ...)
...
derivations_output = result["derivations"]           # Always []
```

也就是說:**使用者做完 B1.5 之後,任何人再跑一次遷移,
68 條 CONFIRMED 會全部被打回 PROVISIONAL,`derivations.json` 被寫回 `[]`,
而且不會有任何警告。**

這直接違反使用者列的不變量第 8 條:
**「使用者選擇重跑時不得無聲覆寫 raw facts 或人工確認」**。

今天還沒發作,只因為現在 CONFIRMED 是 0。**B1.5 之後就會發作,而且是靜默的。**

### 要做什麼

在 `write_outputs()` 加一道**寫入前檢查**:

```
若既有的 taxonomy/rules.json 含任何 state=="CONFIRMED" 的 rule
或既有的 taxonomy/derivations.json 非空
    → **raise**,訊息要說清楚:
       「偵測到 N 條已批准的 rule / M 條 derivation。
         重跑遷移會覆寫人工批准。若確定要重來,先備份 taxonomy/ 再用 <明確的旗標>。」
```

三條要求:

1. **預設是拒絕,不是警告。** 印一行警告然後照樣覆寫,等於沒有防護。
2. **要有明確的覆寫出口**(例如 `--force` 或 `allow_overwrite=True` 參數),
   但**預設關閉**,且訊息要提示先備份。
3. **不准改成 merge。** 自動合併「機器產生的規則」與「人批准過的狀態」是個
   看起來聰明、實際上會靜靜弄錯的設計。拒絕 + 人工決定才是對的。

### 測試

| # | 命題 | 注入什麼 |
|---|---|---|
| M12 | 既有 rules.json 含 CONFIRMED 時,`write_outputs` **raise** 且**不寫入任何檔案** | 讓它照樣覆寫 → **必須紅** |
| M13 | 既有 derivations.json 非空時,`write_outputs` **raise** 且不寫入 | 同上 |
| M14 | 明確指定覆寫旗標時,才允許寫入 | — |

⚠️ **M12/M13 要驗「不寫入」而不只是「有 raise」。** 先 raise 後半途寫壞檔案
是常見的實作錯誤 —— 檢查必須在任何寫入動作**之前**完成。
**一律在 tmp `taxonomy_dir` 測,不准碰真實 `taxonomy/`。**

---

## 3. 驗收

```
[ ] taxonomy/rules.json:第 3 批 3 條的 references == []
[ ] taxonomy/rules.json:83 條,**全部 PROVISIONAL**(CONFIRMED 仍為 0)
[ ] taxonomy/derivations.json 仍為 []
[ ] out/ratify_worklist.md 三批仍是 68 / 12 / 3,第 3 批顯示為零證據
[ ] test_taxonomy_migration.py **全綠**,且 M3 是「資料修好所以綠」不是「判準放寬所以綠」
[ ] M1 印出走「無證據」分支的是哪 3 條
[ ] M11 綠,「注入 → 紅」貼一段
[ ] test_decisions.py 24 項全綠(未動 core/decisions.py)
[ ] test_ratify.py 全綠(未動 core/ratify.py)
[ ] test_decide_equiv.py:583 列逐列相同
[ ] git diff facts/ 為空
[ ] git status:只有 core/migrate_syn.py、test_taxonomy_migration.py、
    taxonomy/rules.json、out/ratify_worklist.md 的變更

G2:
[ ] write_outputs 在既有 CONFIRMED / 非空 derivations 時 raise,且**未寫入任何檔案**
[ ] 有明確的覆寫出口,但**預設關閉**
[ ] M12 / M13 / M14 綠,M12 與 M13 的「注入 → 紅」各貼一段
[ ] 全程在 tmp taxonomy_dir 測,真實 taxonomy/ 未被測試碰過
```

---

## 4. 回報格式

**一次性回報。** 跑完下面這張總表之後才回報一次。

```bash
# ① 本單
python3 test_taxonomy_migration.py   # 必須全綠,含新增的 M11
python3 test_decide_equiv.py         # 583 列逐列相同

# ② 回歸(不該被本單影響)
python3 test_decisions.py            # 24 項
python3 test_ratify.py               # R1–R11

# ③ 九支既有
for t in test_cross.py test_facts.py test_rules.py test_synonyms.py \
         test_wide.py test_locate.py test_gap.py test_drive.py test_pipeline.py; do
  printf "%-18s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ④ Phase A 六支(test_e2_equiv.py 約 60 秒,要跑)
for t in test_units.py test_expand_policy.py test_contracts.py \
         test_e2_equiv.py test_ring.py test_rulings.py; do
  printf "%-20s " "$t"; python3 $t >/tmp/o 2>&1 && echo OK || { echo FAIL; tail -3 /tmp/o; }
done

# ⑤ 唯讀證明
git diff --stat facts/ buckets.py config.py rules.py synonyms.py \
                core/units.py core/expand_policy.py core/contracts.py \
                core/store.py core/reconcile.py core/decisions.py core/ratify.py
python3 -c "import json; d=json.load(open('taxonomy/derivations.json')); \
            r=json.load(open('taxonomy/rules.json')); \
            print('derivations:', d); \
            print('CONFIRMED:', sum(1 for x in r if x['state']=='CONFIRMED')); \
            print('空references:', [x['rule_id'] for x in r if not x['references']])"
# 必須印出 derivations: []  /  CONFIRMED: 0  /  空references 恰好是第 3 批那 3 條
```

**任何一項紅了,不要修判準,回報它。**

### 回報這四段

1. **驗收 checklist**,逐條打勾或說明為什麼沒打勾。
2. **M3 轉綠的證明** —— 要能看出是資料修好而不是判準放寬。
   建議做法:貼出 `test_taxonomy_migration.py` 中 M3 判準的前後 diff
   (**應該是「無變更」**),以及 M3 的實測輸出。
3. **M11 的「注入 → 紅」實測輸出**一段。
4. **遇到的意外**:任何「規格說 A、實際是 B」的地方。**不要自行裁示,列出來。**

---

## 5. 做完之後(給使用者,執行者不必做)

本單綠了之後,整個 Phase B 的 B0 / B1 就真的收乾淨了:
83 條 rule 逐條有誠實的證據標記、`ratify()` 工具就緒、CONFIRMED 仍為 0。

**下一步是 B1.5 —— 使用者本人批准。** 執行者要做的只有一件事:
在回報最後附上 **`ratify_rule()` / `ratify_derivation()` 的實際呼叫範例**
(參數順序、必填欄位、跑完怎麼驗證),讓使用者可以直接照著下指令。
**不准替他跑,不准先幫他填 `approved_by` 或 `reason`。**

---

## 6. 常見誤區

| 誤區 | 正解 |
|---|---|
| 把這 3 條也改成 `kind="group"`(跟 GENERIC 一樣) | §1 的警告:GENERIC 是通稱判斷,這 3 條是**零證據**。標記法不同 |
| 為這 3 條補一個「會通過」的 recheck 讓 M3 變綠 | 那是拿會過的斷言掩護沒驗的判斷。M3 要靠**資料修好**轉綠 |
| 改 M3 的判準讓它接受 `recheck=None` | §2.3:判準是對的,一個字都不准改。這樣做本單就失敗了 |
| 在 `core/decisions.py` 加 `no_evidence` 欄位或新 kind | §2.2:B0 凍結。空 `references` 已經夠用 |
| 順手把這 3 條 ratify 掉,反正很明顯 | 那是 B1.5,使用者本人的動作。本單產出 CONFIRMED 仍為 0 |
| 看到 `plan_local_first.md` 就開始做 workspace / chdir / UI | §0.15:與本單無關 |
| 做完順手做 C3 / B2 | 本單明確停在 G1 |
