# -*- coding: utf-8 -*-
"""S3→S5 的迴圈驅動:定位 → 抄列 → 對帳 → 對不上就擴張 → 再抄。

**由算術驅動,不是由版型驅動。** 整條迴圈只認一個訊號:
`sum(葉列) == 錨` 成不成立。成立就停,不成立就把候選頁擴大重來。
所以不需要分辨遇到的是哪一種漏抓 —— 實測有三種,同一招都治
(子附註在另一頁 / 表格跨頁 / 同頁多段小計,見 locate.Located.expand)。

## 中間那一步是 agent,而且**故意留成洞**

    locate() ─► context() ─► ❓ agent 讀表 ❓ ─► verify() ─┬─ 過 → 收
                   ▲                                      │
                   └────────── expand() ◄─────────────────┴─ 不過

讀表的是 Claude Code 自己(plan_refactor_v3.md §6c 決策 1),本檔**不呼叫任何模型**。
`run()` 因此是 generator:每要一次抄列就 yield 一份 prompt 出去,呼叫端把 rows
送回來(`gen.send(...)`)。這樣同一套升級邏輯,agent 手動抄、未來換成自動抄,
兩邊走的是同一條路徑,不會各長一套。

⚠️ 不要把這個洞補成「找不到就猜」。抄不出來的正確處理是**拒收 + 進複核佇列**,
不是再加一條 rescue(§0.1 第 3 條)。
"""
import locate
import transcribe

#: 擴張的上限。level 1(±1 鄰頁)在 10 格手驗真值上已經 10/10,
#: level 2/3 目前**沒有任何一格用得上** —— 留著是因為原理上可能發生,
#: 但沒有實例前不預設用。動這個數字前先看 locate.EXPAND_TRUTH 的實測表。
MAX_LEVEL = 2


class Outcome:
    """一格跑完的結果。`rows` 為 None 代表拒收 —— **拒收不是 bug,是正確輸出**。"""

    def __init__(self, doc, cls, recs=None, res=None, level=0, reason=None):
        self.doc, self.cls = doc, cls
        self.recs, self.res, self.level, self.reason = recs, res, level, reason

    ok = property(lambda self: self.recs is not None)

    def __repr__(self):
        tag = f"擴張{self.level}級" if self.level else "第1層"
        return (f"<{self.doc} {self.cls} "
                + (f"收 {tag} 葉列{[len(r['rows']) for r in self.recs]}>"
                   if self.ok else f"拒收 {self.reason}>"))


def run(doc, cls):
    """跑一格。generator:yield prompt,呼叫端 send(recs)。回傳 Outcome。

    用法:
        gen = run("202404_兆豐_個體", "Trading")
        prompt = next(gen)
        while True:
            try:
                prompt = gen.send(agent_抄列(prompt))
            except StopIteration as e:
                outcome = e.value; break
    """
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    if cls not in loc.anchors:
        # 錨讀不到(BS 是掃描影像)→ 這格根本進不了純文字路徑,不要假裝試過
        return Outcome(doc, cls, reason="錨讀不到,此格走視覺或不做")
    if not loc.pages[cls]:
        return Outcome(doc, cls, reason=f"無候選頁 錨={loc.anchors[cls]:,}")

    # 2026-07-31:起始頁 = 最小的附註章節(`loc.expand(cls, 0)`),不再是
    # 「錨值 grep 命中的所有頁」—— 後者會把明細表跟附註塞進同一份工單。
    pages, level, seen = loc.expand(cls, 0), 0, []
    if not pages:
        return Outcome(doc, cls, reason=f"切不出附註章節 錨={loc.anchors[cls]:,}")
    while True:
        recs = yield transcribe.context_pages(loc, cls, pages)
        if recs:
            ok, res = transcribe.verify(recs, loc)
            if ok:
                return Outcome(doc, cls, recs, res, level)
            seen.append((level, res))
        else:
            seen.append((level, {"抄列": "agent 回空"}))

        # ── 升級:便宜的先來,對上就停 ──
        level += 1
        if level > MAX_LEVEL:
            return Outcome(doc, cls, res=seen[-1][1], level=level - 1,
                           reason=f"擴張到 {MAX_LEVEL} 級仍對不上,進複核佇列")
        # **取代不是聯集**(見 `locate.Located.expand`):每一級是各自獨立的
        # 一個章節,聯集起來只會把不相干的章節混進同一份工單。
        more = loc.expand(cls, level)
        if not more or more == pages:
            return Outcome(doc, cls, res=seen[-1][1], level=level - 1,
                           reason=f"沒有下一個章節可看,進複核佇列")
        pages = more


def prompt_at(doc, cls, level=0):
    """直接取某一級的 prompt。給「agent 就是我」的手動流程用 —— run() 的
    generator 協定在互動式抄列時很難用,但兩者算的是同一組頁,不會分岔。"""
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    return transcribe.context_pages(loc, cls, loc.expand(cls, level))


def drive(doc, cls, transcriber):
    """把 generator 協定包起來。`transcriber(doc, cls, prompt) -> recs`(抄不出來回 None)。"""
    gen = run(doc, cls)
    try:
        prompt = next(gen)
        while True:
            prompt = gen.send(transcriber(doc, cls, prompt))
    except StopIteration as e:
        return e.value


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 pipeline.py <檔名(不含.pdf)> <Trading|OCI|AC> [擴張級數]")
        raise SystemExit(2)
    print(prompt_at(sys.argv[1], sys.argv[2],
                    int(sys.argv[3]) if len(sys.argv) > 3 else 0))
