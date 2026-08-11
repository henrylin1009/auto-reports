# -*- coding: utf-8 -*-
"""`fill_auto.run_key()` 的候選頁覆寫接得對不對(`plan_web_complete.md` W3)。

**不呼叫真的 reader**——那會打 Gemini API、花錢,而且驗的是抄列本身
(fill_auto.py 既有的事,不是這次要測的東西)。這裡只驗證一件事:
`cellmeta` 帶了 pages 覆寫時,`run_cell` 收到的 `pages` 引數是不是那個覆寫值;
沒帶 cellmeta 時,傳給 run_cell 的 `pages` 是不是 None(= 逐字沿用舊行為,
`run_cell` 自己退回 `loc.pages[cls]`)。用假的 `run_cell` 攔截呼叫來驗。

跑法:python3 test_fill_auto_pages.py
"""
import sys

import fill_auto
import locate

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


def _capture():
    """把 fill_auto.run_cell 換成假的,回傳 (還原函式, 拿引數的字典)。"""
    captured = {}
    orig = fill_auto.run_cell

    def fake(d, c, loc, reader, max_level, verbose=True, pages=None):
        captured["pages"] = pages
        return {"outcome": "PASS"}

    fill_auto.run_cell = fake

    def restore():
        fill_auto.run_cell = orig

    return restore, captured


DOC, CLS = "202404_5843_AI3", "Trading"


def w21_run_key_without_cellmeta_passes_none():
    """不傳 cellmeta:傳給 run_cell 的 pages 是 None——這正是舊行為
    (run_cell 內部再退回 `loc.pages[cls]`),證明沒傳 cellmeta 時
    這次改動對 run_queue 的自動路徑零影響。"""
    restore, captured = _capture()
    try:
        fill_auto.run_key(f"{DOC}|{CLS}", "claude")
    finally:
        restore()
    check("W21 pages 引數是 None", captured.get("pages") is None)


def w22_run_key_with_pages_override_passes_it_through():
    """傳了 cellmeta 且該格有 pages 覆寫:run_cell 收到的就是覆寫值,
    不是 `loc.pages[cls]`。"""
    override = [123, 456]  # 隨便一組跟真實候選頁不同的值,只驗證有沒有傳對
    cellmeta = {f"{DOC}|{CLS}": {"pages": {"value": override, "by": "t",
                                           "at": "t", "why": "t"}}}
    restore, captured = _capture()
    try:
        fill_auto.run_key(f"{DOC}|{CLS}", "claude", cellmeta=cellmeta)
    finally:
        restore()
    check("W22 pages 引數等於覆寫值", captured.get("pages") == override)


#: 這份 ≤2018 的舊檔三類錨都讀不到(掃描影像,無文字層)——固定拿來當
#: 「錨真的沒有」的反例,不必每次現掃 pdf_cache/ 找。
_NO_ANCHOR_DOC = "201802_5835_AI3"


def w23_run_key_still_rejects_anchor_missing():
    """錨真的讀不到的類別,不管有沒有 cellmeta,一樣不能抄
    (`pages` 覆寫解的是「候選頁找不到」,不是「連錨都沒有」——
    後者今天仍然出局,見 `plan_web_complete.md` §6③)。"""
    loc = locate.locate(f"pdf_cache/{_NO_ANCHOR_DOC}.pdf")
    assert not loc.anchors, f"{_NO_ANCHOR_DOC} 這份現在有錨了,換一份當固定反例"
    cls = locate.CLASSES[0]
    restore, captured = _capture()
    try:
        out = fill_auto.run_key(
            f"{_NO_ANCHOR_DOC}|{cls}", "claude",
            cellmeta={f"{_NO_ANCHOR_DOC}|{cls}":
                     {"pages": {"value": [1], "by": "t", "at": "t", "why": "t"}}})
    finally:
        restore()
    check("W23 錨讀不到就是 None,不因為有 pages 覆寫就放行",
          out is None and "pages" not in captured)


if __name__ == "__main__":
    for fn in (w21_run_key_without_cellmeta_passes_none,
               w22_run_key_with_pages_override_passes_it_through,
               w23_run_key_still_rejects_anchor_missing):
        fn()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    sys.exit(1 if FAIL else 0)
