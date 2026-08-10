# -*- coding: utf-8 -*-
"""capital.verify_* 的閘門測試。

**每個閘門都要有一個「注入錯誤 → 必須失敗」的案例。** 只測 happy path 等於沒測 ——
恆真閘門在畫面上跟真閘門長得一模一樣(見 docs/;memory: checks-must-fail)。
真值來自 2025 年報,逐格與財報印出的比率核對過。
"""
import capital

# 民114年報實測值(仟元),basis 標在 key 上 —— 混用個體/合併是實測踩過的坑
TRUTH = {
    "中信|個體": dict(cet1=339_649_244, rwa=2_851_105_470, cet1_pct=11.91,
                      other_tier1=41_056_860, tier2=65_863_236, own_funds=446_569_340),
    "中信|合併": dict(cet1=398_372_097, rwa=3_576_548_169, cet1_pct=11.14),
    "兆豐|個體": dict(cet1=360_019_689, rwa=2_542_363_012, cet1_pct=14.16),
    "國泰|自行": dict(cet1=293_215_000, rwa=2_314_163_466, cet1_pct=12.67),
    "富邦|本行": dict(cet1=290_350_341, rwa=2_406_508_371, cet1_pct=12.07),
    "富邦|合併": dict(cet1=307_773_340, rwa=2_893_077_939, cet1_pct=10.64),
    "玉山|本公司": dict(cet1=274_321_302, rwa=2_287_347_649, cet1_pct=11.99),
    "玉山|合併": dict(cet1=272_904_042, rwa=2_355_778_111, cet1_pct=11.58),
}


def test_truth_passes():
    """真值必須全過。國泰的 cet1 是由比率反推(該頁只印了 RWA 與比率),故容差內即可。"""
    for k, rec in TRUTH.items():
        r = capital.verify_capital(rec)
        assert r is None, f"{k} 應通過但失敗:{r}"


def test_catches_ratio_misread():
    """注入:把資本適足率(BIS)當成 CET1 比率。

    這是實測真的犯過的錯 —— 兆豐該頁 資本適足率 16.42%、CET1 比率 14.16%,
    我的第一版 parser 撈錯行。差 2.26pt,閘門必須擋下。
    """
    bad = dict(TRUTH["兆豐|個體"], cet1_pct=16.42)
    r = capital.verify_capital(bad)
    assert r and any("對不上" in x for x in r), f"應擋下 BIS/CET1 混淆,卻回 {r}"


def test_catches_basis_mix():
    """注入:富邦合併的 CET1 配本行的 RWA。

    實測踩過 —— 富邦表是「合併|本行|合併|本行」四欄交錯,取第 1、3 個數字
    會全取到合併。基礎混用算出 12.79%,與任何一欄印出的比率都對不上。
    """
    bad = dict(cet1=307_773_340, rwa=2_406_508_371, cet1_pct=12.07)
    r = capital.verify_capital(bad)
    assert r and any("對不上" in x for x in r), f"應擋下基礎混用,卻回 {r}"


def test_catches_year_offset():
    """注入:當期 CET1 配前期 RWA(年度對位跑掉)。實測發生過兩次。"""
    bad = dict(cet1=339_649_244, rwa=2_587_361_682, cet1_pct=11.91)
    r = capital.verify_capital(bad)
    assert r, "應擋下年度錯位"


def test_catches_own_funds_break():
    """注入:自有資本少計第二類資本。"""
    bad = dict(TRUTH["中信|個體"], own_funds=380_706_104)
    r = capital.verify_capital(bad)
    assert r and any("自有資本" in x for x in r), f"應擋下加總不符,卻回 {r}"


def test_missing_printed_is_na_not_pass():
    """沒有印出比率時要回 N/A,**不准當成通過** —— 那就是恆真閘門。"""
    rec = dict(cet1=339_649_244, rwa=2_851_105_470)
    r = capital.verify_capital(rec)
    assert r == [capital.NA_NO_PRINTED], f"應標 N/A,卻回 {r}"


