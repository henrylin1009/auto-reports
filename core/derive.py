# -*- coding: utf-8 -*-
"""推導層 —— 只跟模型要它唯一能給的東西,系統已經知道或算得出來的不問。

`docs/plan_schema_derive.md` D1。根因(該文件 §0 實測):25 格拒收裡 22 格死在
`total_col` / `printed_total` / 破折號列這三個 schema 欄位上,而這三個系統
自己就有答案:

    total_col      = 213/213 份既有 record(已歸檔 + 拒收)唯一使
                      「列和 == 推導目標」成立的那一欄
    printed_total  = 推導目標(單根單份的舊格子是錨本身;章節模式下
                      非根的 record 是模型填的 `record_total`,見下方)
    破折號列        = 缺合計欄的列,**在目標確認欄位之後**補 0

⚠️ **2026-07-31 加了 `record_total`**(`docs/plan_section_closure.md`):一格的
多份 record 不再要求每份自己的列和都等於錨——章節模式下,一份附註常常是
「母表(兩三個大類,合計 == 錨)+ 子附註(各大類的明細,合計 == 自己那一段
小計)」,母表以外的 record 永遠對不上錨。`core/closure.py` 事後用金額把
子表掛回母表的哪一列;推導層只管「這張表自己的列和 == 這張表自己說的合計」,
不再管那個合計是不是錨。

⚠️ **`printed_totals`(逐欄合計)不在這支的推導範圍內** —— 它是明細表成本欄
唯一的獨立驗證來源,必須維持「模型獨立讀一次」,系統自己算的話第 6 道
(`transcribe.check_col_totals`)就變恆真了。這裡只處理「宣告了但對不上」
的情況:丟掉那個對不上的欄,不是連整格一起殺掉(`derive_record` 的最後一段)。
"""
import copy


class DeriveError(Exception):
    """推導失敗——訊息面向人看,不是給程式 parse 的。"""


def _col_sums(rows):
    cols = set()
    for r in rows:
        cols |= set((r.get("cols") or {}).keys())
    return {c: sum((r.get("cols") or {}).get(c, 0) for r in rows) for c in cols}


def fill_zero_for_col(rec, col):
    """已經知道(或已經人工選定)哪一欄是合計欄時,把那一欄缺的值補 0。

    跟 `derive_record()` 拆開是有理由的:`plan_web_complete.md` 的人工裁示
    路徑(`webdata.ratify()`)**不透過錨去重新發現 total_col**——人已經看過
    原始頁,選定的欄不一定要跟錨完全對上(那正是人工裁示存在的理由)。
    但「合計欄印的是『—』,該記 0」這件事跟錨對不對得上無關,是表本身的
    印刷慣例,兩條路徑都要套用,所以抽出來共用(2026-07-30 使用者實測抓到:
    ratify() 沒套用這條,導致人工歸檔的格子還是把破折號列的缺欄留白,
    check_identity 照樣報「有列缺合計欄」)。
    """
    out = copy.deepcopy(rec)
    if col:
        for r in out["rows"]:
            r.setdefault("cols", {})
            r["cols"].setdefault(col, 0)
    return out


def drop_mismatched_printed_totals(rec):
    """丟掉宣告了但列和對不上的 `printed_totals` 欄,對得上的保留。

    跟 `fill_zero_for_col` 一樣抽出來共用——`ratify()` 也需要這條,不然
    人工歸檔的格子會永久卡著一個驗不過的 `printed_totals`,`check_col_totals`
    每次開這格都報同一個(其實無關痛癢的)錯。
    """
    out = copy.deepcopy(rec)
    pt = out.get("printed_totals")
    if pt:
        sums = _col_sums(out["rows"])
        # 逐欄合計是模型獨立讀的(見檔頭警告),這裡只做「對不上就丟掉那一欄」,
        # 不重算、不用來覆蓋 —— 對不上代表那個宣告本身有問題(抄錯或欄名對不上),
        # 丟掉是誠實的「沒驗過就不上」,不是連公允欄一起殺掉整格。
        keep = {c: v for c, v in pt.items() if c in sums and sums[c] == v}
        if keep:
            out["printed_totals"] = keep
        else:
            out.pop("printed_totals", None)
    return out


