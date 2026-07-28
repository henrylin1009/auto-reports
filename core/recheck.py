# -*- coding: utf-8 -*-
"""算術類 reference 的可重跑驗算 —— **每個函式都回傳 bool**。

## 為什麼有這支

`reference.recheck` 的協定是「**一個回傳真值的運算式**」,`core.decisions`
的 `stale_confirmations()` 直接 `eval(recheck)` 並看真值。

B1 遷移最初把算術驗算寫成 `exec("...多行...assert...")` 塞進 recheck 字串。
那東西 `eval` 起來回傳 `None` —— 於是**驗算明明通過(assert 沒拋),
`stale_confirmations` 卻判它失敗**。當時沒發作,只因為還沒有任何東西是 CONFIRMED;
真的批准下去才會現形,而那正是最不該壞的時候。

更糟的是它逼出了第二套判定法:`test_taxonomy_migration.py` 的 M3 特判
`recheck.startswith("exec(")` 並改用 exec 跑、不拋例外就算過。
**兩套判定法對同一條 recheck 給出相反答案** —— 這種東西遲早會咬人。

所以把算術驗算收進本檔,寫成具名函式:

    recheck = "__import__('core.recheck', fromlist=['x']).group_sum_matches(...)"

於是 recheck 只剩**一種**形狀(回傳 bool 的運算式),兩套判定法合而為一,
M3 的 exec 特判可以刪掉。

## 為什麼不放進 core/decisions.py

那支是零 IO 的純函數模組(B0 的驗收條件)。本檔要 `facts.load()` 讀檔,
放進去會破壞它的分層。本檔與 `core/migrate_syn.py` 同一層(IO-aware)。

## 失敗語意

- **結構性問題**(找不到該格 / 該來源的 record)→ `raise`。
  那不是「證據不成立」,是「驗算跑不起來」,兩者不該混為一談 ——
  `stale_confirmations` 會把 raise 記成「② recheck error」並照樣降級。
- **算術對不上** → 回傳 `False`。
"""
import buckets
import facts
from config import COST_COLS


def _records(cell_key):
    recs = facts.load().get(cell_key, [])
    if not recs:
        raise AssertionError(f"recheck: 找不到格 {cell_key!r}")
    return recs


def _pick(recs, kind_prefix, cell_key):
    """取第一份 `source_kind` 以 `kind_prefix` 開頭的 record。

    用 startswith 而非精確相等:附註有「附註」與「附註(子)」兩種寫法
    (玉山 202102 p24 是後者),精確比對會漏掉。
    """
    hit = [r for r in recs if r["source_kind"].startswith(kind_prefix)]
    if not hit:
        raise AssertionError(
            f"recheck: {cell_key!r} 沒有 source_kind 以 {kind_prefix!r} 開頭的 record")
    return hit[0]


def _col(rec, prefer_cost):
    """挑要比的欄。

    `prefer_cost` 是給「附註逐項成本、明細表逐項公允」那種格用的
    (兆豐 202404 OCI 實測):口徑沒對齊就會拿成本比公允,同一個科目金額不同,
    驗算會假性失敗。對齊規則的權威來源是 `config.COST_COLS`,不在這裡另列一份。
    """
    if prefer_cost:
        for c in COST_COLS:
            if any(c in r["cols"] for r in rec["rows"]):
                return c
    return rec["total_col"]


def _sum_by_name(rec, names, col):
    want = {buckets.norm(n) for n in names}
    return sum(r["cols"][col] for r in rec["rows"]
               if buckets.norm(r["name"]) in want and col in r["cols"])


def _sum_by_group(rec, group, col):
    return sum(r["cols"][col] for r in rec["rows"]
               if r.get("group") == group and col in r["cols"])


def names_sum_matches(cell_key, detail_names, note_name, prefer_cost=False):
    """明細表若干**具名**列相加 == 附註某一列。→ bool

    「一列 = 多列」的算術推法:同一份文件裡明細表把附註的一個科目拆成幾列,
    金額加得回去 ⇒ 那幾列與附註那一列指的是同一個東西,桶必須相同。
    (富邦 CMO+RMBS = 資產證券化商品;兆豐 銀行定存單+定期存單-可轉讓 = 定存單)
    """
    recs = _records(cell_key)
    detail = _pick(recs, "明細表", cell_key)
    note = _pick(recs, "附", cell_key)
    got = _sum_by_name(detail, detail_names, _col(detail, prefer_cost))
    want = _sum_by_name(note, [note_name], note["total_col"])
    return got == want


def group_sum_matches(cell_key, group, note_name):
    """明細表某**段落**整段相加 == 附註某一列。→ bool

    同上,只是選列的方式是段落而不是列名(中信明細表『衍生金融工具』段
    整段相加 = 附註「衍生金融資產」那一列)。
    """
    recs = _records(cell_key)
    detail = _pick(recs, "明細表", cell_key)
    note = _pick(recs, "附", cell_key)
    got = _sum_by_group(detail, group, detail["total_col"])
    want = _sum_by_name(note, [note_name], note["total_col"])
    return got == want