def test_catches_ratio_swap():
    """注入:三個比率抄反(cet1_pct 填了資本適足率、bis_pct 填了 CET1 比率)。

    單看 CET1 那道也擋得下,但**兩道一起驗**才擋得住「整組平移」——
    只驗一道時,平移後的另一個比率沒人看,錯值會被寫進 capital.json。
    """
    bad = dict(TRUTH["中信|個體"], cet1_pct=15.66, bis_pct=11.91)
    r = capital.verify_capital(bad)
    assert r and len(r) >= 2, f"應同時擋下兩個比率,卻回 {r}"


def test_catches_rwa_parts_break():
    """注入:RWA 三分項加總對不上總額(漏抄市場風險)。"""
    ok = dict(TRUTH["中信|個體"], rwa_credit=2_500_000_000,
              rwa_op=200_000_000, rwa_mkt=151_105_470)
    assert capital.verify_capital(ok) is None, "三分項合得起來時不該報錯"
    bad = dict(ok, rwa_mkt=0)
    r = capital.verify_capital(bad)
    assert r and any("信用+作業+市場" in x for x in r), f"應擋下分項不符,卻回 {r}"


def test_norm_basis():
    """五種叫法要收斂成兩個口徑;認不出來要回 None(交人審),不准猜。"""
    assert [capital.norm_basis(x) for x in ("本行", "自 行", "本公司", "個體")] == ["個體"] * 4
    assert capital.norm_basis("合併") == "合併"
    assert capital.norm_basis("銀行合併") == "合併", "同時出現時合併優先,絕不能歸個體"
    # 實跑抓到的:中信合併欄印「本行及子行」,不含「合併」二字。
    # 這格四道對帳全過、數字全對 —— 只有口徑是錯的,不特別測就永遠看不到。
    assert capital.norm_basis("本行及子行") == "合併"
    assert capital.norm_basis("本行及子公司") == "合併"
    assert capital.norm_basis("XX") is None


# ---------- 權益變動表 ----------
# 中信 民113年(202504 檔第一段)實測值,仟元
CTBC_OPEN = {"股本": 147_962_186, "資本公積": 30_139_671, "法定": 127_316_868,
             "特別": 30_273_312, "未分配": 40_812_502}
CTBC_MOVES = [
    {"name": "本期淨利", "cols": {"未分配": 49_423_933}},
    {"name": "提列法定盈餘公積", "cols": {"法定": 12_243_738, "未分配": -12_243_738}},
    {"name": "普通股現金股利", "cols": {"未分配": -19_235_084}},
    {"name": "普通股股票股利", "cols": {"股本": 10_054_326, "未分配": -10_054_326}},
    {"name": "特別盈餘公積迴轉", "cols": {"特別": -720_696, "未分配": 720_696}},
]
CTBC_CLOSE = {"股本": 158_016_512, "資本公積": 30_139_671, "法定": 139_560_606,
              "特別": 29_552_616, "未分配": 49_423_933 - 12_243_738 - 19_235_084
                                            - 10_054_326 + 720_696 + 40_812_502}


def test_equity_truth_passes():
    rec = {"open": CTBC_OPEN, "moves": CTBC_MOVES, "close": CTBC_CLOSE}
    r = capital.verify_equity(rec)
    assert r is None, f"真值應通過,卻回 {r}"


def test_equity_catches_one_sided_move():
    """注入:股票股利只記股本增加、忘了扣未分配。

    這種漏抄最危險 —— 縱向加總會錯,但單看股本欄完全正常。
    """
    moves = [dict(m) for m in CTBC_MOVES]
    moves[3] = {"name": "普通股股票股利", "cols": {"股本": 10_054_326}}
    r = capital.verify_equity({"open": CTBC_OPEN, "moves": moves, "close": CTBC_CLOSE})
    assert r and any("橫向加總" in x for x in r), f"應擋下單邊分錄,卻回 {r}"


