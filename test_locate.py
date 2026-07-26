# -*- coding: utf-8 -*-
"""定位層回歸測試(快):釘住三份已人工查過的文件,不跑全語料。

全語料普查請跑 `python3 locate.py --census --check`(約 1 分鐘)。
這支只挑三個代表案例,秒級,改 bs_anchor / locate 時隨手跑。

用法:python3 test_locate.py
"""
import locate

# (檔名, {類別: 候選頁}, 錨讀不到的類別)
# 頁碼皆 0-based,且已排除 BS 頁本身。
CASES = [
    # 正常年報:三類齊全,每類 2~4 頁 —— 附註一份、明細表一份,天然雙來源。
    ("202404_5835_AI3", {"Trading": [35, 132], "OCI": [37, 133], "AC": [38, 39, 93, 134]}, []),

    # 國泰 2021 年報:Trading 的 BS 那格是掃描影像 → 錨 None,該類整格不產出。
    # 另兩類照常運作 —— 錨是逐類的,一類讀不到不會拖垮整份。
    ("202104_5835_AI3", {"OCI": [36, 133], "AC": [37, 92, 134]}, ["Trading"]),

    # 玉山 2021H1:全語料唯一的死文件(plan_v3_2_flow.md §5 H3)。
    # Trading 錨讀得到卻 grep 不到任何頁;OCI 唯一候選頁 p23 又是分欄剝離。
    # 這格必須走拒收 —— 若哪天它「自己好了」,是定位邏輯被放寬了,要查。
    ("202102_5847_AI3", {"Trading": [], "OCI": [23]}, ["AC"]),
]


def main():
    bad = 0
    for name, want_pages, want_missing in CASES:
        loc = locate.locate(f"pdf_cache/{name}.pdf")
        got_pages = {c: loc.pages[c] for c in loc.anchors}
        got_missing = [c for c in locate.CLASSES if c not in loc.anchors]

        for label, got, want in (("候選頁", got_pages, want_pages),
                                 ("錨讀不到", got_missing, want_missing)):
            if got != want:
                print(f"✗ {name} {label}\n    實測 {got}\n    預期 {want}")
                bad += 1
        if got_pages == want_pages and got_missing == want_missing:
            print(f"✓ {name}")

    print("\n全過" if not bad else f"\n{bad} 項不符")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
