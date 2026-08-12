# -*- coding: utf-8 -*-
"""產生 golden/golden.yaml 填空模板(P0)。

規則:
  · bs_anchor / total 只在「明細表實讀 == BS 錨」時預填(兩個獨立來源一致 → 大機率正確,你瞄一眼即可)。
    兩者不一致 → 留 __FILL__ 並在註解列出兩個候選值,因為那正是有爭議、必須人判的格子。
  · buckets 一律不預填。逐桶是目前完全沒驗證的維度,預填會造成錨定偏誤,這把尺就白做了。
  · 只有 BUCKET_BLIND 名單裡的 4 份要盲抄逐桶,其餘 6 份只驗總額。

⛔ golden.yaml 已於 2026-07-25 人工填滿(60/60 總額與錨、96/96 逐桶),是全部重構的驗收依據。
   重跑本檔會【清掉那些答案】,那是好幾小時的人工核對。除非你確定要重建,否則不要跑。
"""
import json, os, sys

SRC = "extract_v2_results.json"
OUT = "golden/golden.yaml"
CLASSES = ("Trading", "OCI", "AC")

# 輸出桶(不含「調整項」——衍生/評價/備抵不入桶,只參與對帳)
OUT_BUCKETS = ["公債", "貨幣市場", "公司債", "金融債", "資產基礎", "可轉讓定存單", "其他", "股票"]

# 10 份黃金集:key → (銀行, 報表型別, 入選理由)
GOLDEN = [
    ("202104_富邦_個體", "富邦", "年報",   "掃描圖 BS,Trading 手動採信"),
    ("202202_富邦_個體", "富邦", "半年報", "掃描圖,Trading+OCI 兩格手動採信"),
    ("202102_中信_個體", "中信", "半年報", "掃描圖,Trading 手動採信(疑吞列:錨≈T+O)"),
    ("202504_兆豐_個體", "兆豐", "年報",   "表格內文字元湯"),
    ("202502_兆豐_個體", "兆豐", "半年報", "兆豐半年報基準"),
    ("202504_國泰_個體", "國泰", "年報",   "曾鎖到「證券部門」子報表"),
    ("202304_富邦_個體", "富邦", "年報",   "曾鎖錯表"),
    ("202504_玉山_個體", "玉山", "年報",   "擴頁案例"),
    ("202504_中信_合併", "中信", "合併年報", "無「重要會計項目明細表」章"),
    ("202502_中信_個體", "中信", "半年報", "中信個體半年報基準"),
]

# 要盲抄逐桶的 4 份(四種難法 × 兩種來源)
BUCKET_BLIND = {"202202_富邦_個體", "202504_兆豐_個體", "202504_國泰_個體", "202504_中信_合併"}


