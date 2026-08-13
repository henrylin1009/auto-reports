# -*- coding: utf-8 -*-
"""四根軸 × 定義變體 × 口徑 —— 定位空間(視圖 A)的量測層。

    python3 -m sim.axes        → 印出 5家×5年×4軸(每軸取預設定義)的驗收表

## 兩層可切換,不要混在一起想

    口徑(整體/揭露/變化)  只有①②有 —— 「損失/信用風險算不算」,§11.4a 那顆鈕
    定義(variant)         四根軸都有各自的選單 —— 「用哪把尺量」,這支新加的

兩者正交:選了哪個定義,口徑鈕還是照樣切;選了哪個口徑,定義選單也還在。
以軸②為例:「浮虧率」這個定義本身有整體/揭露兩個口徑;
「對美國10Y的β」也有 —— β 是拿整體或揭露的浮虧率序列去迴歸出來的,
換口徑等於換了迴歸的因變數,β 會跟著變。

## 「整體 / 揭露」是什麼(不變,見前一版)

    軸① 信用   揭露 = OCI 桶的非公債佔比      整體 = 全部位的非公債佔比   ← 部位面
    軸② 利率   揭露 = OCI 浮虧率(已入權益)    整體 = 再加 AC 隱藏浮虧     ← 價值面
    軸③ 槓桿   不切(全行的量,沒有桶的維度)
    軸④ 報酬   不切(分母鎖 AC+OCI;中信/兆豐的附表沒有分桶利息)

## 驗收(計劃 §12.8,逐格對報告;預設定義)

    軸① 國泰 2025 = 63.7%
    軸② 2022H2 揭露·浮虧率 = 中信 −4.14 / 兆豐 −5.60 / 國泰 −8.53 / 富邦 −2.15 / 玉山 −3.96
    軸③ 2025 RWA/CET1 = 中信 8.39 / 國泰 7.89 / 富邦 8.29 / 玉山 8.34 / 兆豐 7.06(pillar3 補上)
    軸④ 2025 層1票息 = 玉山 2.60 / 中信 2.56 / 國泰 2.26 / 兆豐 1.94
"""
import config
from sim import rates, state

WHOLE, SHOWN = "整體", "揭露"

# ── 軸① 信用風險 ──────────────────────────────────────────────────────

def credit(y, b, lens=WHOLE):
    """非公債佔比 %。高 = 信用風險多。"""
    cls = ("OCI",) if lens == SHOWN else state.CLASSES
    tot = state.bonds(y, b, cls)
    return 100 * (1 - state.gov(y, b, cls) / tot) if tot else None


# ── 軸② 利率敏感度 ────────────────────────────────────────────────────

def rate(y, b, lens=WHOLE):
    """浮虧率 %。負 = 帳上比成本低。揭露端只有 OCI,整體端加上 AC 藏的那塊。"""
    pq = state.oci_unrealized(y, b)
    if not pq:
        return None                       # 分券種對不齊 → 留白,不造假浮虧
    p, q = pq
    if not p:
        return None
    if lens == SHOWN:
        return 100 * (p - q) / p
    ac = state.ac_hidden(y, b)
    if not ac:
        return None                       # 玉山 2021 沒有 fair_value,留白不造數
    loss, ac_pos, _ = ac
    return 100 * ((p - q) + loss) / (p + ac_pos)


_beta_memo = {}


def _betas(lens):
    """β 用**全期迴歸**(年頻,n=4),不是逐年數值 —— 同一個口徑只算一次,存起來。"""
    if lens not in _beta_memo:
        series = {(y, b): rate(y, b, lens) for y in state.YEARS for b in state.BANKS()}
        _beta_memo[lens] = rates.betas(series, years=state.YEARS)
    return _beta_memo[lens]


def _make_beta(cur):
    def fn(y, b, lens=WHOLE):
        # β 不是時間序列,是整段期間估一個數 —— 每年回同一個值,好接進軌跡/單期兩種畫法。
        rec = _betas(lens).get((cur, b))
        return rec["beta"] if rec else None
    return fn


beta_us = _make_beta("US")
beta_tw = _make_beta("TW")


# ── 軸③ 槓桿 —— 全部改走 pillar3.json(§7.0b),capital.json 沒有 exposure ──

def leverage_ratio(y, b, lens=None):
    """RWA / CET1(倍)。= 100 / CET1率。"""
    r = state.pillar3_rec(y, b)
    return r["rwa"] / r["cet1"] if r else None


def leverage_true(y, b, lens=None):
    """暴險總額 / 第一類資本(倍)。「真槓桿」—— 不像 RWA/CET1 那樣被風險權數壓過。"""
    r = state.pillar3_rec(y, b)
    if not r or not r.get("exposure"):
        return None
    t1 = r["cet1"] + r.get("other_t1", 0)
    return r["exposure"] / t1


