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
#: 沒抄欄合計 → 這道不存在。**不准當成通過** —— 漏抄與驗過在畫面上要分得開。
NA_NO_COL_TOTAL = "N/A(未抄逐欄合計)"
#: 降級:桶層對上但逐列對不上。**不准畫成綠燈** —— 逐列比才驗得到單一名字的配對。
PARTIAL = "△(部分只到桶層)"


def context(loc, cls, page=None):
    """產生 agent 的輸入。page=None 時列出全部候選頁。"""
    if cls not in loc.anchors:
        raise ValueError(f"{loc.name} {cls}:錨讀不到,此格不該進 S4(走視覺或拒收)")
    pages = loc.pages[cls] if page is None else [page]
    if not pages:
        raise ValueError(f"{loc.name} {cls}:無候選頁,此格走拒收")

    return context_pages(loc, cls, pages)


def context_pages(loc, cls, pages):
    """指定頁碼清單的版本。pipeline 擴張後會給比 loc.pages[cls] 更多的頁。"""
    extra = [i for i in pages if i not in loc.pages[cls]]
    out = [f"# {loc.name}  類別={cls}  錨(BS 合計)={loc.anchors[cls]:,} 仟元",
           f"# 候選頁:{loc.pages[cls]}(0-based;BS 頁 p{loc.bs_page} 已排除)"]
    if extra:
        # 講明白多出來的頁是怎麼來的:上一輪 sum(葉列) != 錨,所以擴張鄰頁。
        # agent 要知道自己在補抓,而不是以為這些頁本來就印著錨。
        out.append(f"# ⚠ 上一輪對不上,已擴張加入鄰頁 {extra} —— "
                   f"這些頁不印錨值,要找的是能補足差額的小計或子附註")
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


def check_col_totals(rec):
    """第 6 道:`printed_totals` 宣告的每一欄,都要**列相加 == 印出的欄合計**。

    為什麼要有這道:明細表的「取得成本」欄是文件裡唯一的逐桶成本來源,但
    `printed_total` 一格只存一個數(公允那欄的合計)→ 成本欄**驗不到**。
    驗不到的數字不准送上網,所以在補這道之前,國泰/富邦/玉山/兆豐的 wide_cost
    全是 null,而文件裡明明有。

    ⚠️ **沒有該欄的列要略過,不是當 0。** 兆豐明細表的衍生只有「選擇權」揭露
    取得成本,其餘 5 種缺欄 —— 那是未揭露,不是零。實測 7 列有取得成本,
    相加 44,631,513 == 印出的欄合計。

    ⚠️ 這道**只在 agent 有抄下欄合計時才存在**,漏抄就是不適用而不是通過 ——
    所以它不能當成「成本口徑一定驗過了」的保證,要看 wide 那邊有沒有取到值。
    """
    declared = rec.get("printed_totals") or {}
    bad = []
    for col, want in declared.items():
        got = sum(r["cols"][col] for r in rec["rows"] if col in r["cols"])
        if got != want:
            n = sum(col in r["cols"] for r in rec["rows"])
            bad.append(f"「{col}」{n} 列相加 {got:,} != 印出 {want:,}(差 {want - got:,})")
    return "; ".join(bad) if bad else None


def check_anchor(rec, loc):
    """第 4 道:印出合計 == BS 錨。

    ⚠️ 用錨值定位之後這道**定義上必然成立**(候選頁就是因為印著錨值才被選中),
    所以它不是獨立檢查,只是防止抄錯合計那一格。別把它當成第二個保證。"""
    a = loc.anchors.get(rec["class"])
    if a is None:
        return f"錨不存在"
    return None if rec["printed_total"] == a else f"印出合計 {rec['printed_total']:,} != 錨 {a:,}"


def check_buckets(rec, bk):
    """第 5 道:每一葉列都要對得到桶。**對不到桶的列就不是葉列。**

    為什麼需要這道:`sum(葉列) == 錨` 擋不住**兩層附註**。玉山 2021H1 OCI 的
    主附註 p23 只有兩列 ——「權益工具投資 16,018,428 / 債務工具投資 271,692,749」,
    相加剛好 = 錨 287,711,177,前四道**全綠通過**,而這份 record 一個債種明細
    都沒有(明細在子附註 p24)。四道全過、產出是廢的 —— 恆真閘門等級的洞。

    這兩列不是資料列,是指向子附註的小計。而「它是小計」這件事,分桶表自己會說:
    「透過其他綜合損益按公允價值衡量之債務工具投資」對不到任何一個債種桶。
    → 所以判準不是認標題、不是認縮排,是**對不到桶就往下挖**(pipeline 會擴張)。

    ⚠️ 這道**只會讓通過變困難**,不會讓失敗變通過。真的新名目(玉山「國外機構
    發行債券」那種)也會落在這裡 —— 那正是要的:擴張若補不上,就拒收進人審佇列,
    而不是猜一個桶或丟進「其他」。
    """
    if bk is None:
        return None
    bad = [r["name"] for r in rec["rows"] if bk.bucket(r) is None]
    if not bad:
        return None
    # 分開講:待人審是**已知擴張補不了**的,再擴幾次都一樣,直接進佇列不要空轉。
    wait = [n for n in bad if bk.pending({"name": n})]
    rest = [n for n in bad if not bk.pending({"name": n})]
    parts = []
    if rest:
        parts.append(f"{len(rest)} 列對不到桶(可能是小計,明細在別頁):{rest}")
    if wait:
        parts.append(f"{len(wait)} 列待人審:{wait}")
    return ";".join(parts)


