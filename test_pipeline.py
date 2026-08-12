# -*- coding: utf-8 -*-
"""迴圈驅動的回歸:**證明工單一開始就走到正確的頁,而且抄不出來時會停**。

⚠️ 2026-07-31 改版。舊版釘的是「對不上 → 擴張鄰頁 → 才看得到子附註頁」,
那條升級路徑已經不存在了:工單單位換成**附註章節**,子附註本來就在同一章裡,
第 1 輪就看得到(`section.py` 檔頭有實測:EXPAND_TRUTH 10 格 10/10)。
所以本檔改釘現在真正要保護的三件事:
  a. **第 1 輪的工單就含手動驗過的正確頁**(章節模式的核心主張)
  b. 抄不出來時會停,不會無限換章節
  c. 母表-only(湊得出錨但沒有明細)**會歸檔**,但 `publish_gate` 必須擋住發布
     —— 洞還在,守衛換位置了(⑤ 從歸檔閘移到發布閘,使用者裁示)

跑法:python3 test_pipeline.py
"""
import json

import locate
import pipeline

DOC, CLS = "202102_玉山_個體", "OCI"     # 玉山 2021H1:子附註在 p24,曾被誤判為「唯一死文件」


def _pages_in(prompt):
    return [int(l.split()[2]) for l in prompt.splitlines() if l.startswith("===== page")]


def case_escalates():
    """第 1 輪就該看到正確頁;抄不出來要停,不能無限換章節。"""
    seen = []

    def never_matches(doc, cls, prompt):
        seen.append(_pages_in(prompt))
        return None                      # agent 抄不出來 → 逼迴圈升級
    out = pipeline.drive(DOC, CLS, never_matches)
    truth = dict(((d, c), p) for d, c, p in locate.EXPAND_TRUTH)[(DOC, CLS)]
    yield (f"**第 1 輪**的 prompt 就含手動驗過的 p{truth}(不必等擴張)",
           bool(seen) and truth in seen[0], f"第1輪={seen[0] if seen else None}")
    yield ("每一輪都是一個章節,不是愈滾愈大的聯集",
           all(a != b for a, b in zip(seen, seen[1:])), f"各輪頁碼={seen}")
    yield ("抄不出來最終拒收,不會無限換章節", (not out.ok) and out.reason, repr(out))


def case_two_layer():
    """主附註加總剛好 = 錨,但沒有明細 → **歸檔,但不可發布**。

    這是「四道全綠、產出是廢的」那個洞。2026-07-31 起 ⑤ 不再擋歸檔,所以它
    會通過 `verify()` —— 保護改由 `publish_gate` 提供(兩列對不到桶 ⇒
    `wide.View.unknown` 非空 ⇒ 不可發布)。**兩件事都要釘**:通過歸檔是預期的,
    可以發布就是洞破了。
    """
    main_note = [{
        "doc": DOC, "class": CLS, "source_page": 23, "source_kind": "附註",
        "total_col": "110年6月30日", "printed_total": 287711177,
        "rows": [{"name": "透過其他綜合損益按公允價值衡量之權益工具投資",
                  "cols": {"110年6月30日": 16018428}},
                 {"name": "透過其他綜合損益按公允價值衡量之債務工具投資",
                  "cols": {"110年6月30日": 271692749}}]}]
    seen = []

    def only_main_note(doc, cls, prompt):
        seen.append(_pages_in(prompt))
        return main_note                 # 每輪都只交得出主附註
    out = pipeline.drive(DOC, CLS, only_main_note)
    truth = dict(((d, c), p) for d, c, p in locate.EXPAND_TRUTH)[(DOC, CLS)]
    yield ("第 1 輪的工單就含子附註頁", bool(seen) and truth in seen[0],
           f"第1輪={seen[0] if seen else None}")
    yield ("主附註湊得出錨 → 兩道閘門放行(歸檔)", out.ok, repr(out))
    from core import publish_gate
    st = publish_gate.coarse_status(f"{DOC}|{CLS}", main_note)
    yield ("但 publish_gate 必須擋住發布", not st["publishable"], repr(st["reasons"]))


def case_stops_early():
    """第 1 輪就對上 → 不准再擴張(擴張是有成本的,不是免費保險)。"""
    recs = json.load(open("scratchpad/rows_r2.json", encoding="utf-8"))["202404_國泰_個體|OCI"]
    n = []

    def good(doc, cls, prompt):
        n.append(_pages_in(prompt))
        return recs
    out = pipeline.drive("202404_國泰_個體", "OCI", good)
    yield ("第 1 輪對上就停", len(n) == 1, f"輪數={len(n)}")
    yield ("結果標記為未擴張", out.ok and out.level == 0, repr(out))


def case_no_anchor():
    """錨讀不到的格子不該假裝試過 —— 連 prompt 都不該產生。"""
    called = []
    out = pipeline.drive("201802_國泰_個體", "Trading",
                          lambda doc, cls, p: called.append(p))
    yield ("錨讀不到 → 直接拒收,不叫 agent", (not out.ok) and not called, repr(out))


def main():
    bad = 0
    for case in (case_escalates, case_two_layer, case_stops_early, case_no_anchor):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
