# -*- coding: utf-8 -*-
"""v4 Reader —— 整份 PDF 一次丟給模型,不切片、不 locate。

    python3 -m v4.reader 202504_5835_AI3          跑一份,結果存 v4/raw/{doc}.json
    python3 -m v4.reader --scope 2023             跑 2023+ 尚未讀過的全部
    python3 -m v4.reader --scope 2023 --force     連已讀過的也重跑

背景(docs/plan_v4_dump.md):
- 國泰年報 `202504_5835_AI3` 逐桶 24/24、總額/錨 3/3 全對,注入的兩個錯 2/2 抓到、
  0 誤報、不竄改原值。
- held-out 富邦半年報 `202202_5836_AI3`(未事先看答案)同樣 24/24 全對,cost 三格
  正確填 null,且面對主報表整段是掃描圖時沒有捏造錨,誠實在散文裡宣告限制。
- **但那次也證明 `no_witness` 不能信模型自報**:BS 頁是空白掃描圖,模型 JSON 裡
  `check_anchor` 照樣填 `"status":"OK"`。所以這支只管「讀」,`no_witness` 的強制
  覆寫留給 `v4/witness.py`(L2),不在這裡做,也不要相信這裡輸出的 checks 是最終結論。
- 去除中文字之間的排版空白,對抽取結果零影響(逐列金額完全相同),省 15~19% token,
  且讓最大的 5 份富邦(原 200~213k)都退回 200k context 以下,不需要切片。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

import pypdfium2 as pdf

import locate

PDF_DIR = "pdf_cache"
OUT_DIR = "v4/raw"
CLASSES = ("Trading", "OCI", "AC")
CLAUDE_TIMEOUT_S = 600  # 實測 2:53~3:43;富邦最大份留雙倍餘裕


# ─────────────────────────── 抽文字 + 去空白 ───────────────────────────

_WS = re.compile(r"[ \t]+")
_CJK_GAP = re.compile(r"(?<=[一-鿿])\s+(?=[一-鿿])")


def slim_line(line):
    """中文字之間的空白是排版對齊的產物,不是資訊——刪掉零影響,已用富邦
    held-out 那份驗證過(逐列金額抽取結果完全相同,見 plan_v4_dump.md 表)。
    數字/`$`/英文字母之間的空白保留,那些是表格欄位分隔。"""
    return _CJK_GAP.sub("", _WS.sub(" ", line)).strip()


def pages_text(path):
    d = pdf.PdfDocument(path)
    try:
        return [d[i].get_textpage().get_text_range() for i in range(len(d))]
    finally:
        d.close()


def dump_text(path):
    """整份文件的可讀全文,含頁碼標記,已去除排版空白。"""
    pages = pages_text(path)
    out = []
    for i, txt in enumerate(pages):
        out.append(f"===== PAGE {i + 1} =====")
        out.append("\n".join(slim_line(l) for l in txt.split("\n")))
    return "\n".join(out), pages


def is_scanned(pages, thresh_chars_per_page=200):
    """粗判是否整份幾乎抽不到文字(純掃描圖)。這支 reader 目前只走文字路徑,
    純掃描圖的份留給 v4 計畫第 7 步(換影像輸入),這裡先誠實跳過而不是硬跑。"""
    if not pages:
        return True
    return sum(len(t) for t in pages) < thresh_chars_per_page * len(pages)


# ─────────────────────────────── Prompt ───────────────────────────────
# 這份 prompt 是 docs/plan_v4_dump.md 表列的 prompt3 定案版,已在兩份文件上驗證
# (一份診斷後修出來的、一份 held-out)。銀行名稱從 prompt 裡拿掉,改成一般化描述
# ——不要為了單一銀行的封面文字硬編,基本結構(附註/明細表位置)才是可以類化的部分。

PROMPT_HEADER = """你是財報分析助理。下面是一份台灣銀行財務報告的完整內文(以 ===== PAGE n ===== 標示頁碼)。

請找出該報告揭露的**最新一期資產負債表日**,三類金融資產的投資明細:
Trading = 透過損益按公允價值衡量之金融資產
OCI     = 透過其他綜合損益按公允價值衡量之金融資產
AC      = 按攤銷後成本衡量之債務工具投資

## 文件結構(銀行財報都是這個結構)
- 帳面口徑在「財務報表附註」的各該項目附註裡。
- 成本口徑(取得成本)在後面「重要會計項目明細表」那一節,每類各一張表,只有年報有,
  半年報沒有。
- 請對三類各自去翻它自己的那張表,不要只翻一張就推論其他類。