def test_equity_catches_missing_column():
    """注入:整欄漏抄(資本公積那欄沒抄)。

    縱向會自洽(期初期末都少同一欄),只有跟表自己印的「權益總額」欄比才抓得到。
    """
    moves = [dict(m) for m in CTBC_MOVES]
    moves[0] = {"name": "本期淨利", "cols": {"未分配": 49_423_933},
                "total": 49_423_933 + 1_000_000}
    r = capital.verify_equity({"open": CTBC_OPEN, "moves": moves, "close": CTBC_CLOSE})
    assert r and any("權益總額" in x for x in r), f"應擋下漏欄,卻回 {r}"


def test_equity_catches_bs_mismatch():
    """注入:跨表對帳 —— 權益變動表期末與資產負債表對不上。"""
    rec = {"open": CTBC_OPEN, "moves": CTBC_MOVES, "close": CTBC_CLOSE}
    r = capital.verify_equity(rec, bs={"法定": 139_560_000})
    assert r and any("BS" in x for x in r), f"應擋下跨表不符,卻回 {r}"


def test_equity_null_is_a_fail_not_a_crash():
    """注入:模型照工單指示把抄不出來的格留 null。

    實測 202204_5841_AI3 就是這樣回的,原本在 `abs(got - cl[k])` 直接 TypeError,
    整份變 ERROR —— 一格沒抄到卻讓另外 19 份也看不到自己的驗收結果。
    """
    close = dict(CTBC_CLOSE, 特別=None)
    r = capital.verify_equity({"open": CTBC_OPEN, "moves": CTBC_MOVES, "close": close})
    assert r and any("沒抄到" in x for x in r), f"應把 null 記成 fail,卻回 {r}"


def test_equity_null_not_swallowed_as_zero():
    """注入:把「普通股現金股利」的金額留 null。

    這是最危險的一種 —— 若當 0 吞掉,縱向加總會自洽到只差那一筆,
    而人眼看 capital.json 只會看到一筆金額不見了、不會看到它是被驗收放行的。
    """
    moves = [dict(m) for m in CTBC_MOVES]
    moves[2] = {"name": "普通股現金股利", "cols": {"未分配": None}}
    r = capital.verify_equity({"open": CTBC_OPEN, "moves": moves, "close": CTBC_CLOSE})
    assert r and any("沒抄到" in x for x in r), f"應擋下 null 金額,卻回 {r}"
    assert not any("期初+變動" in x for x in r), "驗不了的欄不該再報縱向不符,會蓋掉真因"


# ── fair_value:AC 的公允價值 ────────────────────────────────────────
# 真值來自民114年報「非以公允價值衡量者」那張表,五家逐格讀出。
# ⚠️ 這幾條會去讀 facts/*.json 當第二來源 —— 那是刻意的,對帳本身就是被測的東西。

FV_TRUTH = {
    # doc, 帳面, 公允, 揭露範圍
    "中信": ("202504_5841_AI3", 886_706_260, 868_442_291, "全帳"),
    "兆豐": ("202504_5843_AI3", 89_434_819, 88_391_297, "扣貨幣市場"),
    "國泰": ("202504_5835_AI3", 686_643_677, 661_445_489, "全帳"),
    "富邦": ("202504_5836_AI3", 875_353_432, 848_821_775, "全帳"),
    "玉山": ("202504_5847_AI3", 522_115_384, 511_989_932, "全帳"),
}


def _fv(doc, book, fair, period="2025-12-31"):
    return {"basis": "本行", "period": period, "book": book, "fair": fair}


