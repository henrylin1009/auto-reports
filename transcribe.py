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

#: 檢查是三值的:None=通過、NA_*=不適用、字串=失敗。
#: 「不適用」必須跟「通過」分開顯示 —— 把不適用畫成綠燈就是恆真閘門(§1 D1 的老毛病)。
NA_SINGLE = "N/A(單一來源頁)"
NA_BASIS = "N/A(兩表口徑不同,逐列不可比)"


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


def _amounts(rec):
    """{金額: [原名…]}。0 排除 —— 一方揭露「-」、另一方整列省略是常見的,不是矛盾。"""
    out = {}
    for r in rec["rows"]:
        v = r["cols"][rec["total_col"]]
        if v:
            out.setdefault(v, []).append(r["name"])
    return out


def check_cross(recs):
    """第 3 道:同一格的兩份 record 互對 —— **唯一驗得到「名字↔金額配對」的檢查**。

    ⚠️ **必須按金額比,不能按名字比。** 附註寫「金融債」、明細表寫「金融債券」,
    金額同為 29,073,073(國泰 2024 OCI 實測)。按名字比會把每一組同義詞都誤判成失敗——
    而那些名字差異正是 S6 要的同義詞候選。**第 3 道檢查與同義詞產生器是同一個機制。**

    只有年報有(附註 + 明細表)。半年報只有附註一份 → 這道不存在,
    H1 的驗證強度天生弱於 H2,不准假裝四道都在。"""
    if len(recs) < 2:
        return None                      # 不是失敗,是這道檢查不適用
    ref, *rest = recs
    base = _amounts(ref)
    bad = []
    for rec in rest:
        # 口徑不同就不能逐列比 —— 兆豐附註是「非衍生按成本 + 衍生按公允 + 評價調整」,
        # 明細表是逐列公允,兩邊金額本來就不該相等。硬比會把口徑差誤報成抄錯。
        # 這不是放水:口徑必須是**宣告的資料**,漏宣告就照樣比、照樣失敗。
        if rec.get("basis") != ref.get("basis"):
            return NA_BASIS
        cur = _amounts(rec)
        for v in set(base) | set(cur):
            if v not in base:
                bad.append(f"{v:,} 只在 p{rec['source_page']}({cur[v]})")
            elif v not in cur:
                bad.append(f"{v:,} 只在 p{ref['source_page']}({base[v]})")
    return "金額對不上 — " + "; ".join(bad) if bad else None


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
    res["③雙表互對"] = check_cross(recs) if len(recs) >= 2 else NA_SINGLE
    hard = [v for v in res.values() if v and v not in (NA_SINGLE, NA_BASIS)]
    return not hard, res


def report(recs, loc):
    ok, res = verify(recs, loc)
    print(f"{loc.name} {recs[0]['class']}  來源頁 {[r['source_page'] for r in recs]}"
          f"  葉列 {[len(r['rows']) for r in recs]}")
    for k, v in res.items():
        print(f"  {'✓' if v is None else ('–' if v in (NA_SINGLE, NA_BASIS) else '✗')} {k}"
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