def leverage_density(y, b, lens=None):
    """RWA / 暴險總額 %。資產本身有多「重」(風險權數平均起來多高)。"""
    r = state.pillar3_rec(y, b)
    return 100 * r["rwa"] / r["exposure"] if r and r.get("exposure") else None


# ── 軸④ 報酬 —— 四層累加,分母全部鎖平均(AC+OCI) ──────────────────────

def _layer(y, b, n):
    rec = state.yield_record(y, b)
    if not rec:
        return None
    pos, L1 = rec["pos"], rec["yield"]
    if n == 1:
        return L1
    p = state.pnl(y, b)
    if not p:
        return None
    L2 = L1 + (p["oci_realized"] + p["ac_derecog"]) / state.E / pos * 100
    if n == 2:
        return L2
    L3a = L2 + p["oci_debt_ovi"] / state.E / pos * 100
    if n == 3:
        return L3a
    h0, h1 = state.ac_hidden(y - 1, b), state.ac_hidden(y, b)
    if not h0 or not h1:
        return None                        # 缺前一年 fair_value,留白不造數(§12.6 陷阱7同精神)
    return L3a + (h1[0] - h0[0]) / pos * 100


def ret_l1(y, b, lens=None): return _layer(y, b, 1)
def ret_l2(y, b, lens=None): return _layer(y, b, 2)
def ret_l3a(y, b, lens=None): return _layer(y, b, 3)
def ret_l3b(y, b, lens=None): return _layer(y, b, 4)


# ── 組裝 ─────────────────────────────────────────────────────────────
# 每根軸的 switchable 管整體/揭露(口徑鈕);每個 variant 是「用哪把尺量」,
# 彼此正交 —— 選哪個 variant 不影響口徑鈕能不能按,反過來也一樣。

AXES = [
    # lens_note:「帳上看得到／全部位」在這根軸上實際是哪些桶 —— 兩根軸的組成不一樣
    # (①是三桶、②是 OCI+AC),所以按鈕只講可見性,精確定義交給這行副標。
    {"id": "credit", "label": "信用風險", "switchable": True,
     "lens_note": {"揭露": "FVOCI 桶", "整體": "FVTPL+FVOCI+AC 三桶"},
     "variants": [
         {"id": "share", "label": "非公債佔比", "unit": "%", "more": "信用風險更多",
          "hint": "部位面:信用風險放在哪個桶", "fn": credit},
     ]},
    {"id": "rate", "label": "利率敏感度", "switchable": True,
     "lens_note": {"揭露": "已入權益的 OCI 浮虧", "整體": "再加 AC 隱藏浮虧"},
     "variants": [
         {"id": "loss", "label": "浮虧率", "unit": "%", "more": "浮虧更大", "invert": True,
          "hint": "價值面:AC 藏起來的浮虧算不算", "fn": rate},
         {"id": "beta_us", "label": "對美國10Y", "unit": "pt/100bp", "more": "對利率更敏感", "invert": True,
          "hint": "升息100bp,浮虧率跌幾個百分點(美國10Y)",
          "caveat": "全期迴歸估的單一係數(年頻 n=4),不是逐年實測值;"
                    "R² 高多半是 2022 那次升息撐起來的,別當穩健係數看",
          "fn": beta_us},
         {"id": "beta_tw", "label": "對台灣10Y", "unit": "pt/100bp", "more": "對利率更敏感", "invert": True,
          "hint": "升息100bp,浮虧率跌幾個百分點(台灣10Y)",
          "caveat": "全期迴歸估的單一係數(年頻 n=4);"
                    "corr(ΔUS,ΔTW)=0.946,雙因子沒做,兩個 β 分開看",
          "fn": beta_tw},
     ]},
    {"id": "leverage", "label": "槓桿", "switchable": False,
     "variants": [
         {"id": "rwa_cet1", "label": "RWA/CET1", "unit": "倍", "more": "槓桿更高",
          "hint": "全行的量,沒有桶的維度,不隨口徑切換", "fn": leverage_ratio},
         {"id": "true", "label": "暴險/第一類", "unit": "倍", "more": "槓桿更高",
          "hint": "真槓桿,不像 RWA/CET1 被風險權數壓過", "fn": leverage_true},
         {"id": "density", "label": "RWA密度", "unit": "%", "more": "資產風險更重",
          "hint": "資產本身平均風險權數多高", "fn": leverage_density},
     ]},
    {"id": "ret", "label": "報酬", "switchable": False,
     "variants": [
         {"id": "l1", "label": "票息", "unit": "%", "more": "報酬更高",
          "hint": "分母鎖平均(AC+OCI),已知的坑,不開放切換", "fn": ret_l1},
         {"id": "l2", "label": "+已實現", "unit": "%", "more": "報酬更高",
          "hint": "加計 OCI 已實現處分損益 + AC 除列損益", "fn": ret_l2},
         {"id": "l3a", "label": "+OCI未實現", "unit": "%", "more": "報酬更高",
          "hint": "再加計 OCI 當期未實現評價變動", "fn": ret_l3a},
         {"id": "l3b", "label": "+AC隱藏浮虧", "unit": "%", "more": "報酬更高",
          "hint": "再加計 AC 隱藏浮虧的年度變化(缺前一年 fair_value 就留白)",
          "fn": ret_l3b},
     ]},
]