def test_fv_truth_passes():
    """五家真值必須全過,而且 scope 要判對。

    兆豐只揭露「債券投資」那段(AC 有 88% 是央行定期存單與短期票券),
    其餘四家揭露全帳。判錯 scope 會讓後面算浮虧率時分母差一個量級。
    """
    for bank, (doc, book, fair, scope) in FV_TRUTH.items():
        rec = _fv(doc, book, fair)
        r = capital.verify_fair_value(rec, doc)
        assert r is None, f"{bank} 應通過但失敗:{r}"
        assert rec["scope"] == scope, f"{bank} scope 判成 {rec['scope']},應是 {scope}"


def test_fv_catches_level_table_first_tier():
    """注入:抄到公允價值**等級**表,拿「合計」當帳面、「第一等級」當公允。

    國泰 p96 兩張表同頁,等級表那列也叫「按攤銷後成本衡量之債務工具投資」。
    合計 661,445,489 / 第一等級 42,517,268 → −93.6%,量級閘門要擋下。
    """
    r = capital.verify_fair_value(_fv("202504_5835_AI3", 661_445_489, 42_517_268),
                                  "202504_5835_AI3")
    assert r and any("等級表" in x for x in r), f"應擋下等級表,卻回 {r}"


def test_fv_catches_level_table_second_tier():
    """注入:同樣抄到等級表,但這次拿的是**第二等級**。

    國泰 合計 661,445,489 / 第二等級 612,004,125 → −7.5%,**量級閘門攔不住**
    (在 ±15% 內,而且很像一個合理的長久期浮虧)。只有 facts/ 對帳擋得住 ——
    等級表的「合計」是公允價值不是帳面,對不上 AC 的帳面 686,764,055。
    這條就是為什麼兩道閘門都要留。
    """
    r = capital.verify_fair_value(_fv("202504_5835_AI3", 661_445_489, 612_004_125),
                                  "202504_5835_AI3")
    assert r and any("對不上 facts" in x for x in r), f"應由對帳擋下,卻回 {r}"


def test_fv_catches_swapped_columns():
    """注入:帳面與公允抄反。量級看起來完全正常(+2.1%),只有對帳看得出來。"""
    doc, book, fair, _ = FV_TRUTH["中信"]
    r = capital.verify_fair_value(_fv(doc, fair, book), doc)
    assert r and any("對不上 facts" in x for x in r), f"應擋下抄反,卻回 {r}"


def test_fv_catches_wrong_year():
    """注入:數字是 2025 的,period 卻標成 2024。

    年報同時印當期與前期,對位跑掉是實測最常見的錯(memory: 202504 的中信與富邦
    被整份往前偏移一年)。period 決定去哪一份 facts/ 對帳,錯了就對不上。
    """
    doc, book, fair, _ = FV_TRUTH["中信"]
    r = capital.verify_fair_value(_fv(doc, book, fair, period="2024-12-31"), doc)
    assert r and any("對不上 facts" in x for x in r), f"應擋下年度偏移,卻回 {r}"


def test_fv_missing_facts_is_not_green():
    """facts/ 沒有對應那份時要記成 N/A 進人審,**不可以當通過**。

    恆真閘門就是這樣長出來的:沒得對帳 → 不報錯 → 畫面全綠。
    """
    r = capital.verify_fair_value(_fv("209904_5841_AI3", 100_000_000, 99_000_000,
                                      period="2099-12-31"), "209904_5841_AI3")
    assert r and any("N/A" in x for x in r), f"沒得對帳時不該通過,卻回 {r}"


# ── pnl / interest ──────────────────────────────────────────────────
# 真值全部逐頁核對過 202504 的個體綜合損益表與附註「利息淨收益」。

PNL_TRUTH = {
    "中信": dict(basis="個體", period="2025",
                 interest_income=153_560_890, interest_expense=82_932_181,
                 net_interest=70_628_709, oci_realized=2_965_486,
                 ac_derecog=12_422, oci_debt_ovi=499_952, net_income=57_298_147),
    "兆豐": dict(basis="個體", period="2025",
                 interest_income=116_639_707, interest_expense=78_849_648,
                 net_interest=37_790_059, oci_realized=2_123_634,
                 ac_derecog=-172_692, oci_debt_ovi=7_445_474, net_income=28_865_751),
}

