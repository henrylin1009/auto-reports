# -*- coding: utf-8 -*-
"""S4 抄列:定位層 → agent 的輸入,與 agent 輸出的驗收。

**本檔不呼叫任何模型。** 讀表的是 Claude Code 自己(plan_refactor_v3.md §6c 決策 1),
所以 S4 只有兩件事:
    context()  把候選頁的純文字包成 agent 的輸入
    check_*()  驗 agent 抄回來的 rows

事實層的規矩(plan_v3_2_flow.md §2.3),違反就是把判斷洩進事實層:
  - `name` 存**表上印的原名**,不正規化、不翻譯、不分桶
  - `cols` 的 key 存**原欄名**(「取得成本」「公允價值總額」「帳面金額」…)
  - 缺的欄**不放 key**。不准補 0 —— null(未揭露)與 0 是不同的事實
  - **小計/合計不是資料列,不抄進 rows**(中信 2023H1 OCI 實測:當成資料列剛好 2 倍)

一格(doc × 類別)可能有多份 record,一份對一個來源頁。年報通常有附註與明細表兩份,
兩份互對就是第 3 道檢查 —— 同一份 PDF 內免費的雙來源交叉驗證。
"""
import json

import buckets
from config import COST_COLS, DERIVATIVE

#: 檢查是三值的:None=通過、NA_*=不適用、字串=失敗。
#: 「不適用」必須跟「通過」分開顯示 —— 把不適用畫成綠燈就是恆真閘門(§1 D1 的老毛病)。
NA_SINGLE = "N/A(單一來源頁)"
NA_BASIS = "N/A(兩表口徑不同,逐列不可比)"
#: 降級:桶層對上但逐列對不上。**不准畫成綠燈** —— 逐列比才驗得到單一名字的配對。
PARTIAL = "△(部分只到桶層)"


def context(loc, cls, page=None):
    """產生 agent 的輸入。page=None 時列出全部候選頁。"""
    if cls not in loc.anchors:
        raise ValueError(f"{loc.name} {cls}:錨讀不到,此格不該進 S4(走視覺或拒收)")
    pages = loc.pages[cls] if page is None else [page]
    if not pages:
        raise ValueError(f"{loc.name} {cls}:無候選頁,此格走拒收")

    out = [f"# {loc.name}  類別={cls}  錨(BS 合計)={loc.anchors[cls]:,} 仟元",
           f"# 候選頁:{loc.pages[cls]}(0-based;BS 頁 p{loc.bs_page} 已排除)"]
    for i in pages:
        out.append(f"\n===== page {i} =====\n{loc.text(i)}")
    return "\n".join(out)


def check_identity(rec):
    """第 1/2 道:葉列相加 == 印出合計。

    注意這道**驗不到配對** —— 它加的是金額欄,而欄的和與名字怎麼配對無關。
    名字整排錯位、金額照樣加得對。配對只能靠 check_cross。"""
    col = rec["total_col"]
    missing = [r["name"] for r in rec["rows"] if col not in r["cols"]]
    if missing:
        return f"有列缺合計欄「{col}」:{missing}"
    s = sum(r["cols"][col] for r in rec["rows"])
    if s != rec["printed_total"]:
        return (f"列相加 {s:,} != 印出合計 {rec['printed_total']:,}"
                f"(差 {rec['printed_total'] - s:,})")
    return None


def check_anchor(rec, loc):
    """第 4 道:印出合計 == BS 錨。

    ⚠️ 用錨值定位之後這道**定義上必然成立**(候選頁就是因為印著錨值才被選中),
    所以它不是獨立檢查,只是防止抄錯合計那一格。別把它當成第二個保證。"""
    a = loc.anchors.get(rec["class"])
    if a is None:
        return f"錨不存在"
    return None if rec["printed_total"] == a else f"印出合計 {rec['printed_total']:,} != 錨 {a:,}"


def _amounts(rec, col=None, skip=None):
    """{金額: [原名…]}。0 排除 —— 一方揭露「-」、另一方整列省略是常見的,不是矛盾。

    `col=None` 用 record 自己的合計欄;指定欄名時,**沒有該欄的列直接略過**
    (明細表的衍生只揭露公允、不揭露取得成本 —— 那是缺欄,不是金額為 0)。"""
    out = {}
    for r in rec["rows"]:
        if skip and skip(r):
            continue
        v = r["cols"].get(col or rec["total_col"])
        if v:
            out.setdefault(v, []).append(r["name"])
    return out