def flags():
    """每一格的口徑註記 —— 並列比較時會用到兩把尺的地方,前端要能標出來。

    ★ 兆豐的 `fair_value.scope = "扣貨幣市場"` **不標記**(定案 2026-08-06):
    分母已經把五家都壓到「只有債券」,算完是同一個口徑;分子差的那塊是貨幣市場、
    浮虧≈0。口徑一樣就沒問題,不加沒有內容的警示。
    """
    out = {}
    for y in state.YEARS:
        for b in state.BANKS():
            note = []
            if (y, b) in state.misaligned():
                note.append("帳面與成本的分券種對不齊(兩張表顆粒度不同)→ 利率軸留白")
            if not state.has_basis(y, b, "wide", "AC"):
                note.append("AC 逐桶在 data.json 裡不存在(只有全帳合計)→ 利率軸整體端、報酬軸+AC隱藏浮虧 留白")
            elif not state.ac_hidden(y, b):
                note.append("沒有 AC 公允揭露 → 利率軸整體端、報酬軸+AC隱藏浮虧 留白")
            sc = state.yield_pct(y, b)
            if sc and sc[1] == "僅AC":
                note.append("利息只涵蓋 AC 桶,分母同步只取 AC")
            if note:
                out[f"{y}|{b}"] = note
    return out


def _variant_table(fn, switchable):
    lens = {}
    for L in ([WHOLE, SHOWN] if switchable else [WHOLE]):
        vals = {f"{y}|{b}": fn(y, b, L) for y in state.YEARS for b in state.BANKS()}
        lens[L] = {k: round(v, 3) for k, v in vals.items() if v is not None}
    return lens


def payload():
    """給前端的一包。

    軸 → variants[] → lens{整體/揭露 或 只有整體}。多一層是因為現在每根軸
    有好幾把尺,不再是「軸=一個公式」。
    """
    state.wide()  # 確保 wide() 的來源判斷先跑過(payload 最後才讀 source 標記)
    D, src = state.wide()
    axes = []
    for a in AXES:
        variants = []
        for v in a["variants"]:
            variants.append({k: v[k] for k in ("id", "label", "unit", "hint", "more", "invert")
                             if k in v} | ({"caveat": v["caveat"]} if "caveat" in v else {})
                            | {"lens": _variant_table(v["fn"], a["switchable"])})
        axes.append({"id": a["id"], "label": a["label"], "switchable": a["switchable"],
                     "lens_note": a.get("lens_note"),
                     "variants": variants, "default": a["variants"][0]["id"]})
    return {"source": src, "banks": state.BANKS(), "years": list(state.YEARS),
            # 2026-08-12:`config.BANK_COLORS[b]` 直接索引沒有 fallback —— 加第 6 家
            # 銀行、還沒被人手動配色時就會整支 KeyError。灰色是明確的「還沒配色」
            # 訊號,不是猜色;等真的要上圖表再由 config.BANK_COLORS 補一筆品牌色。
            "colors": {b: config.BANK_COLORS.get(b, "#9aa0a8") for b in state.BANKS()},
            "axes": axes, "flags": flags()}


def main():
    D, src = state.wide()
    print(f"定位空間 四軸 × 定義變體 × 口徑    data.json 來源:{src}")
    for a in AXES:
        for v in a["variants"]:
            for L in ([SHOWN, WHOLE] if a["switchable"] else [WHOLE]):
                tag = f"[{L}]" if a["switchable"] else "[不切]"
                print(f"\n{a['label']}·{v['label']} ({v['unit']}) {tag}")
                print("     " + "".join(f"{y:>9}" for y in state.YEARS))
                for b in state.BANKS():
                    cells = "".join(
                        (lambda x: f"{x:8.2f} " if x is not None else "     —   ")(
                            v["fn"](y, b, L)) for y in state.YEARS)
                    print(f"{b:>4} {cells}")


if __name__ == "__main__":
    main()