## 抄錄規則
1. 三類都必須各自回答 cost,不准省略。該類明細表沒有「取得成本」欄就填 null,
   並在 cost_note 說明該表實際有哪些欄位。
2. 嚴禁替代:不准拿公允價值、攤銷後成本、帳面金額、總面額、名目本金充當成本。
   寧可填 null,也不准放一個看起來合理但口徑不同的數字。
3. **細項展開層級鐵則(重點)**:
   - `rows` 中的項目名稱必須是**具體金融工具標的**（如:股票、政府公債、公司債、金融債券、商業本票、可轉換公司債、REITs、受益憑證等）。
   - **嚴禁僅抄錄大類標題**:若附註表格開頭僅寫「權益工具投資」與「債務工具投資」兩大會計分類標題,**必須繼續向下展開**,抄錄各分類下具體的金融資產種類細項（例如將權益工具展開為股票/REITs,將債務工具展開為公司債/金融債券/政府公債等）,使其加總等於該類總額。
   - **`group` 與 `name` 分開兩個欄位,不要黏在一起**:財報常把表格印成
     「權益工具投資－上市（櫃）及興櫃股票」「強制透過損益按公允價值衡量之金融資產－商業本票」
     這種「大類段落－具體標的」的格式。`group` 填大類段落（例如「權益工具投資」
     「強制透過損益按公允價值衡量之金融資產」「衍生金融資產」),`name` 只填具體標的
     （例如「上市（櫃）及興櫃股票」「商業本票」)。**不准把兩段原封不動接在一起塞進
     `name`**——下游是拿 `name` 去對照一份具體標的清單,黏著大類的話永遠對不上。
     表格如果本來就只印具體標的、沒有大類段落,`group` 留空字串即可。
   - `合計`/`小計`/`淨額` 這類加總列**不是**投資標的,不要放進 `rows`——那是
     `printed_subtotal`,加總列如果被誤放進 `rows` 會被下游當成「對不到桶的
     金額」擋下來,等於白白製造一個假警報。
4. 每個數字附出處頁碼。
5. **也回報這份文件的口徑**:封面寫「個體財務報告」→ "個體";
   寫「合併財務報告」或含「及子公司」→ "合併"。判不出來就填 "?"。

## 對帳規則(逐項執行,回報結果到 checks —— 只是初稿,最終判定由外部程式重算)
對每一類,執行下列三道檢查:
- check_rowsum : 你抄下來的逐列金額加總,是否等於財報**自己印出來的**小計/合計?
                 (自己加一次,不要假設它一定相等)
- check_anchor : 該類附註的合計數,是否等於**個體或合併資產負債表**上該科目的金額?
                 **若資產負債表那一頁抽不到文字(掃描圖/空白),status 一律填
                 "no_witness",不准猜測填 OK。**
- check_cost   : 若 cost 不為 null,成本逐列加總是否等於明細表印出的成本合計?

**鐵則:發現不符時,絕對不准回頭修改任何一列數字去讓它對得起來,也不准悄悄改用另一個
數字。照抄你實際看到的,如實回報 MISMATCH 與差額。財報印錯、或你抄錯,都要讓它浮出來。**

單位新台幣仟元。只輸出 JSON,不要其他說明文字。格式:
{"basis":"個體|合併|?",
 "bs_date":"114/12/31",
 "Trading":{"book":{"total":n,"printed_subtotal":n,"bs_anchor":n,"page":n,
            "rows":[{"group":"","name":"","amount":n}]},
            "cost":{"total":n|null,"page":n|null,"rows":[...]},"cost_note":"",
            "checks":{"check_rowsum":{"status":"OK|MISMATCH","diff":n},
                      "check_anchor":{"status":"OK|MISMATCH|no_witness","diff":n},
                      "check_cost":{"status":"OK|MISMATCH|no_witness","diff":n}}},
 "OCI":{...}, "AC":{...}}

