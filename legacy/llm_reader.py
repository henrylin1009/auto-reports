# -*- coding: utf-8 -*-
"""LLM 讀值器(DeepSeek)——取代『我人工讀值』那步。

流程:候選頁文字 → DeepSeek 判斷哪頁是明細表 + 讀出 [(品名, 當期金額)] + 總合計錨。
數字/對桶/對帳仍由 schema.py + universal.check 把關(LLM 不碰對帳,防幻覺)。

key 放 .env 的 DEEPSEEK_API_KEY。DeepSeek 相容 OpenAI SDK。
"""
import os
import json


def _load_env(path=".env"):
    """極簡 .env 讀取(免裝 python-dotenv)。"""
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _client():
    _load_env()
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("找不到 DEEPSEEK_API_KEY,請在 .env 貼上你的 key")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


_PROMPT = """你是財報抽取助手。以下是某銀行財報中,標題含「{cls_title}」的候選頁文字。
請找出「{cls_name}」的持有資料,讀出每一列(債務工具+權益工具都要)以及最後的『合計』。

來源優先(重要):固定讀「{source}」;不是損益表、不是公允價值分級表、不是敘述段落。
若同時有主附註與附錄明細表,依上面指定的那一種為準。

規則:
- 只取「當期(本期資產負債表日/本期期末)」金額,判準是欄位標題的『日期』:取日期最新(最近)的那一欄。
  * 年報常是兩欄:本期(如 12/31 當年)| 去年底 → 取左邊本期。
  * 半年報常是三欄:本期底(如 6/30 當年)| 去年底(12/31 去年)| 去年同期(6/30 去年)
    → 一律取「日期最新」那欄(本期 6/30),不要取去年底、更不要取去年同期。
  * 判不出日期時才退回「取最左欄」。當期欄是單獨破折號(―/—/-)=當期無 → 記 0,絕不改取其他欄補。
- 取「{measure}」欄的金額(明細表可能有面額/成本/公允價值等多欄)。
- 評價調整、減損、備抵、衍生、避險等調整項也要列出(名稱原樣、金額原樣,負數用負號)。
- 重要:凡屬於「衍生工具/衍生金融資產/避險」段落底下的每一列,品名前一律加註「衍生」二字
  (例如衍生段落裡叫「其他」的,請寫成「衍生其他」;叫「利率交換」寫成「衍生利率交換」)。
  這樣才不會把衍生工具誤當成債券。
- 中途的「小計」不要當合計;要最後那個「合計/總計」當 anchor。
- 金額單位照原文(仟元),去除逗號與 $;數字務必逐位看準,不要看錯位數。

分組(重要,供自洽校驗用):把每一列歸到它所屬的「小計段落」。
- 財報常把明細分成幾段,各段有自己印出的「小計」(例:債務工具小計、權益工具小計)。
- 每一段輸出成一個 group:section=段名、subtotal=該段印在紙上的小計金額(沒有印小計就填 null)、
  rows=該段底下各列 [品名, 金額]。
- 評價調整/減損/衍生等調整項,自成一段(section 用「調整」,subtotal 填 null)。
- 各段 rows 的加總必須等於該段印出的 subtotal——請據實填,不要湊。

自報來源(重要,供防呆):
- source_type:你這次的數字是從哪種表讀的?只能填「主附註」或「明細表」。
  * 主附註 = 財報正文的附註(段落式,附註編號如(十二));明細表 = 附錄逐筆/逐標的清單。
- header:把你所讀那頁/那張表最上方的標題那一行『原文』照抄回來(讓人可核對你沒挑錯表)。

只回 JSON,格式:
{{"page": <頁碼>,
  "source_type": "主附註 或 明細表",
  "header": "<所讀表的頁首標題原文>",
  "groups": [
    {{"section": "債務工具", "subtotal": <該段小計>, "rows": [["品名", 金額], ...]}},
    {{"section": "權益工具", "subtotal": <該段小計>, "rows": [...]}},
    {{"section": "調整", "subtotal": null, "rows": [["評價調整", -金額], ...]}}
  ],
  "anchor": <最後的合計金額>}}

候選頁:
{pages}"""


def read_note(candidates, cls, cls_title, cls_name, measure, source="", model=None):
    """candidates: [(page_index, text)];回傳 {"page","rows","anchor"} 或拋錯。"""
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    blob = "\n\n".join(f"===== PAGE {i} =====\n{t}" for i, t in candidates)
    msg = _PROMPT.format(cls_title=cls_title, cls_name=cls_name,
                         measure=measure, source=source, pages=blob)
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": msg}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    # 解析分組;扁平化成 rows 供既有對桶邏輯用,同時保留 groups 供自洽校驗。
    groups = []
    flat = []
    for g in data.get("groups", []) or []:
        rows = [(str(n), int(v)) for n, v in g.get("rows", []) if v is not None]
        sub = g.get("subtotal")
        groups.append({"section": g.get("section", ""),
                       "subtotal": None if sub is None else int(sub),
                       "rows": rows})
        flat.extend(rows)
    if not flat:                       # 舊格式相容:模型只回 rows 沒回 groups
        flat = [(str(n), int(v)) for n, v in data.get("rows", []) if v is not None]
    data["rows"] = flat
    data["groups"] = groups
    return data


_BS_PROMPT = """以下是某銀行財報『資產負債表』頁,已用座標對齊成「欄位 | 欄位」格式
(每列大致為:科目代碼 | 科目名稱 | 本期金額 | 本期% | 去年金額 | 去年%)。
請找出【資產側】科目「{cls_name}」的『當期(較新那欄)』金額,單位仟元。

重要:
- 標籤可能【折行】:某列只有「代碼+標籤上半」沒有數字,數字在【下一列】(標籤下半+金額)。
  請把折行併回,數字歸屬它上方的科目代碼。
- 舊格式常把這科目拆成「流動」+「非流動」兩列(代碼如 113xxx 與 123xxx),
  資產側也可能叫「…債務工具投資」而非「…金融資產」——都算同一科目,請把兩者【相加】。
- 只取資產側。務必【排除】權益區的同名項(如「…金融資產未實現損益/評價調整」),那不是資產。
- 每列本期金額 = 科目名稱後的第一個數字欄(其後的 1/8 等小整數是百分比,不是金額,別取)。
- 只取當期欄,不要去年欄。金額去逗號與 $。

只回 JSON:{{"anchor": <資產側總額數字(流動+非流動已相加),找不到填 null>}}

資產負債表頁(座標對齊):
{pages}"""


def read_bs_anchor(pages, cls_name, model=None):
    """讓 LLM 從資產負債表讀外錨(自動相加流動+非流動、排除權益側)。
       pages: [(page_index, text)];回傳 int(仟元)或 None。"""
    if not pages:
        return None
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    blob = "\n\n".join(f"===== PAGE {i} =====\n{t}" for i, t in pages)
    msg = _BS_PROMPT.format(cls_name=cls_name, pages=blob)
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": msg}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    v = json.loads(resp.choices[0].message.content).get("anchor")
    return None if v is None else int(v)


if __name__ == "__main__":
    # 簡易連線測試:讀不到 key 會報錯;有 key 會回一句話
    try:
        c = _client()
        r = c.chat.completions.create(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "回一個字:OK"}],
            temperature=0,
        )
        print("DeepSeek 連線成功:", r.choices[0].message.content.strip())
    except Exception as e:
        print("連線失敗:", e)
