# -*- coding: utf-8 -*-
"""迴圈驅動的回歸:**證明升級決策會觸發,而且會走到正確的頁**。

`locate.EXPAND_TRUTH` 只證明了「正確頁在擴張後的候選集合裡」。那是必要條件,
不是迴圈本身 —— 中間還有一個「對不上才擴張」的決策,而那個決策可能:
  a. 根本不觸發(第 1 輪就誤判成過了)→ 永遠看不到子附註頁
  b. 觸發了但沒把新頁餵給 agent
  c. 抄不出來時不肯停,無限擴張
本檔用假的 transcriber 把這三件事分別鎖住,不需要真的叫 agent 讀表。

跑法:python3 test_pipeline.py
"""
import json

import locate
import pipeline

DOC, CLS = "202102_5847_AI3", "OCI"     # 玉山 2021H1:子附註在 p24,曾被誤判為「唯一死文件」


def _pages_in(prompt):
    return [int(l.split()[2]) for l in prompt.splitlines() if l.startswith("===== page")]


def case_escalates():
    """對不上 → 必須擴張,而且新 prompt 要包含手動驗過的正確頁。"""
    seen = []

    def never_matches(prompt):
        seen.append(_pages_in(prompt))
        return None                      # agent 抄不出來 → 逼迴圈升級
    out = pipeline.drive(DOC, CLS, never_matches)
    truth = dict(((d, c), p) for d, c, p in locate.EXPAND_TRUTH)[(DOC, CLS)]
    yield ("抄不出來時會擴張(prompt 輪數 > 1)", len(seen) > 1, f"輪數={len(seen)}")
    yield (f"擴張後的 prompt 含手動驗過的 p{truth}",
           any(truth in p for p in seen[1:]), f"各輪頁碼={seen}")
    yield ("每輪頁數只增不減", all(len(a) < len(b) for a, b in zip(seen, seen[1:])),
           f"各輪頁數={[len(p) for p in seen]}")
    yield ("抄不出來最終拒收,不會無限擴張", (not out.ok) and out.reason, repr(out))


def case_two_layer():
    """主附註加總剛好 = 錨,但沒有明細 → **必須照樣擴張**。

    這是原本測不出來的死角:舊的假 transcriber 一律回 None,所以「抄得出東西、
    前四道還全綠、但產出是廢的」這條路徑從來沒被走過。實跑才撞到(玉山 p23)。
    """
    main_note = [{
        "doc": DOC, "class": CLS, "source_page": 23, "source_kind": "附註",
        "total_col": "110年6月30日", "printed_total": 287711177,
        "rows": [{"name": "透過其他綜合損益按公允價值衡量之權益工具投資",
                  "cols": {"110年6月30日": 16018428}},
                 {"name": "透過其他綜合損益按公允價值衡量之債務工具投資",
                  "cols": {"110年6月30日": 271692749}}]}]
    seen = []

    def only_main_note(prompt):
        seen.append(_pages_in(prompt))
        return main_note                 # 每輪都只交得出主附註
    out = pipeline.drive(DOC, CLS, only_main_note)
    yield ("主附註湊得出錨也不算過(第 5 道擋下)", len(seen) > 1, f"輪數={len(seen)}")
    yield ("擴張後看得到子附註 p24", any(24 in p for p in seen[1:]), f"各輪={seen}")
    yield ("始終交不出明細 → 拒收", not out.ok, repr(out))


def case_stops_early():
    """第 1 輪就對上 → 不准再擴張(擴張是有成本的,不是免費保險)。"""
    recs = json.load(open("scratchpad/rows_r2.json", encoding="utf-8"))["202404_5835_AI3|OCI"]
    n = []

    def good(prompt):
        n.append(_pages_in(prompt))
        return recs
    out = pipeline.drive("202404_5835_AI3", "OCI", good)
    yield ("第 1 輪對上就停", len(n) == 1, f"輪數={len(n)}")
    yield ("結果標記為未擴張", out.ok and out.level == 0, repr(out))


def case_no_anchor():
    """錨讀不到的格子不該假裝試過 —— 連 prompt 都不該產生。"""
    called = []
    out = pipeline.drive("201802_5835_AI3", "Trading", lambda p: called.append(p))
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