def _amounts(rec, col=None, skip=None):
    """{金額: [列…]}。0 排除 —— 一方揭露「-」、另一方整列省略是常見的,不是矛盾。

    `col=None` 用 record 自己的合計欄;指定欄名時,**沒有該欄的列直接略過**
    (明細表的衍生只揭露公允、不揭露取得成本 —— 那是缺欄,不是金額為 0)。

    ⚠️ **裝整列不是只裝名字。** 舊版只留 `name`,下游一律 `bucket({"name": n})`
    —— `group` 在這裡被丟掉,通稱就分不出段落了。富邦 202404 Trading 實測:
    「其他」在有價證券段與衍生段各一次,舊版把兩者都算成「其他」桶,兩邊
    加總自然對不上,報成 7 筆金額對不上,而真正的差異只有一筆。
    """
    out = {}
    for r in rec["rows"]:
        if skip and skip(r):
            continue
        v = r["cols"].get(col or rec["total_col"])
        if v:
            out.setdefault(v, []).append(r)
    return out


def _names(rows):
    return tuple(r["name"] for r in rows)


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
            ba = {bucket(r) for r in base[v]}
            bb = {bucket(r) for r in cur[v]}
            if ba != bb:
                out.append(f"金額對不上 — {v:,} 兩邊的桶不同:"
                           f"p{ref['source_page']}{_names(base[v])}→{sorted(map(str, ba))} vs "
                           f"p{rec['source_page']}{_names(cur[v])}→{sorted(map(str, bb))}")
            elif None in ba:
                # 兩邊講的是同一件事,只是**都**不認得 → 這道驗不了配對,不是配對錯了。
                # 訊息要講對:玉山「國外機構發行債券」兩表同名同額,舊寫法會印
                # 「兩邊的桶不同:None vs None」,把待人審誤報成抄錯,人會去查錯地方。
                out.append(f"金額對不上 — {v:,} 兩邊都對不到桶({_names(base[v])}),"
                           f"這道驗不了它的配對")
        rest_a = {v: n for v, n in base.items() if v not in hit}
        rest_b = {v: n for v, n in cur.items() if v not in hit}
        # 對不上的餘額退一步比**桶層**:顆粒度本來就會兩邊不同,而且兩個方向都會
        # (兆豐 2024 同一份文件裡,衍生是附註 1 列 → 明細表 7 列,股票是附註 3 列
        #  → 明細表 1 列)。桶層加總相等 = 名字仍然歸對了,只是切法不同。
        # ⚠️ 這是**降級不是通過**:逐列比才驗得到單一名字的配對,桶層比驗不到。
        deg, bad = _by_bucket(rest_a, rest_b, bucket)
        m = _merged(bad, rest_a, rest_b)
        if m:
            v, rows, parts = m
            out.append(f"{'/'.join(_names(rows))} {v:,} 是合併列"
                       f"(對面 {len(parts)} 列相加相等):"
                       + "、".join(f"{'/'.join(_names(n))} {a:,}" for a, n in parts))
        elif bad:
            out.append("金額對不上 — " + "; ".join(
                f"{v:,} 只在 p{(rec if v in rest_b else ref)['source_page']}({_names(n)})"
                for v, n in sorted(bad.items())))
        if deg:
            out.append(f"{len(hit)} 項逐列對上,{len(deg)} 個桶只在桶層對上:"
                       + "、".join(f"{b} {s:,}" for b, s in deg))
    if any(o.startswith("金額對不上") for o in out):
        return "; ".join(o for o in out if o.startswith("金額對不上"))
    if out:
        return PARTIAL + " " + "; ".join(out)
    return None


def _merged(bad, a, b):
    """一邊只剩**一列**、另一邊剩下的加起來剛好等於它 ⇒ 那一列是**合併列**。

    富邦 202404 Trading 實測:附註「其他 16,378,254」= 明細表
    政府公債 1,799,570 + 公司債 3,565,242 + 其他 11,013,442
    (明細表自己註明「各項金額皆未超過本項目百分之五」故併列)。

    ⚠️ **不做子集搜尋。** 一對多是唯一解,不需要試組合;多對多有多組解,
    猜哪一組配哪一組就是在製造沒人驗得到的錯,一律回 None 讓它報失敗。
    """
    ba = {v: r for v, r in bad.items() if v in a}
    bb = {v: r for v, r in bad.items() if v in b}
    for one, many in ((ba, bb), (bb, ba)):
        if len(one) == 1 and len(many) > 1:
            (v, rows), = one.items()
            if sum(many) == v:
                return v, rows, sorted(many.items())
    return None