def derive_record(rec, anchor):
    """一份 record 的推導。回傳新的 record(深拷貝,不動呼叫端的物件)。

    失敗時拋 `DeriveError`——**只有一種失敗**:沒有唯一的欄使列和等於推導目標。
    0 個命中 = 真的抄錯(系統過去把這種跟「挑錯欄」混在一起擋,現在分開);
    ≥2 個命中 = 歧義,今天實測 0 格,但不能沉默假裝成功(`plan_schema_derive.md` §8①)。

    推導目標(`docs/plan_section_closure.md`,2026-07-31):優先用模型填的
    `record_total`(**這張表自己印出來的合計**,不一定等於錨——章節模式下
    一格常有母表+子附註兩三份,只有母表的合計 == 錨,子附註的合計是自己那
    一段的小計)。沒有 `record_total` 才退回舊行為用錨本身(既有 155 格
    facts 都是這種單根單份形狀,沒有這個欄位,實測零改判)。

    `record_total` 只是**推導的輸入**,不進最終 record——推導完就是
    `printed_total`,兩者語意上是同一個數字,沒必要留兩份。是否等於錨
    (= 是不是這格的根)交給 `core/closure.py` 事後判斷,這裡不管。
    """
    if anchor is None and "record_total" not in rec:
        raise DeriveError("這個類別沒有錨,無法推導 total_col")
    rows = rec.get("rows") or []
    if not rows:
        raise DeriveError("rows 是空的,無法推導")

    target = rec.get("record_total", anchor)
    if target is None:
        raise DeriveError("沒有 record_total,也沒有錨,無法推導 total_col")

    sums = _col_sums(rows)
    hits = [c for c, s in sums.items() if s == target]
    if not hits:
        raise DeriveError(
            f"0 個欄命中——逐列相加沒有任何一欄等於{'錨' if target == anchor else '這張表自己印出的合計'} "
            f"{target:,}(可能真的抄錯了)")
    if len(hits) > 1:
        raise DeriveError(
            f"{len(hits)} 個欄命中,無法唯一推導:{hits}(需要人工挑選)")

    col = hits[0]
    out = copy.deepcopy(rec)
    out.pop("record_total", None)
    out["total_col"] = col
    out["printed_total"] = target
    # 破折號列:合計欄印的是「—」,模型照規矩沒放這個 key(RULES 說
    # 「缺的欄不放 key,不准補 0」)。但**這裡不是任意補 0**——是這一欄
    # 已經被錨確認過總和了,缺的那一格必然是 0,不然列和就對不上錨。
    out = fill_zero_for_col(out, col)
    return drop_mismatched_printed_totals(out)


def split_foreign_records(recs, own_anchor, other_anchors):
    """擴頁把隔壁類別的表也拉進候選頁時,模型可能把整份表照抄進來
    (實測 202304_5835_AI3 Trading:level 2 擴到 p.131/p.132,那兩頁其實是
    OCI、AC 的明細表三/四,模型逐頁抄了進來)。**這不是抄錯,是頁碼歸錯格**——
    `derive_records` 的「全有全無」在這種情況下太嚴格:一份對的 record 被
    兩份不屬於這格的 record 拖累一起判失敗。

    這裡在丟給 `derive_records` 之前先篩一輪:一份 record 的列和如果對不上
    自己的錨、卻對得上**別的類別**的錨,就判定為錯拉進來的表,先摘掉
    (連同來源留 log),不讓它進推導。摘完之後剩下的才是真正屬於這格的
    record,才適用「全有全無」。

    回傳 (kept, dropped):`dropped` 是 [(rec, 對到的類別), ...],供呼叫端記
    log / reason,不是靜默丟棄。
    """
    kept, dropped = [], []
    for rec in recs:
        sums = set(_col_sums(rec.get("rows") or []).values())
        if own_anchor is not None and own_anchor in sums:
            kept.append(rec)
            continue
        foreign = next((c for c, a in (other_anchors or {}).items()
                         if a is not None and a in sums), None)
        if foreign:
            dropped.append((rec, foreign))
        else:
            kept.append(rec)
    return kept, dropped


def derive_records(recs, anchor):
    """一格所有 record 一起推導。**要嘛全部成功,要嘛整批失敗**——一格通常
    只有 1-2 份 record(附註 + 明細表),其中一份抄錯的話,合起來看也是
    抄錯的一格,不該讓另一份先斬後奏歸檔進去。

    回傳 (derived_recs, err):err 是 None 表示全部成功,`derived_recs` 才有效;
    否則 `derived_recs` 是 None,`err` 是合併過的訊息(帶頁碼,方便追查是哪一份)。
    """
    derived, fails = [], []
    for rec in recs:
        try:
            derived.append(derive_record(rec, anchor))
        except DeriveError as e:
            page = rec.get("source_page")
            tag = f"p.{page + 1}" if isinstance(page, int) else "p.?"
            fails.append(f"{tag}: {e}")
    if fails:
        return None, "; ".join(fails)
    return derived, None
