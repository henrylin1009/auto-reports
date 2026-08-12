# -*- coding: utf-8 -*-
"""章節閉合(`core/closure.py`)的回歸。**每一道檢查都要有一個證明它會失敗的案例**
(`memory/checks-must-fail`)——恆真閘門看起來跟正確的檢查一模一樣,只有注入錯誤分得開。

數字全部取自玉山 202502_玉山_個體 OCI(章節模式實跑,2026-07-31),不是編的:
主表 p24 兩列 = 錨 316,073,868;子附註 (一) p24 = 23,130,069、(二) p25 = 292,943,799。

跑法:python3 test_closure.py
"""
from core import closure

A = 316_073_868
COL = "114年6月30日"


def rec(page, total, rows):
    return {"source_page": page, "source_kind": "附註", "total_col": COL,
            "printed_total": total,
            "rows": [{"name": n, "cols": {COL: v}} for n, v in rows]}


def yushan():
    return [
        rec(23, A, [("透過其他綜合損益按公允價值衡量之權益工具投資", 23_130_069),
                    ("透過其他綜合損益按公允價值衡量之債務工具投資", 292_943_799)]),
        rec(23, 23_130_069, [("上市（櫃）及興櫃股票", 21_709_081),
                             ("未上市（櫃）股票", 1_420_988)]),
        rec(24, 292_943_799, [("金融債券", 120_654_702), ("政府公債", 31_606_624),
                              ("公司債", 113_298_779), ("國外機構發行債券", 25_036_937),
                              ("證券化商品", 2_346_757)]),
    ]


def case_兩層附註閉合():
    """玉山 OCI 三張表(母表+兩份子附註)要能拼成一棵樹,根是印出合計 == 錨的那份。"""
    tree, err = closure.build(yushan(), A)
    yield ("build 成功", err is None, err)
    yield ("唯一根落在 p23(母表)", tree.roots[0]["source_page"] == 23, None)


def case_母表那兩列不是葉列():
    """這是舊管線最痛的地方:母表的兩列拿去分桶,永遠對不到任何債種桶。"""
    tree, _ = closure.build(yushan(), A)
    names = [x["name"] for _, x in tree.leaves()]
    want = ["上市（櫃）及興櫃股票", "未上市（櫃）股票", "金融債券",
            "政府公債", "公司債", "國外機構發行債券", "證券化商品"]
    yield ("葉列只剩底層 7 列", names == want, names)


def case_攤平給下游的是葉列():
    """`flatten()` 給 wide/webdata 用的攤平結果,列和要等於錨。"""
    flat, err = closure.flatten(yushan(), A)
    yield ("flatten 成功且只有一個根", err is None and len(flat) == 1, err)
    if not err:
        yield ("攤平列和 == 錨", sum(r["cols"][COL] for r in flat[0]["rows"]) == A, None)


def case_單根單份_攤平就是自己():
    """既有 155 格全是這種形狀。攤平不能把它們改掉,否則等於整庫重抄一遍。"""
    one = [rec(30, A, [("公司債", 300_000_000), ("金融債券", 16_073_868)])]
    flat, err = closure.flatten(one, A)
    yield ("單根單份直接通過", err is None, err)
    if not err:
        yield ("rows 原封不動", flat[0]["rows"] == one[0]["rows"], flat[0]["rows"])


def case_附註加明細表_兩個平行根不相加():
    """年報常見附註+明細表兩份都印著錨——它們是平行來源,不是父子,不能加成兩倍。"""
    two = yushan() + [rec(130, A, [("股票及受益證券", 23_130_069 + 1), ("債券", 292_943_799 - 1)])]
    tree, err = closure.build(two, A)
    yield ("build 成功", err is None, err)
    if not err:
        yield ("兩個根", len(tree.roots) == 2, len(tree.roots))
        flat, _ = closure.flatten(two, A)
        sums = [sum(x["cols"][COL] for x in f["rows"]) for f in flat]
        yield ("每個根攤平後各自 == 錨(不是 2 倍)", sums == [A, A], sums)


# ---- 以下每一個都必須失敗。全綠但產出是廢的,就是靠這幾個擋下來的 ----

def case_失敗_沒有根():
    """子表都在,母表沒抄到——不准用「加起來剛好等於錨」放行(子集和後門)。"""
    _, err = closure.build(yushan()[1:], A)
    yield ("回報找不到根", err is not None and "沒有任何一份 record 的印出合計 == 錨" in err, err)