def coarse(recs, bk=None):
    """哪幾份 record 含**跨桶的合併列** → 回傳它們的 `source_page` 集合。

    這種 record **不准拿來分桶**。富邦 202404 附註把 政府公債 + 公司債 併進
    「其他」:照抄會讓三個桶同時錯(公債少 179 萬仟元、公司債整個消失、
    其他多出 536 萬仟元),而總額仍然等於錨 —— **六道檢查會全綠**。
    只有跨桶才排除;同桶的合併(定存單拆兩列)加總後桶是對的,照用無妨。
    """
    if len(recs) < 2 or bk is None:
        return set()
    cols = align(recs, bk.basis_of, bk.is_adj)
    if cols is None:
        return set()
    cross = len({bk.basis_of(r) for r in recs}) > 1
    skip = (lambda row: bk.is_adj(row)
            or (cross and bk.bucket(row) == DERIVATIVE))
    out = set()
    ref, *rest = recs
    base = _amounts(ref, cols[id(ref)], skip)
    for rec in rest:
        cur = _amounts(rec, cols[id(rec)], skip)
        hit = set(base) & set(cur)
        ra = {v: n for v, n in base.items() if v not in hit}
        rb = {v: n for v, n in cur.items() if v not in hit}
        _, bad = _by_bucket(ra, rb, bk.bucket)
        m = _merged(bad, ra, rb)
        if m and len({bk.bucket(r) for _, ns in m[2] for r in ns}) > 1:
            out.add((ref if m[0] in ra else rec)["source_page"])
    return out


def _by_bucket(a, b, bucket):
    """兩邊剩下對不上的金額,改用桶層加總比。回傳 (降級的桶, 真的對不上的)。"""
    if bucket is None:
        return [], sorted({**a, **b}.items())
    sa, sb = {}, {}
    for src, dst in ((a, sa), (b, sb)):
        for v, rows in src.items():
            for r in rows:
                dst.setdefault(bucket(r), []).append(v)
    deg, bad = [], {}
    for k in set(sa) | set(sb):
        va, vb = sum(sa.get(k, ())), sum(sb.get(k, ()))
        if k is not None and va == vb:
            deg.append((k, va))
        else:                                    # 桶認不得(None)或加總不等 → 真的有問題
            bad.update({v: a[v] for v in sa.get(k, ())})
            bad.update({v: b[v] for v in sb.get(k, ())})
    return sorted(deg), bad


# 「同金額不同名 → 同義詞候選」原本在這裡,已搬到 `synonyms.py`(S6)。
# 搬走的理由不是整理:舊版拿各自的 `total_col` 比,口徑不同的格子(兆豐)會配出
# 成本 ↔ 公允的假同義詞,而且沒有「金額在該欄唯一」的守門 —— 兩邊各有兩列同額時
# 誰對誰是猜的。新版共用第 3 道的 `align()`,守門與注入測試在 `test_synonyms.py`。


def verify(recs, loc):
    """回傳 (通過?, 每道檢查的結果)。recs 是同一格的所有 record。"""
    res = {}
    for rec in recs:
        tag = f"p{rec['source_page']}"
        res[f"①②列相加@{tag}"] = check_identity(rec)
        res[f"④合計==錨@{tag}"] = check_anchor(rec, loc)
        res[f"⑤列皆可分桶@{tag}"] = check_buckets(rec, buckets)
        res[f"⑥逐欄合計@{tag}"] = (check_col_totals(rec) if rec.get("printed_totals")
                                    else NA_NO_COL_TOTAL)
    res["③雙表互對"] = check_cross(recs, buckets) if len(recs) >= 2 else NA_SINGLE
    hard = [v for v in res.values()
            if v and v not in (NA_SINGLE, NA_BASIS, NA_NO_COL_TOTAL)
            and not v.startswith(PARTIAL)]
    return not hard, res


def report(recs, loc):
    ok, res = verify(recs, loc)
    print(f"{loc.name} {recs[0]['class']}  來源頁 {[r['source_page'] for r in recs]}"
          f"  葉列 {[len(r['rows']) for r in recs]}")
    for k, v in res.items():
        mark = ("✓" if v is None else "–" if v in (NA_SINGLE, NA_BASIS, NA_NO_COL_TOTAL)
                else "△" if v.startswith(PARTIAL) else "✗")
        print(f"  {mark} {k}"
              + (f"  {v}" if v else ""))
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
