# -*- coding: utf-8 -*-
"""`pipeline.drive` × `transcriber.replay` 的回歸基準:**證明「換成自動抄列」
不會改變迴圈本身的行為**。

replay 是最誠實的假 transcriber —— 它就是把事實庫裡已經抄好的答案原封不動交回去。
對事實庫裡每一格都跑一次 drive(),應該每格都 `outcome.ok`,而且抄出來的 recs
與事實庫裡的**逐列相同**(不是「數字對得上」,是同一份資料)。

跑法:python3 test_drive.py
"""
import facts
import pipeline
import transcriber


def main():
    cells = facts.load()
    replay = transcriber.replay(cells)
    bad = 0
    for key in sorted(cells):
        doc, cls = key.split("|", 1)
        out = pipeline.drive(doc, cls, replay)
        ok = out.ok and out.recs == cells[key]
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {key}" + ("" if ok else f"\n      {out!r}"))
    print(f"\n{len(cells)} 格,{len(cells) - bad} 格重現" + ("" if not bad else f",{bad} 格不符"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