===== 財報全文開始 =====
"""


def build_prompt(full_text):
    return PROMPT_HEADER + full_text


# ─────────────────────────────── 模型呼叫 ───────────────────────────────
# `--allowed-tools ""` 是必要的:工單全文已經在 prompt 裡,它不需要讀任何檔;
# 不收掉工具的話它是 agent,可能自作主張去翻 repo 或改檔案(見 fill_auto.py 同款註解)。

def call_claude(prompt, timeout_s=CLAUDE_TIMEOUT_S):
    r = subprocess.run(
        ["claude", "-p", "--allowed-tools", "", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout_s)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 失敗(rc={r.returncode}) "
                            f"stdout={r.stdout[:500]!r} stderr={r.stderr[:500]!r}")
    return r.stdout


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def call_deepseek(prompt, timeout_s=CLAUDE_TIMEOUT_S):
    """DeepSeek API(OpenAI-compatible)。KEY 從 .env 讀,不寫死在程式裡。"""
    import urllib.request
    _load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未設定(請確認 .env 有 DEEPSEEK_API_KEY=sk-...)")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


def call_model(prompt, model="claude", timeout_s=CLAUDE_TIMEOUT_S):
    """統一入口。`model` 接受 'claude' 或 'deepseek'。"""
    if model == "deepseek":
        return call_deepseek(prompt, timeout_s)
    return call_claude(prompt, timeout_s)


def parse_json(text):
    """模型可能包 markdown 圍欄或前後加話。解析失敗回 None,不猜一個空結果——
    「模型壞了」與「表格真的空」是兩件事,混在一起會讓 witness 層失去意義。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────── 主流程 ───────────────────────────────────

def run_doc(doc, pdf_dir=PDF_DIR, out_dir=OUT_DIR, model="claude", force=False):
    """讀一份文件,存原始模型輸出到 {out_dir}/{doc}.json。回傳 (ok, path_or_reason)。
    `model`:"claude"(預設)或 "deepseek"。
    `force`:True = 即使已讀過也重跑(覆寫)。
    """
    path = os.path.join(pdf_dir, f"{doc}.pdf")
    if not os.path.exists(path):
        return False, f"找不到 PDF:{path}"

    out_path = os.path.join(out_dir, f"{doc}.json")
    if not force and os.path.exists(out_path):
        return True, f"已有結果(force=False),跳過:{out_path}"

    full_text, pages = dump_text(path)
    if is_scanned(pages):
        return False, "純掃描圖(這支 reader 只走文字路徑,留給計畫第 7 步)"

    prompt = build_prompt(full_text)
    t0 = time.time()
    raw = call_model(prompt, model=model)
    elapsed = time.time() - t0

    parsed = parse_json(raw)
    os.makedirs(out_dir, exist_ok=True)
    record = {
        "doc": doc,
        "model": model,
        "n_pages": len(pages),
        "prompt_chars": len(prompt),
        "elapsed_s": round(elapsed, 1),
        "raw_text": raw,
        "parsed": parsed,
        "parse_ok": parsed is not None,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)

    if parsed is None:
        return False, f"JSON 解析失敗,原文存在 {out_path}"
    return True, out_path


def docs_in_scope(scope_year=None):
    """`pdf_cache/*.pdf` 依 doc 前 4 碼(年份)篩選。`fill._doc_sort_key` 那套排序
    這裡不需要 —— v4 沒有預算與重試順序,誰先跑都一樣,結果是集合不是序列。"""
    out = []
    for p in sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))):
        doc = os.path.basename(p)[:-4]
        if scope_year and doc[:4] < str(scope_year):
            continue
        out.append(doc)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", nargs="?", help="只跑這一份")
    ap.add_argument("--scope", type=int, default=None,
                     help="跑這年以後的全部,例如 --scope 2023")
    ap.add_argument("--force", action="store_true", help="已讀過的也重跑")
    ap.add_argument("--model", default="claude", help="模型選擇 (claude 或 deepseek)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    if args.doc:
        targets = [args.doc]
    elif args.scope:
        targets = docs_in_scope(args.scope)
    else:
        ap.error("要嘛指定一份 doc,要嘛給 --scope")
        return 2

    if not args.force:
        targets = [d for d in targets
                   if not os.path.exists(os.path.join(OUT_DIR, f"{d}.json"))]
    if args.limit:
        targets = targets[:args.limit]

    print(f"待跑 {len(targets)} 份: {targets}")
    ok = fail = skip = 0
    for i, doc in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {doc} ...", end=" ", flush=True)
        try:
            good, info = run_doc(doc, model=args.model, force=args.force)
        except subprocess.TimeoutExpired:
            good, info = False, f"逾時(>{CLAUDE_TIMEOUT_S}s)"
        except Exception as e:  # noqa: BLE001 —— 批次跑,單份出錯不能讓全批停
            good, info = False, f"例外:{e}"
        if good:
            ok += 1
            print(f"OK  {info}")
        elif "純掃描圖" in info:
            skip += 1
            print(f"跳過  {info}")
        else:
            fail += 1
            print(f"FAIL  {info}")
    print(f"\n完成:成功 {ok}  失敗 {fail}  跳過(掃描圖) {skip}  共 {len(targets)}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
