# -*- coding: utf-8 -*-
"""分桶檢視「LLM 分類」按鈕的實作。函式簽章跟 `rules.propose()` 相同
(`name → (bucket, why)`),可以互換 —— 兩者都是**提案**,不自動生效。

⚠️ **不准用 `core/llm.py`**(那是 gemini 的出口,已退場,理由見它的檔頭)。
讀取器一律走 `fill_auto.READERS`(`claude` = `claude -p`,用使用者自己的
Claude Code 訂閱,不需要 API key;`deepseek` = DeepSeek API,需要
`DEEPSEEK_API_KEY`)——跟現行抄列同一組讀取器,不另開一條路。

prompt 直接用 `config.BUCKET_RULES`——不另寫一份,那段散文才是分桶規則的
唯一權威來源(`buckets.py`/`rules.py` 檔頭都這樣講)。
"""
import json

import config

_PROMPT_TMPL = """{rules}

科目名:「{name}」

只回一個 JSON 物件,不要多餘文字:
{{"bucket": "桶名或 __UNKNOWN__", "why": "一句話理由"}}"""


def _parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"LLM 沒回 JSON:{text[:200]!r}")
    return json.loads(text[start:end + 1])


def propose(name, reader="claude"):
    """`name → (bucket, why)`。判不出來(含模型自稱 `__UNKNOWN__`、回傳桶名
    不在 `config.BUCKETS` 裡、呼叫失敗、格式不對)一律回 `(None, why)` ——
    **不准把「壞掉」跟「判不出來」混在一起變成兩種原因一種結果**,`why` 裡
    要講清楚是哪一種。

    `reader`:`"claude"`(預設,`claude -p`,不需 API key)或
    `"deepseek"`(需要環境變數 `DEEPSEEK_API_KEY`)——就是 `fill_auto.READERS`
    的兩個既有讀取器,分桶跟抄列共用同一組,不另開一條路。
    """
    import fill_auto

    read_fn = fill_auto.READERS.get(reader)
    if read_fn is None:
        return None, f"不認得的讀取器「{reader}」(只支援 {list(fill_auto.READERS)})"

    prompt = _PROMPT_TMPL.format(rules=config.BUCKET_RULES, name=name)
    try:
        raw = read_fn(prompt)
        obj = _parse(raw)
    except Exception as e:
        return None, f"LLM 呼叫或解析失敗:{e}"

    bucket = obj.get("bucket")
    why = obj.get("why") or "(LLM 沒附理由)"
    if bucket == "__UNKNOWN__" or not bucket:
        return None, f"LLM 判不出來:{why}"
    if bucket not in config.BUCKETS:
        # 模型幻覺出不存在的桶名 —— 白名單擋下,不靜靜新增一個桶
        # (docs/plan_v8_llm分桶.md R0-3)。
        return None, f"LLM 回了不存在的桶名「{bucket}」,視同判不出來(原理由:{why})"
    return bucket, why