INT_CTBC = dict(
    basis="個體", basis_norm="個體", period="2025",
    rows=[{"name": "放款息", "amount": 106_086_649},
          {"name": "循環信用息", "amount": 3_657_560},
          {"name": "有價證券息", "amount": 31_155_757},
          {"name": "存放央行息", "amount": 1_901_951},
          {"name": "存放及拆放同業息", "amount": 8_789_004},
          {"name": "其他", "amount": 1_969_969}],
    securities=31_155_757, subtotal_income=153_560_890,
    subtotal_expense=82_932_181, net=70_628_709, sec_ac=None, sec_oci=None)

INT_ESUN = dict(
    basis="個體", basis_norm="個體", period="2025",
    rows=[{"name": "貼現及放款利息收入", "amount": 69_980_413},
          {"name": "投資有價證券利息收入", "amount": 22_320_633},
          {"name": "信用卡循環利息收入", "amount": 2_236_879},
          {"name": "存放及拆放同業利息收入", "amount": 6_359_056},
          {"name": "其他", "amount": 2_116_190}],
    securities=22_320_633, subtotal_income=103_013_171,
    subtotal_expense=None, net=None,
    sec_ac=12_084_194, sec_oci=10_236_439)

PNL_STORE = {"202504_5841_AI3": [dict(PNL_TRUTH["中信"], basis_norm="個體")]}


def test_pnl_truth_passes():
    for k, rec in PNL_TRUTH.items():
        r = capital.verify_pnl(rec)
        assert r is None, f"{k} 應通過但失敗:{r}"


def test_pnl_catches_interest_identity_break():
    """注入:利息淨收益抄成別的數。收入−費用==淨額 是表自己印的,必須合。"""
    bad = dict(PNL_TRUTH["中信"], net_interest=70_628_000)
    r = capital.verify_pnl(bad)
    assert r and any("!= 淨額" in x for x in r), f"應擋下,卻回 {r}"


def test_pnl_catches_swapped_income_expense():
    """注入:利息收入與費用抄反。恆等式仍然成立(只差正負),所以①擋不住 ——
    這正是為什麼要多一道「收入必須大於淨收益」。"""
    bad = dict(PNL_TRUTH["中信"], interest_income=82_932_181,
               interest_expense=153_560_890, net_interest=-70_628_709)
    r = capital.verify_pnl(bad)
    assert r and any("抄反" in x for x in r), f"應擋下收入/費用抄反,卻回 {r}"


def test_pnl_null_is_fail_not_zero():
    """注入:除列AC 沒抄到(null)。**null 必須是失敗** ——
    當成 0 吞掉的話,玉山「真的沒有這一列」與「沒抄到」就永遠分不出來。"""
    bad = dict(PNL_TRUTH["中信"], ac_derecog=None)
    r = capital.verify_pnl(bad)
    assert r and any("null" in x for x in r), f"null 不該通過,卻回 {r}"
    ok = capital.verify_pnl(dict(PNL_TRUTH["中信"], ac_derecog=0))
    assert ok is None, f"真的沒有那一列(0)應該通過,卻回 {ok}"


def test_interest_truth_passes():
    r = capital.verify_interest(INT_CTBC, "202504_5841_AI3", PNL_STORE)
    assert r is None, f"中信應通過但失敗:{r}"


def test_interest_catches_row_sum_break():
    """注入:漏抄一個分項。分項加總 == 印出的小計,是表自己印的。"""
    bad = dict(INT_CTBC, rows=INT_CTBC["rows"][:-1])
    r = capital.verify_interest(bad, "202504_5841_AI3", PNL_STORE)
    assert r and any("!= 印出的小計" in x for x in r), f"應擋下漏抄,卻回 {r}"