def align(recs, basis_of, is_adj):
    """挑出讓兩份 record 可逐列比較的欄。回傳 {id(rec): 欄名} 或 None(對不齊)。

    附註與明細表的口徑常常不同(兆豐 2024 Trading:附註逐項成本、明細表逐項公允),
    **但這不代表不能比** —— 明細表把成本與公允並列,挑成本那欄就對得上了。
    實測:兆豐附註 6 個非衍生科目全部精準等於明細表「取得成本」欄
    (含股票 3 列 5,935,630+1,344,916+6,081,329 = 明細表「股票」13,361,875)。

    ⚠️ 舊寫法是口徑不同就回 NA_BASIS 棄權。那讓**唯一驗得到「名字↔金額配對」的
    檢查**在最需要它的時候消失 —— 而且棄權會畫成灰色,看起來像「沒問題」。
    """
    kinds = {id(r): basis_of(r) for r in recs}
    if len(set(kinds.values())) == 1:
        return {id(r): r["total_col"] for r in recs}     # 同口徑,各用自己的合計欄
    out = {}
    for r in recs:
        if kinds[id(r)] == "成本":
            out[id(r)] = r["total_col"]
            continue
        # 這份是公允的 → 要它交出成本欄,否則兩邊沒有共同口徑
        have = [c for c in COST_COLS if any(c in row["cols"] for row in r["rows"]
                                            if not is_adj(row))]
        if not have:
            return None
        out[id(r)] = have[0]
    return out


def check_cross(recs, bk=None):
    """第 3 道:同一格的兩份 record 互對 —— **唯一驗得到「名字↔金額配對」的檢查**。

    ⚠️ **必須按金額比,不能按名字比。** 附註寫「金融債」、明細表寫「金融債券」,
    金額同為 29,073,073(國泰 2024 OCI 實測)。按名字比會把每一組同義詞都誤判成失敗——
    而那些名字差異正是 S6 要的同義詞候選。**第 3 道檢查與同義詞產生器是同一個機制。**

    只有年報有(附註 + 明細表)。半年報只有附註一份 → 這道不存在,
    H1 的驗證強度天生弱於 H2,不准假裝四道都在。

    `bk` 是判斷層(buckets 模組)。**不給就退化成只比同口徑、只比逐列** ——
    這層相依是真的:要對齊欄位就得認得出「評價調整」與「衍生」是哪幾列,
    而那是分桶知識。與其在事實層偷偷內建一份桶名,不如把相依攤在簽名上。
    """
    if len(recs) < 2:
        return None                      # 不是失敗,是這道檢查不適用
    basis_of = bk.basis_of if bk else (lambda r: r.get("basis"))
    is_adj = bk.is_adj if bk else (lambda row: False)
    bucket = bk.bucket if bk else None
    cols = align(recs, basis_of, is_adj)
    if cols is None:
        return NA_BASIS
    # 兩種列**定義上**沒有對造,不是抄錯,排除它們不是 rescue 而是把檢查的範圍講對:
    #   評價調整 —— 它就是兩個口徑的「差」,對造若存在,差就不會存在
    #   衍生     —— 跨口徑比時才排除:明細表的衍生多半不揭露取得成本
    #               (兆豐 2024 只有「選擇權」有,其餘 5 種缺欄),沒有共同口徑可比
    cross = len({basis_of(r) for r in recs}) > 1
    skip = (lambda row: is_adj(row) or (cross and bucket and bucket(row) == DERIVATIVE))
    ref, *rest = recs
    base = _amounts(ref, cols[id(ref)], skip)
    out = []
    for rec in rest:
        cur = _amounts(rec, cols[id(rec)], skip)
        hit = set(base) & set(cur)
        # ⚠️ 金額對上**還不夠**。只比金額集合的話,把明細表的「公司債」與「金融債券」
        # 名字互換,兩邊金額集合一模一樣 → 完全驗不到,而這道號稱是唯一驗得到
        # 「名字↔金額配對」的檢查。實測(2026-07-26 注入錯誤)確認過這個洞。
        # 所以同一筆金額在兩邊掛的名字,**桶必須一致**;桶認不得(None)也算失敗。
        for v in sorted(hit) if bucket else ():
            ba = {bucket({"name": n}) for n in base[v]}
            bb = {bucket({"name": n}) for n in cur[v]}
            if None in ba | bb or ba != bb:
                out.append(f"金額對不上 — {v:,} 兩邊的桶不同:"
                           f"p{ref['source_page']}{base[v]}→{sorted(map(str, ba))} vs "
                           f"p{rec['source_page']}{cur[v]}→{sorted(map(str, bb))}")
        rest_a = {v: n for v, n in base.items() if v not in hit}
        rest_b = {v: n for v, n in cur.items() if v not in hit}
        # 對不上的餘額退一步比**桶層**:顆粒度本來就會兩邊不同,而且兩個方向都會
        # (兆豐 2024 同一份文件裡,衍生是附註 1 列 → 明細表 7 列,股票是附註 3 列
        #  → 明細表 1 列)。桶層加總相等 = 名字仍然歸對了,只是切法不同。
        # ⚠️ 這是**降級不是通過**:逐列比才驗得到單一名字的配對,桶層比驗不到。
        deg, bad = _by_bucket(rest_a, rest_b, bucket)
        if bad:
            out.append("金額對不上 — " + "; ".join(
                f"{v:,} 只在 p{(rec if v in rest_b else ref)['source_page']}({n})"
                for v, n in bad))
        elif deg:
            out.append(f"{len(hit)} 項逐列對上,{len(deg)} 個桶只在桶層對上:"
                       + "、".join(f"{b} {s:,}" for b, s in deg))
    if any(o.startswith("金額對不上") for o in out):
        return "; ".join(o for o in out if o.startswith("金額對不上"))
    if out:
        return PARTIAL + " " + "; ".join(out)
    return None


