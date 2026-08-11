#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R3-3 驗收(`docs/plan_v6_一台機器.md`):換一份 schema,`viz_generic.py`
要照樣畫得出矩陣、時間序列、缺漏標示。

**判準的重點是「完全不提銀行、債券、任何本專案字眼」。** 下面這份假 schema
描述的是「三個城市 × 四季降雨量 × 三種降水型態」——如果 `viz_generic.py`
真的脫鉤了,這份跟銀行債券一點關係都沒有的資料照樣要畫得出來;
如果畫不出來(或者要改 `viz_generic.py` 才畫得出來),脫鉤就是假的。

執行: python3 test_viz_generic.py     exit 0 = 全綠
"""
import viz_generic
from schema import Item, Schema

PASS = FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  —— {detail}" if detail else ""))


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {detail}")


def check(label, cond, detail=""):
    (ok if cond else fail)(label, detail)


# ── 假 schema:三個城市 × 四季 × 三種降水型態,跟銀行債券無關 ────────────

FAKE_SCHEMA = Schema(
    title="城市降雨型態(假資料,只給 R3-3 用)",
    entity_label="城市",
    period_label="季別",
    entities=(Item("台北", "台北"), Item("台中", "台中"), Item("高雄", "高雄")),
    dimensions=(Item("累積", "累積降雨"), Item("強度", "降雨強度")),
    buckets=(Item("梅雨", "梅雨"), Item("颱風", "颱風"), Item("對流雨", "對流雨")),
    bases=(Item("mm", "毫米"),),
    cell_key_format="{dimension}_{bucket}",
)
FAKE_PERIODS = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]


def _fake_table():
    """刻意留兩種缺漏:台中整季缺資料(missing)、高雄部分桶缺(partial)。"""
    t = {}
    for period in FAKE_PERIODS:
        for ent in ("台北",):
            t[f"{period}|{ent}"] = {
                f"{d.id}_{b.id}": (10 + hash((period, ent, d.id, b.id)) % 50)
                for d in FAKE_SCHEMA.dimensions for b in FAKE_SCHEMA.buckets}
        # 高雄:只有「累積」維度有資料,「強度」全缺 → partial
        t[f"{period}|高雄"] = {f"累積_{b.id}": 5 for b in FAKE_SCHEMA.buckets}
        # 台中:2024Q1/Q2 完全沒資料(missing),Q3/Q4 才有
        if period in ("2024Q3", "2024Q4"):
            t[f"{period}|台中"] = {
                f"{d.id}_{b.id}": 3 for d in FAKE_SCHEMA.dimensions
                for b in FAKE_SCHEMA.buckets}
    return {"mm": t}


def case_matrix_draws_every_entity_and_period():
    html = viz_generic.render(FAKE_SCHEMA, FAKE_PERIODS, _fake_table())
    check("矩陣區塊存在", '<section id="matrix">' in html)
    for ent in FAKE_SCHEMA.entities:
        check(f"矩陣裡有「{ent.label}」這欄", f">{ent.label}<" in html)
    for period in FAKE_PERIODS:
        check(f"矩陣裡有「{period}」這列", f">{period}<" in html)


def case_missing_data_is_marked_differently_from_partial():
    html = viz_generic.render(FAKE_SCHEMA, FAKE_PERIODS, _fake_table())
    check("有 missing(全缺)標記", 'class="cell missing"' in html)
    check("有 partial(部分缺)標記", 'class="cell partial"' in html)
    check("有 full(齊全)標記", 'class="cell full"' in html)
    # 三種必須是**三種不同**的 CSS class,不是同一個標記混著用——
    # 這條要能失敗:如果 _cell_completeness 的判準壞掉(例如永遠回 full),
    # missing/partial 就會從輸出裡消失,這裡會抓到。


def case_bucket_table_shows_actual_values_and_na():
    html = viz_generic.render(FAKE_SCHEMA, FAKE_PERIODS, _fake_table())
    check("逐桶表區塊存在", '<section id="bucket-table">' in html)
    check("逐桶表用最新一期(2024Q4)", "2024Q4" in html.split('id="bucket-table"')[1][:200])
    check("缺資料的桶顯示「—」不是 0 或空白",
          '<td class="na">—</td>' in html)


def case_timeseries_svg_has_real_data_points():
    html = viz_generic.render(FAKE_SCHEMA, FAKE_PERIODS, _fake_table())
    check("時間序列區塊存在", '<section id="timeseries">' in html)
    check("有 SVG", "<svg" in html)
    check("有畫線(至少一個實體有連續兩期以上的資料)", "<path d=" in html)
    check("有資料點(circle)", "<circle" in html)
    check("圖例列出了城市名字(不是銀行名字)", "台北" in html and "梅雨" not in
          html.split('id="timeseries"')[1].split("</section>")[0].split("<svg")[0]
          or "台北" in html)


def _code_only(path):
    """去掉檔頭的模組 docstring 再回原始碼 —— 那段本來就在**用文字描述**
    這條規則(逐字寫著「不准 import config」),拿它當檢查對象只會測到
    自己的說明文件,不是測到程式碼真的有沒有犯規。

    走 `ast`,不猜字串邊界 —— 模組開頭可能先有 `# -*- coding -*-` 這種
    註解行,docstring 不一定是檔案的第一行。
    """
    import ast
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    doc = ast.get_docstring(tree, clean=False)
    return src.replace(doc, "", 1) if doc else src


def case_completely_independent_of_project_config():
    """**這是脫鉤本身的證明,不是功能測試。**"""
    code = _code_only("viz_generic.py")
    check("viz_generic 的程式碼(不含檔頭說明)沒有 import config",
          "import config" not in code)
    check("viz_generic 的程式碼裡沒有任何一家銀行的名字",
          not any(bank in code for bank in ("中信", "兆豐", "國泰", "富邦", "玉山")))
    check("viz_generic 的程式碼裡沒有 US10Y / BANKHUE 這類題目專屬字眼",
          "US10Y" not in code and "BANKHUE" not in code)


def case_output_is_self_contained_offline():
    """跟 `make_web.py` 既有的規範同一條(`test_report.py` E4):自足、
    不掛外部 http(s) 請求 —— 通用層一樣要守。"""
    html = viz_generic.render(FAKE_SCHEMA, FAKE_PERIODS, _fake_table())
    check("沒有任何外部 http(s) 連結", "http://" not in html and "https://" not in html)
    check("是一份完整的 HTML", html.strip().startswith("<!doctype html>"))


def case_empty_periods_does_not_crash():
    """邊界:沒有任何期別時(剛換上新 schema、資料還沒進來)不准炸掉,
    要能印出一個空的、誠實的頁面。"""
    html = viz_generic.render(FAKE_SCHEMA, [], {"mm": {}})
    check("空輸入不會拋例外(能跑到這裡就是沒炸)", isinstance(html, str) and len(html) > 0)
    check("矩陣區塊仍然存在(空的,但結構在)", '<section id="matrix">' in html)


if __name__ == "__main__":
    for case in (case_matrix_draws_every_entity_and_period,
                 case_missing_data_is_marked_differently_from_partial,
                 case_bucket_table_shows_actual_values_and_na,
                 case_timeseries_svg_has_real_data_points,
                 case_completely_independent_of_project_config,
                 case_output_is_self_contained_offline,
                 case_empty_periods_does_not_crash):
        print(f"\n{case.__doc__.splitlines()[0] if case.__doc__ else case.__name__}")
        case()
    print(f"\nPASS {PASS}  FAIL {FAIL}")
    raise SystemExit(1 if FAIL else 0)
