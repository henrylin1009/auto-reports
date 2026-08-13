# -*- coding: utf-8 -*-
"""規則層的回歸:**證明它不會多講,也不會跟既有的分桶表打架**。

`rules.py` 是子字串比對,子字串比對一定會誤命中,而誤命中在下游沒有任何檢查
抓得到(它產出的是分桶,而分桶錯了金額照樣加得對)。所以這裡驗的不是「有沒有
提案」,是**提案錯的時候會不會閉嘴**。

跑法:python3 test_rules.py
"""
import buckets
import config
import rules


#: `rules.propose()` 推不出來、由人審裁示進 SYN 的名字。**每一條在 buckets.py
#: 都附了出處**(哪家銀行、哪一年、哪一頁、金額),這裡只登記名字。
#: 加名字進來 = 宣告「這是人審過的判斷,不是規則轉抄」,請連同證據一起 review。
HUMAN_RULINGS = {
    # 使用者裁示(buckets.py 逐條有長註解說明依據)
    "國外機構發行債券", "不動產投資信託受益證券", "受益證券", "結構型債券",
    "CMO 擔保房貸憑證", "其他衍生金融資產", "金屬商品交換合約",
    # 同一份文件的算術推定(一列 = 多列,金額對得上)
    "CMO", "RMBS", "資產證券化", "定存單", "定期存單-可轉讓", "換匯", "商品交換",
    # 使用者裁示永遠留 PROVISIONAL 的三條(見 test_b5.py 檔頭)
    "政府債券", "貨幣交換", "外匯換匯合約",
    # 2026-08-14 華南/第一上線後補的四條。BUCKET_RULES 寫的是例示名字
    # (「銀行定期存單」「短期票券」「不動產抵押貸款證券」),沒寫通用工具詞,
    # 所以子字串比對推不出來 —— 不是沒有依據。改 BUCKET_RULES 文字會動到
    # derivations 的 revision hash、把 68 條已批准規則全降級,代價不成比例。
    "買入定期存單", "國外定期存單", "政府機構不動產抵押證券", "票券投資",
}


def case_no_smuggling():
    """表裡的每個關鍵字都要真的寫在 BUCKET_RULES 裡。"""
    extra = rules.audit(config.BUCKET_RULES)
    yield ("沒有夾帶規則外的關鍵字", not extra, f"多出來的:{extra}")


def case_agrees_with_syn():
    """跟人工審過的 SYN **一條都不准矛盾**(能推的推,推不出來可以)。

    這是最有價值的一條:SYN 的每一條都是人看過的,規則層若跟它衝突,
    衝突的那一邊一定有一個是錯的,而不知道是哪一邊就不該讓規則層上線。
    """
    bad, hit = [], 0
    for name, want in buckets.SYN.items():
        got, why = rules.propose(buckets.norm(name))
        if got == want:
            hit += 1
        elif got is not None:
            bad.append((name, want, got, why))
    yield ("與 SYN 零矛盾", not bad, f"{bad}")

    # 覆蓋率的目的是「掉下來代表有人往 SYN 塞了規則外的東西」。
    # ⚠️ 2026-08-14:原本寫成 `hit >= len(SYN) * 0.8`,而**比例門檻量不到那件事**。
    #    推不出來的那些不是髒東西,是逐條附了證據的人審裁示(國外機構發行債券、
    #    受益證券、CMO…),它們只會越積越多 —— 分母漲、比例掉,棘輪會在
    #    「又審了一批」的時候變紅,而真正要抓的「偷塞一條沒證據的」如果數量少,
    #    比例反而不會動。實測:本次補 4 條有出處的名字就從 69/86 掉到 69/90 變紅。
    #
    #    改成**逐條列名凍結**:推不出來的集合必須恰好等於下面這張清單。
    #    多一個沒登記的名字就紅(比 80% 嚴格得多 —— 一條就抓),
    #    少一個(規則層進步到推得出來了)也提醒你把它從清單刪掉。
    #    要加名字進這張清單,SYN 那邊必須同時附上出處(哪家、哪年、哪頁、金額)。
    undevirable = {n for n, want in buckets.SYN.items()
                   if rules.propose(buckets.norm(n))[0] != want}
    yield (f"SYN 有 {hit}/{len(buckets.SYN)} 條推得出來;推不出來的 "
           f"{len(undevirable)} 條必須逐條登記在案",
           undevirable == HUMAN_RULINGS,
           f"未登記:{sorted(undevirable - HUMAN_RULINGS)}  "
           f"清單裡已不需要:{sorted(HUMAN_RULINGS - undevirable)}")


def case_refuses():
    """該閉嘴的地方要閉嘴 —— 這三種都是真實踩過的。"""
    cases = [
        ("國外機構發行債券", "待人審的名目:規則裡沒寫,不准用「債券」二字硬湊"),
        ("透過其他綜合損益按公允價值衡量之債務工具投資",
         "兩層附註的小計列:含「其他」二字,子字串比對會誤判成「其他」桶,"
         "那等於拆掉第 5 道"),
        ("政府債券", "SYN 有(公債),但規則散文只寫了「政府公債」→ 規則層該說推不出來"),
    ]
    for name, why in cases:
        got, reason = rules.propose(buckets.norm(name))
        yield (f"不提案:{name}", got is None, f"卻提了 {got}({reason}) — {why}")


def case_longest_wins():
    """長關鍵字優先,而且並列時不准挑一個。"""
    yield ("可轉換公司債 → 公司債(不是被「公司債」以外的東西吃掉)",
           rules.propose("可轉換公司債")[0] == "公司債", rules.propose("可轉換公司債"))
    yield ("金融債券 → 金融債(不是公債)", rules.propose("金融債券")[0] == "金融債",
           rules.propose("金融債券"))
    saved = rules.KEYS["其他"]
    try:                                     # 注入一組並列命中,證明它真的會回 None
        rules.KEYS["其他"] = ("其他", "金融債券")
        got, why = rules.propose("金融債券")
        yield ("同長度命中兩個桶 → 拒絕提案", got is None, f"{got} / {why}")
    finally:
        rules.KEYS["其他"] = saved


def main():
    bad = 0
    for case in (case_no_smuggling, case_agrees_with_syn, case_refuses,
                 case_longest_wins):
        print(f"\n{case.__doc__.splitlines()[0]}")
        for label, ok, detail in case():
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"\n      {detail}"))
    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