def _by_bucket(a, b, bucket):
    """兩邊剩下對不上的金額,改用桶層加總比。回傳 (降級的桶, 真的對不上的)。"""
    if bucket is None:
        return [], sorted({**a, **b}.items())
    sa, sb = {}, {}
    for src, dst in ((a, sa), (b, sb)):
        for v, names in src.items():
            for n in names:
                dst.setdefault(bucket({"name": n}), []).append(v)
    deg, bad = [], []
    for k in set(sa) | set(sb):
        va, vb = sum(sa.get(k, ())), sum(sb.get(k, ()))
        if k is not None and va == vb:
            deg.append((k, va))
        else:                                    # 桶認不得(None)或加總不等 → 真的有問題
            bad += [(v, tuple(a[v])) for v in sa.get(k, ())]
            bad += [(v, tuple(b[v])) for v in sb.get(k, ())]
    return sorted(deg), sorted(set(bad))


def synonyms(recs):
    """同金額、不同名 → 同義詞候選(S6 的原料)。**不是錯誤。**

    只在年報成立:配對需要一份文件裡有 2 份以上表述,半年報只有附註一份。
    → 表從年報長、套用到半年報。"""
    if len(recs) < 2:
        return []
    ref, *rest = recs
    base = _amounts(ref)
    out = []
    for rec in rest:
        for v, names in _amounts(rec).items():
            if v in base and set(names) != set(base[v]):
                out.append((v, sorted(set(base[v]) | set(names))))
    return sorted(out)


def verify(recs, loc):
    """回傳 (通過?, 每道檢查的結果)。recs 是同一格的所有 record。"""
    res = {}
    for rec in recs:
        tag = f"p{rec['source_page']}"
        res[f"①②列相加@{tag}"] = check_identity(rec)
        res[f"④合計==錨@{tag}"] = check_anchor(rec, loc)
    res["③雙表互對"] = check_cross(recs, buckets) if len(recs) >= 2 else NA_SINGLE
    hard = [v for v in res.values()
            if v and v not in (NA_SINGLE, NA_BASIS) and not v.startswith(PARTIAL)]
    return not hard, res


def report(recs, loc):
    ok, res = verify(recs, loc)
    print(f"{loc.name} {recs[0]['class']}  來源頁 {[r['source_page'] for r in recs]}"
          f"  葉列 {[len(r['rows']) for r in recs]}")
    for k, v in res.items():
        mark = ("✓" if v is None else "–" if v in (NA_SINGLE, NA_BASIS)
                else "△" if v.startswith(PARTIAL) else "✗")
        print(f"  {mark} {k}"
              + (f"  {v}" if v else ""))
    for v, names in synonyms(recs):
        print(f"  ◆ 同義詞候選 {v:,}: {' / '.join(names)}")
    print(f"  → {'通過' if ok else '拒收'}")
    return ok


if __name__ == "__main__":
    import sys
    import locate
    if len(sys.argv) < 3:
        print("用法: python3 transcribe.py <檔名(不含.pdf)> <Trading|OCI|AC> [頁碼]")
        print("      python3 transcribe.py --verify <rows.json>")
        raise SystemExit(2)
    if sys.argv[1] == "--verify":
        data = json.load(open(sys.argv[2], encoding="utf-8"))
        allok = True
        for key, recs in data.items():
            loc = locate.locate(f"pdf_cache/{recs[0]['doc']}.pdf")
            allok &= report(recs, loc)
            print()
        raise SystemExit(0 if allok else 1)
    loc = locate.locate(f"pdf_cache/{sys.argv[1]}.pdf")
    pg = int(sys.argv[3]) if len(sys.argv) > 3 else None
    print(context(loc, sys.argv[2], pg))