def case_失敗_湊得出錨但掛不上():
    """兩份隨便湊出來的數字加起來等於錨,但誰也不是誰的子節——必須被擋。"""
    fake = [rec(9, 100_000_000, [("公司債", 100_000_000)]),
            rec(9, A - 100_000_000, [("金融債券", A - 100_000_000)])]
    _, err = closure.build(fake, A)
    yield ("被拒收", err is not None and "沒有任何一份 record 的印出合計 == 錨" in err, err)


def case_失敗_子表掛不上任何一列():
    """子表印出合計被改掉 1 元,在母表任何一列都找不到對應金額。"""
    r = yushan()
    r[2]["printed_total"] = 292_943_798
    _, err = closure.build(r, A)
    yield ("回報掛不上去", err is not None and "掛不上去" in err, err)


def case_失敗_父列撞名時不准猜():
    """兩個地方剛好有一模一樣的金額,系統不准隨便選一個當父列。"""
    r = yushan()
    r[2]["rows"].append({"name": "某某其他投資", "cols": {COL: 23_130_069}})
    _, err = closure.build(r, A)
    yield ("回報無法唯一掛載", err is not None and "無法唯一掛載" in err, err)


def case_失敗_兩層的欄對不起來():
    """子表的合計欄跟根不同名(例如子附註只印取得成本)——攤平要停下來,不能生假資料。"""
    r = yushan()
    r[2]["total_col"] = "取得成本"
    for x in r[2]["rows"]:
        x["cols"] = {"取得成本": x["cols"][COL]}
    _, err = closure.flatten(r, A)
    yield ("flatten 回報欄對不起來", err is not None and "欄對不起來" in err, err)


def case_沒有錨不准通過():
    """這個類別的錨讀不到時,不能假裝有根、放行過關。"""
    _, err = closure.build(yushan(), None)
    yield ("回報沒有錨", err is not None and "沒有錨" in err, err)


def case_merge_anchor_自帶優先():
    """record 自帶 bs_anchor,且與 fallback 一致 —— 用哪個都一樣,回自帶的值。"""
    recs = [{**yushan()[0], "bs_anchor": A}]
    got, mismatch = closure.merge_anchor(recs, A)
    yield ("回錨值", got == A, got)
    yield ("不算不一致", mismatch is False, mismatch)


def case_merge_anchor_只有_fallback():
    """record 沒帶錨(舊資料 / v3 抄的),退回 fallback,不是恆假拒收。"""
    got, mismatch = closure.merge_anchor(yushan(), A)
    yield ("回 fallback", got == A, got)
    yield ("不算不一致", mismatch is False, mismatch)


def case_merge_anchor_只有自帶():
    """fallback 讀不到(locate 找不到這份文件的 BS 頁),但資料自己帶了錨 —— 要能用。"""
    recs = [{**yushan()[0], "bs_anchor": A}]
    got, mismatch = closure.merge_anchor(recs, None)
    yield ("回自帶的錨", got == A, got)
    yield ("不算不一致", mismatch is False, mismatch)


def case_merge_anchor_打架_回_None不放行():
    """自帶錨跟 fallback 不一樣 —— 不准挑一個,值回 None,而且要標成『不一致』
    不能跟『查無可查』塌成同一種狀態(不然後面看不出兩者的差別,這正是這支函式
    要修的那個坑)。"""
    recs = [{**yushan()[0], "bs_anchor": A + 1}]
    got, mismatch = closure.merge_anchor(recs, A)
    yield ("值回 None", got is None, got)
    yield ("標成不一致", mismatch is True, mismatch)


def case_merge_anchor_自帶內部不一致():
    """多份 record 各自帶的錨彼此不同(不該發生,但要能安全處理)——同樣值回 None
    且標成不一致,不能悄悄選第一個。"""
    r1 = {**yushan()[0], "bs_anchor": A}
    r2 = {**yushan()[1], "bs_anchor": A + 1}
    got, mismatch = closure.merge_anchor([r1, r2], A)
    yield ("值回 None", got is None, got)
    yield ("標成不一致", mismatch is True, mismatch)


def main():
    bad = 0
    for case in (case_兩層附註閉合, case_母表那兩列不是葉列, case_攤平給下游的是葉列,
                 case_單根單份_攤平就是自己, case_附註加明細表_兩個平行根不相加,
                 case_失敗_沒有根, case_失敗_湊得出錨但掛不上,
                 case_失敗_子表掛不上任何一列, case_失敗_父列撞名時不准猜,
                 case_失敗_兩層的欄對不起來, case_沒有錨不准通過,
                 case_merge_anchor_自帶優先, case_merge_anchor_只有_fallback,
                 case_merge_anchor_只有自帶, case_merge_anchor_打架_回_None不放行,
                 case_merge_anchor_自帶內部不一致):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