def p1(x):
    """0-based 頁碼 → 1-based(PDF 閱讀器看到的頁)。"""
    if x is None:
        return None
    if isinstance(x, list):
        return [i + 1 for i in x]
    return x + 1


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    L = []
    a = L.append

    a("# 黃金集正確答案(P0)——本檔是全部重構的驗收依據,請人工開 PDF 核對後填寫。")
    a("#")
    a("# 單位一律【仟元】,與財報同。填整數,不要逗號。")
    a("# 頁碼註解是 1-based(PDF 閱讀器看到的頁)。")
    a("#")
    a("# 欄位說明:")
    a("#   total       表最末【印出的總計】(含衍生),例:「透過損益按公允價值衡量之金融資產 $122,605,853」")
    a("#   bs_anchor   資產負債表【資產側】該科目的當期金額")
    a("#   buckets     逐桶金額,【不含衍生】(只有標 bucket_blind 的 4 份要填)")
    a("#   deriv       衍生金融資產小計(不入桶,但算進 total)。沒有衍生段就填 0")
    a("#   adj         調整項:備抵損失/評價調整/未攤銷溢折價等(不入桶也不是衍生)。通常是負數,沒有就填 0")
    a("#   verdict     ok = 人工讀得出來 / unreadable = 資訊已毀,任何模型都讀不出(這也是有效答案)")
    a("#")
    a("# ★★ 財報【不會】照我們的 9 桶印,要做會計意義的對應。實例(富邦 2022H1 主附註 p40):")
    a("#")
    a("#     商業本票        31,149,443  → 貨幣市場")
    a("#     可轉換公司債     21,757,691  ┐ 兩列併一桶")
    a("#     公司債           5,179,127  ┘ → 公司債 = 26,936,818")
    a("#     可轉讓定期存單    6,308,512  → 可轉讓定存單")
    a("#     政府公債         4,528,895  → 公債")
    a("#     其他             6,419,339  → 其他")
    a("#     小計            75,343,007  ← 這個 = 8 個桶的總和")
    a("#     衍生金融資產小計  47,262,846  ← deriv,不入桶")
    a("#     印出的總計      122,605,853  ← total")
    a("#")
    a("#   常見對應:多列併一桶(可轉換公司債+公司債)、整段不入桶(衍生/評價調整/備抵/減損/")
    a("#   應計利息/未攤銷溢折價)、沒有的桶填 0(不要留空)。受益憑證=股票,受益證券=資產基礎(一字之差,兩種商品)。")
    a("#")
    a("# ✅ 自檢(填完務必驗,能抓到自己的抄寫錯誤):  sum(buckets) + deriv + adj == total")
    a("#")
    a("# ★ 分桶三條規則(記這三條就夠):")
    a("#   1. 先找「小計」那條線。小計以上的列才分桶,8 桶加起來必須剛好等於小計。")
    a("#      小計以下的衍生段整段不入桶,只填 deriv 一個數字。")
    a("#   2. 衍生段裡也有一列叫「其他」——那是陷阱,不要抓。「其他」桶只收小計以上那列。")
    a("#   3. 對不上就是漏列,不要硬湊。")
    a("#")
    a("# ★ 一份表可能有多個金額欄,要挑對:")
    a("#   明細表「取得成本 / 公允價值」→ 取【公允價值】")
    a("#   AC 明細表「總額 / 備抵損失 / 未攤銷溢折價 / 帳面金額」→ 取【帳面金額】(已扣抵,adj 填 0)")
    a("#   主附註若逐列列出備抵/評價調整 → 各列照抄,該列進 adj")
    a("#")
    a("# ★ 名詞對照:")
    a("#   商業本票 / 國庫券 / 短期票券 / 附買回        → 貨幣市場")
    a("#   政府公債 / 政府債券 / 中央政府建設公債        → 公債")
    a("#   金融債券 / 次順位金融債                      → 金融債")
    a("#   公司債 + 可轉換公司債                        → 都算公司債")
    a("#   資產基礎證券 / 不動產抵押證券 / 不動產投資信託受益證券 / 受益【證券】 → 資產基礎")
    a("#   股票 / 基金受益【憑證】 / REITs / ETF        → 股票")
    a("#   可轉讓定期存單 / 央行定期存單 / 銀行定存單    → 可轉讓定存單")
    a("#   ⚠ 受益【憑證】=股票,受益【證券】=資產基礎,一字之差兩種商品")
    a("#")
    a("# ⚠ 填寫紀律:")
    a("#   1. buckets 一律【盲抄】——不要看 extract_v2_results.json,不要看網站。看了這把尺就失效。")
    a("#   2. 預填的數字是「明細表與 BS 兩個獨立來源一致」的值,瞄一眼確認即可;")
    a("#      標 __FILL__ 的是【兩來源不一致】,必須人判,註解裡有兩個候選值。")
    a("#   3. 真的判不出來 → 填 verdict: unreadable,不要猜。")
    a("")

    stats = {"prefill": 0, "fill": 0, "buckets": 0}

    for key, bank, kind, why in GOLDEN:
        v = src.get(key)
        if not v:
            a(f"# ⚠ {key} 不在 {SRC},請確認檔名")
            continue
        cls_data = v.get("cls") or {}
        meta = next((r.get("_meta") for r in cls_data.values() if r.get("_meta")), {}) or {}
        blind = key in BUCKET_BLIND

        a("# " + "═" * 76)
        a(f"# {key}  {bank}{kind}")
        a(f"# 入選理由:{why}")
        bs_pg = p1(meta.get("bs_pages"))
        if bs_pg and len(bs_pg) > 3:
            a(f"# 資產負債表:程式讀不到,是把第 {bs_pg[0]}–{bs_pg[-1]} 頁整段當影像餵進去猜的 ⚠ 請自己翻找")
        else:
            a(f"# 資產負債表:第 {bs_pg} 頁")
        np_ = p1(meta.get("note_pages"))
        if np_:
            a(f"# 主附註:第 {np_[0]}–{np_[-1]} 頁")
        det = {c: p1((cls_data.get(c, {}).get('_meta') or {}).get("det_pages")) for c in CLASSES}
        if any(det.values()):
            a("# 明細表:" + "  ".join(f"{c}=p{det[c]}" for c in CLASSES if det[c]))
        a(f"# 逐桶盲抄:{'✅ 要(這份是 4 份重點之一)' if blind else '❌ 免,只驗總額'}")
        a("# " + "═" * 76)
        a(f"{key}:")
        a(f"  bank: {bank}")
        a(f"  kind: {kind}")
        a(f"  bucket_blind: {str(blind).lower()}")

        for cls in CLASSES:
            r = cls_data.get(cls, {})
            recon, bs = r.get("recon_fair"), r.get("bs_anchor")
            agree = recon is not None and bs is not None and recon == bs
            a(f"  {cls}:")
            a("    verdict: ok")
            if agree:
                a(f"    total: {recon}          # 預填(明細/附註與BS一致),瞄一眼確認")
                a(f"    bs_anchor: {bs}      # 預填,同上")
                stats["prefill"] += 1
            else:
                a(f"    # ⚠ 兩來源不一致 → 必須人判。實讀={recon}  BS錨讀={bs}")
                if recon and bs:
                    a(f"    #   差 {abs(bs - recon):,} 仟元({abs(bs-recon)/1e5:,.1f} 億)")
                a("    total: __FILL__")
                a("    bs_anchor: __FILL__")
                stats["fill"] += 1
            if blind:
                a("    buckets:          # 盲抄,不含衍生,沒有的桶填 0")
                for b in OUT_BUCKETS:
                    a(f"      {b}: __FILL__")
                a("    deriv: __FILL__   # 衍生小計(不入桶);無衍生段填 0")
                a("    adj: 0            # 調整項(備抵損失/評價調整…),通常為負;沒有就 0")
                a("    # 自檢:sum(buckets) + deriv + adj == total")
                stats["buckets"] += len(OUT_BUCKETS)
            else:
                a("    buckets: skip")
        a("")

    os.makedirs("golden", exist_ok=True)
    if os.path.exists(OUT) and "--force" not in sys.argv:
        print(f"❌ {OUT} 已存在。若確定要覆蓋(會清掉已填的答案)請加 --force")
        return 1
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"✅ 已產生 {OUT}")
    print(f"   預填(兩來源一致,瞄一眼即可):{stats['prefill']} 類")
    print(f"   必填(兩來源不一致,要人判) :{stats['fill']} 類")
    print(f"   逐桶盲抄格子              :{stats['buckets']} 格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
