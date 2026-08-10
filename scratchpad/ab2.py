# -*- coding: utf-8 -*-
"""B2 = 章節上下文 + 「每張表交代自己印出的合計」。驗收改走 closure。"""
import sys, json, collections, argparse
sys.path.insert(0, ".")
import locate, fill, fill_auto, buckets
from scratchpad.ab import ctx_section
from scratchpad import closure

EXTRA = """
## 這一格可能不只一張表(章節模式的關鍵,實測最大宗的失敗就在這)
附註常常是**兩層**:主表只印兩三列大類(例如「權益工具投資」「債務工具投資」)加總等於錨,
下面的子附註 (一)(二) 才印每一類的明細;表格也可能被分頁切成上下半。

**照文件原樣抄,不要幫忙湊。** 一張表(含被分頁切開的同一張表)抄成一份 record:
  · 主表也要抄成一份 record —— 就算它只有兩列
  · 每份 record 都要填 `printed_total_self` = **這張表自己印出來的那個合計**
    (主表就是錨;子附註是它自己那一段的合計,例如 292,943,799)
  · 被分頁切開的同一張表,合成一份 record,`source_page` 填第一頁
系統會用金額把子表掛回主表的那一列,你不必判斷誰是誰的子節。
"""

def derive_total_col(rec):
    """哪一欄的列和 == 這張表自己印出的合計。0 或 2+ 個命中都算失敗,不猜。"""
    pt = rec.get("printed_total_self")
    if pt is None: return "沒填 printed_total_self"
    sums = collections.defaultdict(int)
    for x in rec["rows"]:
        for c, v in x["cols"].items(): sums[c] += v
    hit = [c for c, v in sums.items() if v == pt]
    if len(hit) == 1:
        from core import derive as _d
        _d.fill_zero_for_col(rec, hit[0])   # 沿用既有推導:合計欄確認後才補 0
    if len(hit) != 1:
        return f"p{rec['source_page']+1}:{len(hit)} 個欄命中 {hit}(印出合計 {pt:,})"
    rec["total_col"], rec["printed_total"] = hit[0], pt
    return None

def judge(recs, anchor):
    for r in recs:
        e = derive_total_col(r)
        if e: return "FAIL", e, None
    ok, why, tree = closure.build(recs, anchor)
    if not ok: return "FAIL", why, None
    lv = closure.leaves(recs, tree)
    unknown = sorted({x["name"] for _, x in lv if buckets.bucket(x) is None})
    if unknown: return "FAIL⑤", f"葉列對不到桶:{unknown}", tree
    return "PASS", None, tree

def run(cells, out):
    res = []
    for n, key in enumerate(cells, 1):
        doc, cls = key.split("|")
        print(f"[{n}/{len(cells)}] {key} ...", end=" ", flush=True)
        loc = locate.locate(f"pdf_cache/{doc}.pdf")
        ctx, pages = ctx_section(loc, cls)
        prompt = "\n".join([
            f"你在抄一份台灣銀行財報的有價證券明細表。錨(BS 合計)= {loc.anchors[cls]:,} 仟元。",
            "", fill.RULES, EXTRA,
            fill_auto.OUTPUT_CONTRACT.replace("printed_totals", "printed_totals")
            + '\n每份 record 另外必須有 `printed_total_self`(整數)。\n',
            "## 來源頁", ctx])
        raw = fill_auto.READERS["gemini"](prompt)
        data = fill_auto._parse_json(raw)
        if not data or "records" not in data:
            print("PARSE_FAIL"); res.append({"key":key,"outcome":"PARSE_FAIL"}); continue
        recs = data["records"] or []
        o, why, _ = judge(recs, loc.anchors[cls])
        print(o, (why or "")[:100])
        res.append({"key":key,"outcome":o,"reason":why,"pages":pages,"records":recs,
                    "anchor":loc.anchors[cls]})
        json.dump(res, open(out,"w"), ensure_ascii=False, indent=1)
    print(collections.Counter(r["outcome"] for r in res))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--cells"); ap.add_argument("--out", default="scratchpad/ab2.json")
    a = ap.parse_args(); run(a.cells.split(","), a.out)
