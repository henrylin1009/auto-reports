# -*- coding: utf-8 -*-
"""縱切一刀:rows(事實) → 分桶(判斷) → wide(視圖),用 R2 已抄好的 3 格。

目的不是做完 R4/R6,是**讓介面在哪裡斷就斷在哪裡**。所以:
  - 分桶表只涵蓋這 3 格出現過的名字,不求完整;沒收錄的名字一律 __UNKNOWN__
  - 不寫進 data.json,只印出來看

口徑規則(§4.3):wide 要的是**帳面/公允**。
一份 record 只有成本欄時,該格的逐桶帳面在文件裡不存在 → null,不准拿成本頂替。
"""
import json
import sys
import os

sys.path.insert(0, os.getcwd())
from config import BUCKET_MAP, WIDE_BUCKETS, DERIVATIVE, VALUATION_ADJ

# 只為這 3 格手寫。原名 → 桶名(config.BUCKETS)。
SYN = {
    "政府公債": "公債", "政府債券": "公債", "國庫券": "貨幣市場",
    "可轉讓定期存單": "可轉讓定存單", "可轉讓定存單": "可轉讓定存單",
    "公司債": "公司債", "公司債券": "公司債",
    "金融債": "金融債", "金融債券": "金融債",
    "資產基礎證券": "資產基礎", "資產基礎債券": "資產基礎", "證券化商品": "資產基礎",
    "其他證券及債券": "其他", "其他": "其他",
    "上市櫃公司股票": "股票", "興櫃公司股票": "股票", "非上市、上櫃、興櫃股票": "股票",
    "國內上市櫃股票": "股票", "國內興櫃股票": "股票", "國外股票": "股票",
    "國內未上市櫃股票": "股票", "股票": "股票", "受益憑證": "股票",
    # 衍生與評價調整各自成桶,不進 wide 7 桶(見 config.BUCKET_MAP 上方註解)
    "衍生工具": DERIVATIVE, "利率交換合約": DERIVATIVE, "貨幣交換": DERIVATIVE,
    "遠期外匯合約": DERIVATIVE, "信用違約交換": DERIVATIVE, "選擇權": DERIVATIVE,
    "資產交換合約": DERIVATIVE,
    "評價調整": VALUATION_ADJ, "金融資產評價調整": VALUATION_ADJ,
}

BOOK_COLS = ("公允價值總額", "帳面金額")


def basis_of(rec):
    """由**表自己**判這份 record 的逐項口徑,回傳 "成本" 或 "公允"。

    ⚠️ **不讀 agent 宣告的 `rec["basis"]`。** 舊寫法是
    `if "成本" not in (rec.get("basis") or "")` —— 漏填就當公允放行,
    「偷懶 = 變綠」,跟 D1 恆真閘門同一種病。實測後果:中信 2023H1
    OCI_GB = 61,640,884 是成本卻被當帳面用,精準重現已發布的那個 bug。

    判準是一行算術(見 memory/oracle-basis-mismatch):
        有評價調整列 → 逐項是【成本】,那列就是補到公允的差額
        沒有         → 逐項本身已是【公允】
    不看銀行、不看年報/半年報、不看附註或明細表、不看檔名。
    """
    return "成本" if any(SYN.get(r["name"]) == VALUATION_ADJ
                        for r in rec["rows"]) else "公允"


#: ⚠️ `rec["basis"]` 這個欄位**已停用,不要再讀它,也不要再叫 agent 填**。
#: 它是自由敘述(兆豐 p125 填的是「逐列雙欄:取得成本 + 公允價值總額」,一句話裡
#: 兩個詞都有),散文沒辦法機械驗證 —— 想拿它跟 basis_of() 對帳,對出來的是假警報。
#: 口徑既然推得出來就別宣告:少一個「漏填 / 填錯 = 悄悄變綠」的入口。


def pick(recs):
    """選出能給【帳面/公允】的 record。回傳 (rec, 欄名) 或 (None, 原因)。"""
    for r in recs:
        for c in BOOK_COLS:
            if all(c in row["cols"] for row in r["rows"]):
                return r, c             # 雙欄明細表:直接指名公允欄,不必推
    for r in recs:                      # 單欄附註:欄名是日期,口徑靠算術推
        if basis_of(r) == "公允":
            return r, r["total_col"]
    return None, "所有來源逐項皆為成本口徑,逐桶帳面在文件裡不存在"


def run(path):
    data = json.load(open(path, encoding="utf-8"))
    for key, recs in data.items():
        cls = recs[0]["class"]
        print(f"\n{'='*66}\n{key}")
        for r in recs:
            print(f"  p{r['source_page']}({r['source_kind']}) 逐項口徑 = {basis_of(r)}")
        rec, col = pick(recs)
        if rec is None:
            print(f"  ✗ wide 全填 null —— {col}")
            for wb in WIDE_BUCKETS:
                print(f"     {cls}_{wb} = None")
            continue
        print(f"  取值來源 p{rec['source_page']}({rec['source_kind']}) 欄「{col}」")

        book = {wb: 0 for wb in WIDE_BUCKETS}
        side = {DERIVATIVE: 0, VALUATION_ADJ: 0}     # 不進 wide 的兩段
        unknown = []
        for row in rec["rows"]:
            b = SYN.get(row["name"])
            if b in side:
                side[b] += row["cols"][col]
                continue
            wb = BUCKET_MAP.get(b)
            if wb is None:
                tag = row["name"] + (f"[桶{b}無 wide 對應]" if b else "")
                unknown.append((tag, row["cols"][col]))
                continue
            book[wb] += row["cols"][col]

        for wb in WIDE_BUCKETS:
            print(f"     {cls}_{wb:<6} = {book[wb]:>15,}")
        wide = sum(book.values())
        for k, v in side.items():
            print(f"     {'(不進 wide)':<12} {k} = {v:>15,}")
        tot = wide + sum(side.values())
        anchor = rec["printed_total"]
        print(f"  {'✓' if tot == anchor else '✗'} wide {wide:,} + 衍生 {side[DERIVATIVE]:,}"
              f" + 評價調整 {side[VALUATION_ADJ]:,} = {tot:,}"
              f"  vs 印出合計 {anchor:,}  差 {anchor-tot:,}")
        # 只有衍生可以從「債券市值」扣掉。評價調整**不能扣** —— 它不是持有的部位,
        # 是逐項成本橋到公允的差額,扣掉等於把口徑扣掉。舊版把兩者一起扣,
        # 中信算出債券MV 215,117,416 > 類別合計 209,334,435,子集大於全集。
        print(f"    債券MV = wide − 衍生 − 股票 = "
              f"{wide - side[DERIVATIVE] - book['股票']:,}")
        if unknown:
            print(f"  ⚠ __UNKNOWN__ {len(unknown)} 列:")
            for n, v in unknown:
                print(f"      {n}  {v:,}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "scratchpad/rows_r2.json")