def test_interest_catches_fabricated_securities():
    """注入:證券利息填一個自己算出來的數(不等於任何一列)。

    這是最陰的錯 —— 模型把兩列相加或估一個,加總與小計仍然對得上。
    """
    bad = dict(INT_CTBC, securities=31_000_000)
    r = capital.verify_interest(bad, "202504_5841_AI3", PNL_STORE)
    assert r and any("可能是自己算的" in x for x in r), f"應擋下,卻回 {r}"


def test_interest_catches_bucket_break():
    """注入:AC/OCI 分桶加總對不上證券利息合計(附表自己印合計)。"""
    bad = dict(INT_ESUN, sec_ac=12_084_194, sec_oci=9_000_000)
    r = capital.verify_interest(bad, "202504_5847_AI3", None)
    assert r and any("分桶" in x for x in r), f"應擋下分桶不合,卻回 {r}"


def test_interest_cross_table_catches_mismatch():
    """注入:附註小計與綜合損益表的利息收入不同。

    這道是**精確相等**不是容差 —— 實測中信/兆豐兩邊逐位元相同。
    它擋的是「抄到合併的損益表」或「年度對位跑掉」。
    """
    bad = dict(INT_CTBC, subtotal_income=153_560_000,
               rows=INT_CTBC["rows"][:-1] + [{"name": "其他", "amount": 1_969_079}])
    r = capital.verify_interest(bad, "202504_5841_AI3", PNL_STORE)
    assert r and any("綜合損益表" in x for x in r), f"應擋下跨表不符,卻回 {r}"


def test_interest_no_pnl_is_not_green():
    """還沒有 pnl 可對帳時要記成 N/A 進人審,**不可以當通過**。"""
    r = capital.verify_interest(INT_CTBC, "202504_5841_AI3", {})
    assert r and any("N/A" in x for x in r), f"沒得對帳時不該通過,卻回 {r}"


def test_interest_accepts_two_securities_rows():
    """富邦 202404 的附註**同時印了 AC 與 OCI 兩列**,工單要求相加填 securities。

    只認「等於單一分項」會把它誤判成造假 —— 實測整份被擋掉。
    這條測的是閘門不可以跟自己的工單打架。
    """
    rec = dict(basis="個體", basis_norm="個體", period="2024",
               rows=[{"name": "貼現及放款利息", "amount": 64_505_182},
                     {"name": "按攤銷後成本衡量之債務工具投資利息", "amount": 26_023_280},
                     {"name": "存放及拆放同業利息", "amount": 16_004_303},
                     {"name": "透過其他綜合損益按公允價值衡量之債務工具投資利息",
                      "amount": 5_279_614},
                     {"name": "其他", "amount": 3_946_074}],
               securities=31_302_894, subtotal_income=115_758_453,
               subtotal_expense=76_137_497, net=39_620_956,
               sec_ac=26_023_280, sec_oci=5_279_614)
    r = capital.verify_interest(rec, "202404_5836_AI3", None)
    assert r == [capital.NA_NO_PNL], f"兩列相加應該被接受,卻回 {r}"
    assert rec["scope"] == "AC+OCI", f"兩桶都有時 scope 應為 AC+OCI,卻是 {rec['scope']}"


def test_interest_still_catches_fabricated_with_buckets():
    """但有分桶也不能亂填:securities 既不等於任何一列、也不等於 AC+OCI 之和。"""
    rec = dict(basis="個體", basis_norm="個體", period="2024",
               rows=[{"name": "放款息", "amount": 100}, {"name": "有價證券息", "amount": 50}],
               securities=70, subtotal_income=150, subtotal_expense=None, net=None,
               sec_ac=30, sec_oci=20)
    r = capital.verify_interest(rec, "x", None)
    assert r and any("可能是自己算的" in x for x in r), f"應擋下,卻回 {r}"
