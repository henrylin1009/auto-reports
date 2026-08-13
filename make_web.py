"""產生給 GitHub Pages 的網頁:site/index.html(兩張儀表板圖 + Excel 下載)。
讀 data.json;圖用 matplotlib(伺服器/CI 需裝 CJK 字型,如 fonts-noto-cjk)。
"""
import json, re, shutil, datetime
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from config import BANK_COLORS, CLASSES

SITE=Path("site"); SITE.mkdir(exist_ok=True)
# 唯一設定源:web/tokens.css(複核台用 <link> 讀同一份)。GitHub Pages 要單檔可攜,這裡內嵌。
TOKENS_CSS=open("web/tokens.css", encoding="utf-8").read()
D=json.load(open("data.json")); PERIODS=D["periods"]; BANKS=D["banks"]; DATA=D["data"]
# 合併報表(AI1):獨立分頁用,不進主要 wide/banks(口徑範圍比個體大,混比會失真)
# 合併有季報,時間軸用季度(periods_consol,如 2023Q1…2025Q4),與個體的半年軸(periods)分開
BANKS_CONSOL=D.get("banks_consol",[])
# 合併報表的兩個口徑都交給前端,由 interactive_html 的口徑鈕自己挑有資料的那個。
# **不要在這裡寫死「合併=成本」** —— 那是今天中信合併附註的長相(逐項印取得成本
# + 一整筆金融資產評價調整,所以逐桶帳面在文件裡不存在),不是規則。
WIDE_CONSOL=D.get("wide_consol",{}); WIDE_COST_CONSOL=D.get("wide_cost_consol",{})
def _any_val(t):
    return any(v is not None for cols in (t or {}).values() for v in (cols or {}).values())
HAS_CONSOL=bool(BANKS_CONSOL) and (_any_val(WIDE_CONSOL) or _any_val(WIDE_COST_CONSOL))
PERIODS_CONSOL=D.get("periods_consol") or PERIODS
# 待複核旗標(bridge_v2 從 extract_v2 的 _needs_review / 弱錨 / 錨可疑 浮上)
REVIEW=D.get("review",{}); REVIEW_CONSOL=D.get("review_consol",{})
# 企業品牌色來自 config.BANK_COLORS(全站唯一設定源);下方 JS 的 BANKHUE 也由此注入,避免多處各寫一份
COLOR=BANK_COLORS
_BANKHUE_JS="const BANKHUE="+json.dumps(BANK_COLORS,ensure_ascii=False)+";"
# 圖表期間:最近 6 個「有資料」的期(自動,不寫死年份)
_have=[p for p in PERIODS if any((DATA.get(f"{p}|{b}")) for b in BANKS)]
SHOW=(_have or PERIODS)[-6:]

# 中文字型(Linux CI: Noto CJK;mac: PingFang)
for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/truetype/noto/NotoSansCJKtc-Regular.otf",
          "/System/Library/Fonts/PingFang.ttc","/Library/Fonts/Arial Unicode.ttf"]:
    try: fm.fontManager.addfont(p); plt.rcParams["font.family"]=fm.FontProperties(fname=p).get_name(); break
    except Exception: pass
plt.rcParams["axes.unicode_minus"]=False

def rb(per,bank): return DATA.get(f"{per}|{bank}")
def mv(b): return b["公債"]+b["公司債"]+b["金融債"]+b["其他"]
def tot(r): return sum(mv(r[c]) for c in CLASSES)

def panel(ax, fn, title, pct=False):
    ax.set_title(title, fontsize=10, fontweight="bold"); nb=len(BANKS); npd=len(SHOW); w=0.8/npd
    for bi,bank in enumerate(BANKS):
        for pi,per in enumerate(SHOW):
            r=rb(per,bank);  v=None if r is None else fn(r)
            if v is None: continue
            ax.bar(bi+(pi-npd/2)*w+w/2, v, width=w*0.95, color=COLOR[bank])
    ax.set_xticks(range(nb)); ax.set_xticklabels(BANKS, fontsize=8); ax.grid(axis="y",color="#eee"); ax.set_axisbelow(True)
    if pct: ax.set_ylim(0,1); ax.yaxis.set_major_formatter(lambda y,_:f"{y*100:.0f}%")
    for s in ("top","right"): ax.spines[s].set_visible(False)

cmv=lambda c:(lambda r:mv(r[c])); cpct=lambda c:(lambda r:(mv(r[c])/tot(r) if tot(r) else 0))
tmv=lambda k:(lambda r:sum(r[c][k] for c in CLASSES))
credit=lambda r:sum(r[c]["公司債"]+r[c]["金融債"] for c in CLASSES)
tpct=lambda k:(lambda r:(tmv(k)(r)/tot(r) if tot(r) else 0))

def dash1():
    fig,ax=plt.subplots(2,4,figsize=(18,8)); fig.suptitle("債券投資 — 按會計分類 (Trading/OCI/AC) 單位:億元",fontsize=13,fontweight="bold"); A=ax.flat
    panel(next(A),tot,"債券MV(合計)"); panel(next(A),cmv("Trading"),"Trading MV"); panel(next(A),cmv("OCI"),"OCI MV"); panel(next(A),cmv("AC"),"AC MV")
    panel(next(A),cpct("Trading"),"Trading 比重",True); panel(next(A),cpct("OCI"),"OCI 比重",True); panel(next(A),cpct("AC"),"AC 比重",True); next(A).axis("off")
    fig.tight_layout(rect=[0,0,1,0.96]); fig.savefig(SITE/"圖1.png",dpi=110); plt.close(fig)
def dash2():
    fig,ax=plt.subplots(2,4,figsize=(18,8)); fig.suptitle("債券投資 — 按債種 (公債/信用債/公司債/金融債/其他) 單位:億元",fontsize=13,fontweight="bold"); A=ax.flat
    panel(next(A),tot,"債券MV(合計)"); panel(next(A),tmv("公債"),"公債MV"); panel(next(A),credit,"信用債MV"); panel(next(A),tmv("金融債"),"金融債MV")
    panel(next(A),tmv("公司債"),"公司債MV"); panel(next(A),tmv("其他"),"其他債MV"); panel(next(A),tpct("公債"),"公債比重",True); panel(next(A),lambda r:(credit(r)/tot(r) if tot(r) else 0),"信用債比重",True)
    fig.tight_layout(rect=[0,0,1,0.96]); fig.savefig(SITE/"圖2.png",dpi=110); plt.close(fig)

dash1(); dash2()

# 數字明細(那張 spreadsheet)2026-08-13 搬到資料核對頁(core/webdata.py:wide_table()
# + web/workbench.js:wideTableCard())——分析頁不再自己畫一份,見 docs/plan_ui_一層導覽.md R1。

# ---- 互動儀表板(A跨行比較 / B時間趨勢 / D增減 / C探索 + KPI + 含CP開關)----
def interactive_html(prefix="", banks=None, wide=None, wide_cost=None, periods=None, review=None,
                     expose_trend_range=True, include_chartjs=True, autorun=True):
    """跨行比較+時間趨勢+KPI 儀表板。prefix 非空時可重複呼叫產生第二份(如「合併報表」分頁),
    所有元素 id 會自動加前綴避免跟預設頁衝突,整段 JS 包成 IIFE 避免變數(BANKS/PERIODS/...)重複宣告。"""
    banks = list(banks) if banks is not None else BANKS
    wide_data = wide if wide is not None else D.get("wide", {})
    cost_data = wide_cost if wide_cost is not None else D.get("wide_cost", {})
    _p = periods if periods is not None else (_have or PERIODS)
    _rev = review if review is not None else REVIEW
    payload=json.dumps({"periods":_p,"banks":banks,"wide":wide_data,
                        "wide_cost":cost_data,"review":_rev}, ensure_ascii=False)
    css="""<style>
.ix{font-family:inherit}
.ix-kpihead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.ix-cfg{position:relative;display:inline-block}
.ix-cfg>summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#5f6672;border:1px solid #e0e3e8;border-radius:9px;padding:8px 12px;background:#fff;user-select:none}
.ix-cfg>summary::-webkit-details-marker{display:none}
.ix-cfg>summary:hover{border-color:#c6cbd4}
.ix-cfg>summary b{color:#111827;font-weight:600}
.ix-cfg-ic{font-size:13px}
.ix-cfg-ar{color:#8a919e;font-size:11px}
.ix-cfg[open]>summary{border-color:#4f46e5}
.ix-cfg-panel{position:absolute;z-index:20;top:calc(100% + 6px);left:0;background:#fff;border:1px solid #e9ebef;border-radius:12px;box-shadow:0 10px 30px rgba(16,24,40,.12);padding:12px 14px;min-width:280px}
.ix-cfg-h{font-size:12px;color:#8a919e;margin-bottom:10px}
.ix-cfg-panel label{display:flex;align-items:center;gap:8px;font-size:13px;color:#111827;padding:7px 6px;border-radius:7px;cursor:pointer;flex-wrap:wrap}
.ix-cfg-panel label:hover{background:#f5f6f8}
.ix-cfg-panel input{accent-color:#4f46e5;width:15px;height:15px}
.ix-cfg-note{width:100%;padding-left:23px;font-size:11px;color:#a0a6b0;margin-top:-2px}
.ix-ctl{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.ix-ctl label{font-size:12px;color:#8a919e;margin-left:6px}
.ix-ctl select{height:34px;border:1px solid #e0e3e8;border-radius:8px;padding:0 8px;background:#fff;color:#111827;font-size:13px;outline:none}
.ix-ctl select:hover{border-color:#c6cbd4}
.ix-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.ix-kcard{background:#fff;border:1px solid #e9ebef;border-radius:12px;padding:14px 16px}
.ix-klabel{font-size:12px;color:#8a919e;margin-bottom:8px}
.ix-kval{font-size:24px;font-weight:600;color:#111827;line-height:1.15;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.ix-ksub{font-size:12px;color:#8a919e;margin-top:4px}
.ix-legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px;font-size:12px;color:#5f6672;align-items:center}
.ix-legend span{display:flex;align-items:center;gap:5px}
.ix-sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.ix-row{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.ix-name{width:38px;font-size:13px;color:#111827;text-align:right;flex:none}
.ix-track{flex:1;display:flex;height:30px;border-radius:6px;overflow:hidden;background:#f2f3f5}
.ix-s2{height:100%;display:flex;align-items:center;justify-content:center;overflow:hidden;box-shadow:inset -1.5px 0 0 #fff}
.ix-s2 .s2l{font-size:10px;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.ix-tot{width:82px;font-size:12px;color:#5f6672;text-align:right;flex:none;font-variant-numeric:tabular-nums}
.ix-na{flex:1;height:26px;font-size:11px}
.ix-tip{position:fixed;z-index:99;pointer-events:none;background:#111827;color:#fff;border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.6;box-shadow:0 8px 24px rgba(16,24,40,.2);max-width:230px;opacity:0;transition:opacity .1s}
.ix-tip b{color:#a5b4fc}
.lg-item{cursor:pointer;padding:3px 8px;border-radius:7px;transition:all .12s;user-select:none}
.lg-item:hover{background:#eef0f3}
.lg-item.sel{background:#eef0f3;font-weight:600;color:#111827}
.lg-item.dim{opacity:.35}
.ix-s2.dim,.ix-cell.dim{opacity:.18}
.ix-s2{transition:opacity .15s}
.ix-name.click{cursor:pointer;border-bottom:1px dashed #c6cbd4}
.ix-name.click:hover{color:#4f46e5;border-color:#4f46e5}
.ix-drill{background:#f8f9fb;border:1px solid #e9ebef;border-radius:12px;padding:16px 18px;margin-top:6px}
.ix-drill-h{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
.ix-drill-h b{font-size:15px;color:#111827}
.ix-drill-h span{font-size:12px;color:#8a919e}
.ix-drill-x{margin-left:auto;cursor:pointer;border:none;background:none;color:#8a919e;font-size:16px;line-height:1;padding:2px 6px;border-radius:6px}
.ix-drill-x:hover{background:#eef0f3;color:#111827}
.ix-mini{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.ix-mini .lb{width:52px;font-size:12px;color:#5f6672;text-align:right;flex:none}
.ix-mini .tk{flex:1;display:flex;height:18px;border-radius:5px;overflow:hidden;background:#eef0f3}
.ix-mini .vv{width:56px;font-size:12px;color:#5f6672;text-align:right;flex:none;font-variant-numeric:tabular-nums}
.ix-drill-ft{display:flex;gap:18px;align-items:center;margin-top:12px;font-size:12px;color:#5f6672;flex-wrap:wrap}
.ix-concl{margin-top:4px}
.ix-cl-h{font-size:12px;color:#8a919e;margin-bottom:10px}
.ix-cl-h span{color:#b0b6c0}
.ix-cl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}
.ix-cl{display:flex;gap:10px;align-items:flex-start;background:#f8f9fb;border:1px solid #eef0f3;border-radius:10px;padding:11px 13px}
.ix-cl-dot{width:8px;height:8px;border-radius:3px;margin-top:5px;flex:none}
.ix-cl-tag{font-size:11px;color:#8a919e}
.ix-cl-bk{font-size:15px;font-weight:600;color:#111827;margin:1px 0 2px}
.ix-cl-note{font-size:11px;color:#5f6672;line-height:1.5}
.ix-panel-toprow{justify-content:space-between;padding-bottom:14px;border-bottom:1px solid #eef0f3}
.ix-bar-info{font-size:12px;color:#8a919e}
.ix-bar-info b{color:#111827;font-weight:600}
.ix-bar-ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ix-bar-sel{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#5f6672}
.ix-bar-sel select{height:36px;border:1px solid #e0e3e8;border-radius:9px;padding:0 10px;background:#fff;color:#111827;font-size:13px;font-weight:600;outline:none;cursor:pointer}
.ix-bar-sel select:hover{border-color:#c6cbd4}
.ix-bar-dash{color:#8a919e;font-size:13px}
.ix-panel{background:#fff;border:1px solid #e9ebef;border-radius:14px;padding:16px 20px;margin:0 0 20px;display:flex;flex-direction:column;gap:14px}
.ix-panel-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ix-panel-lbl{font-size:12px;color:#8a919e;width:64px;flex:none}
.ix-chiprow{display:flex;gap:8px;flex-wrap:wrap}
.incl-chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:6px 10px;border:1px solid #e9ebef;border-radius:20px;cursor:pointer;background:#fff;user-select:none}
.incl-chip:hover{border-color:#c6cbd4}
.incl-chip input{margin:0;accent-color:#4f46e5}
.ix-curr-tag{font-size:12px;color:#5f6672;background:#f5f6f8;border:1px solid #e9ebef;border-radius:8px;padding:6px 10px}
.ix-catchk{display:inline-flex;gap:10px;align-items:center}
.ix-catchk label{display:inline-flex;align-items:center;gap:4px;font-size:13px;color:#111827;cursor:pointer;user-select:none}
.ix-catchk input{accent-color:#4f46e5;width:14px;height:14px;margin:0}
.ix-panelwrap{position:sticky;top:var(--header-h,70px);z-index:9;background:#fff;padding-top:10px;margin-bottom:10px}
.embedded .ix-panelwrap{top:0}
</style>"""
    markup=f"""<div class="ix-panel">
<div class="ix-panel-row ix-panel-toprow">
<div class="ix-bar-info" id="barinfo"><b>{len(banks)}</b> 家銀行 · <b>{len(_p)}</b> 期 · {_p[0]}–{_p[-1]}</div>
<div class="ix-bar-ctl">
<span class="ix-bar-sel"><label>起訖</label><select id="B_from"></select><span class="ix-bar-dash">–</span><select id="B_to"></select></span>
<span class="ix-bar-sel"><label>當期</label><select id="G_p"></select></span>
<span class="ix-bar-sel"><label>口徑</label><span class="ix-seg" id="G_basis"><button data-basis="wide" class="on">帳面/公允</button><button data-basis="wide_cost">取得成本</button></span></span>
<span class="ix-curr-tag">幣別:新台幣(億元)</span>
</div></div>
<div class="ix-panel-row">
<span class="ix-panel-lbl">顯示銀行</span>
<div id="bankchips" class="ix-chiprow"></div>
</div>
<div class="ix-panel-row">
<span class="ix-panel-lbl">計入分類</span>
<span class="ix-catchk"><label><input type="checkbox" class="G_ccb" value="Trading" checked autocomplete="off">FVTPL</label><label><input type="checkbox" class="G_ccb" value="OCI" checked autocomplete="off">FVOCI</label><label><input type="checkbox" class="G_ccb" value="AC" checked autocomplete="off">AC</label></span>
<span class="ix-seg" id="inclQuick"><button data-q="all" class="on">全選</button><button data-q="bond">只看債券</button><button data-q="bondcp">含貨幣市場</button></span>
</div>
<div class="ix-panel-row">
<span class="ix-panel-lbl">計入債種</span>
<div class="ix-chiprow">
<label class="incl-chip"><input type="checkbox" class="inclbox" value="GB" checked autocomplete="off"><span class="ix-sw" style="background:#2a78d6"></span>政府公債</label>
<label class="incl-chip"><input type="checkbox" class="inclbox" value="公司債" checked autocomplete="off"><span class="ix-sw" style="background:#1baf7a"></span>公司債</label>
<label class="incl-chip"><input type="checkbox" class="inclbox" value="金融債" checked autocomplete="off"><span class="ix-sw" style="background:#eda100"></span>金融債</label>
<label class="incl-chip"><input type="checkbox" class="inclbox" value="資產基礎" checked autocomplete="off"><span class="ix-sw" style="background:#d4318c"></span>資產基礎證券</label>
<label class="incl-chip"><input type="checkbox" class="inclbox" value="其他" checked autocomplete="off"><span class="ix-sw" style="background:#a0a6b0"></span>其他債券</label>
<label class="incl-chip" title="國庫券／可轉讓定存單／商業本票,短天期,非投資型債券"><input type="checkbox" class="inclbox" value="貨幣市場" checked autocomplete="off"><span class="ix-sw" style="background:#888780"></span>貨幣市場(短天期)</label>
<label class="incl-chip" title="FVTPL＋FVOCI 股票／受益憑證;FVOCI 股票玉山、國泰暫無"><input type="checkbox" class="inclbox" value="股票" checked autocomplete="off"><span class="ix-sw" style="background:#8b7fd6"></span>股票(權益工具,非債券)</label>
</div>
</div>
</div>
<!--IX_PANEL_SPLIT-->
<div class="ix">
<div class="card">
<div class="ix-kpihead"><h2 style="margin:0">本期速覽 <span class="ix-sub">所選期別,一眼看每家(範圍見上方全域列)</span></h2></div>
<div class="ix-sub" id="ix_basis_note" style="margin:-8px 0 14px"></div>
<div class="ix-kpi" id="ix_kpi"></div>
<div class="ix-concl" id="ix_concl"></div>
</div>

<div class="card">
<h2>跨行比較 <span class="ix-sub">同一期,誰的部位大、怎麼配(可切依債種或依會計分類)</span></h2>
<div class="ix-sub" id="A_basis_note" style="margin:-4px 0 8px"></div>
<div class="ix-ctl"><label>攤開</label><span class="ix-seg"><button id="A_by_b" class="on">依債種</button><button id="A_by_c">依會計分類</button></span><label>檢視</label><span class="ix-seg"><button id="A_amt" class="on">金額(億)</button><button id="A_pct">結構(%)</button></span></div>
<div class="ix-legend" id="A_lg"></div><div id="A_bars"></div><div id="ix_drill"></div>
<div style="font-size:12px;color:#8a919e;margin-top:6px">點銀行名展開該行明細;依債種檢視時,點圖例可聚焦單一債種。</div>
</div>

<div class="card">
<h2>時間趨勢 <span class="ix-sub">2020 以來,各家部位怎麼變(起訖區間見上方全域列,同時套用到下方「AC 隱藏損失趨勢」圖)</span></h2>
<div class="ix-ctl"><label>模式</label><span class="ix-seg"><button id="B_mcross" class="on">跨行比較</button><button id="B_msingle">單行分類</button></span><label>債種</label><select id="B_b"><option value="合計">全部債種</option><option value="GB">政府公債</option><option value="公司債">公司債</option><option value="金融債">金融債</option><option value="資產基礎">資產基礎證券</option><option value="貨幣市場">貨幣市場(短)</option><option value="股票">股票</option></select><label>檢視</label><span class="ix-seg"><button id="B_amt" class="on">金額(億)</button><button id="B_pct">佔比(%)</button></span></div>
<div class="ix-sub" id="B_pctnote" style="margin:-10px 0 8px;display:none">佔比＝該線的部位 ÷ 該行同期(勾選分類×勾選債種)合計。</div>
<div class="ix-legend" id="B_lg"></div><div style="position:relative;width:100%;height:320px"><canvas id="B_cv" role="img" aria-label="銀行債券部位時間趨勢"></canvas></div>
</div>

<div class="ix-legend" style="margin-top:2px">
<span><span class="ix-sw" style="background:#f0f0f0;border:1px solid #ccc"></span>0 = 真實零部位</span>
<span><span class="ix-sw na-pattern-sw"></span>無資料(當期財報為掃描影像檔)</span></div>
</div>"""
    js=r"""
const BANKS=RAW.banks,PERIODS=RAW.periods,REVIEW=RAW.review||{};
// 口徑可切換。**兩個口徑絕不混在同一張圖裡** —— 帳面與成本的差就是浮盈虧,
// 混著畫等於把浮盈虧當成部位變動。整頁一次只看一個口徑,切了全部重畫。
// 為什麼需要這顆鈕:多數格子的「逐桶帳面」在文件裡不存在(附註逐項印成本,
// 評價調整/備抵損失是一整筆、沒有分攤到桶),只給帳面的話大半個網格是空的。
let BASIS="wide";
let W=RAW.wide||{};
const BASIS_NOTE={wide:"帳面口徑:Trading/OCI 為公允價值、AC 為攤銷後成本(資產負債表帳面金額)。",
                  wide_cost:"取得成本口徑:逐項取得成本。帳面與成本的差額即為未實現損益。"};
const ALLBONDS=[["GB","政府公債","#2a78d6"],["公司債","公司債","#1baf7a"],["金融債","金融債","#eda100"],["資產基礎","資產基礎證券","#d4318c"],["其他","其他債券","#a0a6b0"],["貨幣市場","貨幣市場","#888780"],["股票","股票","#8b7fd6"]];
const CATS=["Trading","OCI","AC"],SC=["#2a78d6","#1baf7a","#eda100","#4a3aa7","#d4318c"];
const PAL=SC.concat(["#e34948","#eb6834","#008300","#1d9e75","#534ab7"]);
// 全站統一:企業品牌色(中信綠/兆豐金/國泰墨綠/富邦藍/玉山青),與估值視角 VC 一致
const BANKHUE={"中信":"#046A38","中信(合併)":"#046A38","兆豐":"#C9A227","國泰":"#00584A","富邦":"#0072BC","玉山":"#007A7A"};
const BC={};BANKS.forEach((b,i)=>BC[b]=BANKHUE[b]||PAL[i%PAL.length]);
function revOf(p,bk){return REVIEW[p+"|"+bk]||null;}
function revTip(info){if(!info)return"";return Object.keys(info).map(c=>{const r=info[c];return c+": "+(r.reasons||[]).join("/");}).join(" · ");}
let banksSel=new Set(BANKS);
function AB(){return BANKS.filter(b=>banksSel.has(b));}
let incl=new Set(["GB","公司債","金融債","資產基礎","其他","貨幣市場","股票"]);
function bondList(){return ALLBONDS.filter(b=>incl.has(b[0]));}
// 分類(FVTPL/FVOCI/AC)全域勾選 —— 唯一入口,KPI/跨行比較/時間趨勢一律吃這份,不准卡片各自持有一份。
let catsSel=new Set(CATS);
function syncCatsSel(){
  const boxes=[...document.querySelectorAll(".G_ccb")];
  if(!boxes.some(b=>b.checked)){const keep=boxes.find(b=>b.value===[...catsSel][0])||boxes[0];keep.checked=true;} // 不准全部取消勾選
  catsSel=new Set(boxes.filter(b=>b.checked).map(b=>b.value));
}
document.querySelectorAll(".G_ccb").forEach(cb=>cb.onchange=()=>{syncCatsSel();drawKPI();drawA();drawB();});
syncCatsSel();
// 「這期這家有沒有資料」。**空 dict 不算有** —— data.json 對還沒有資料的期別
// (如 2026H1/H2)會留一筆 {},原本 !=null 判成有資料,趨勢圖就會把線硬拉到 0,
// 看起來像部位在 2026 歸零。有資料的列一定帶得出桶,所以用 keys 長度判。
function has(p,bk){const r=W[p+"|"+bk];return r!=null&&Object.keys(r).length>0;}
// 唯一的取數入口。bond 給定時只認被勾選(incl)的那個債種——分子必須跟分母吃同一份勾選,
// 否則會算出「被排除的東西 ÷ 排除它之後的合計」這種對不起來的數字。
function sum(p,bk,{cats,bond}={}){
  const row=W[p+"|"+bk];if(!row)return 0;
  const cs=cats||CATS;
  if(bond){if(!incl.has(bond))return 0;return cs.reduce((s,c)=>s+(row[c+"_"+bond]||0),0);}
  return bondList().reduce((s,bd)=>s+cs.reduce((s2,c)=>s2+(row[c+"_"+bd[0]]||0),0),0);
}
function val(p,bk,cat,bond){return sum(p,bk,{cats:cat==="合計"?CATS:[cat],bond});}
function total(p,bk,cat){return sum(p,bk,{cats:cat==="合計"?CATS:[cat]});}
function fmt(n){return Math.round(n).toLocaleString();}
function sgn(n){return (n>=0?"+":"−")+fmt(Math.abs(n));}
function prevP(p,step){const i=PERIODS.indexOf(p);return i-step>=0?PERIODS[i-step]:null;}
// 依 PERIODS 的期別間距往前/往後推算標籤,用來在圖表兩端補「緩衝期」,超出實際資料範圍時仍能算出合理標籤。
// 自動判斷軸別:季度軸(YYYYQn,每年4期,如合併報表)或半年軸(YYYYH1/H2,每年2期,如個體)。
function periodAt(idx){
  if(idx>=0&&idx<PERIODS.length)return PERIODS[idx];
  const b=PERIODS[0],qm=b.match(/^(\d{4})Q([1-4])$/);
  if(qm){const v=(+qm[1])*4+(+qm[2]-1)+idx;return Math.floor(v/4)+"Q"+((((v%4)+4)%4)+1);}
  const y0=+b.slice(0,4),h0=(b.slice(4)==="H2"?1:0),v=y0*2+h0+idx;
  return Math.floor(v/2)+"H"+((((v%2)+2)%2)+1);
}
function fillSel(id,def){const s=document.getElementById(id);PERIODS.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;if(v===def)o.selected=true;s.appendChild(o);});}
function latestP(){for(let i=PERIODS.length-1;i>=0;i--){if(BANKS.some(b=>has(PERIODS[i],b)))return PERIODS[i];}return PERIODS[0];}
fillSel("B_from",PERIODS[0]);fillSel("B_to",PERIODS[PERIODS.length-1]);
fillSel("G_p",latestP());
function gp(){return document.getElementById("G_p").value;}
function trendIdx(){
  const f=document.getElementById("B_from"),t=document.getElementById("B_to");
  let i=PERIODS.indexOf(f.value),j=PERIODS.indexOf(t.value);
  if(i>j){const tmp=i;i=j;j=tmp;}
  return [i,j];
}
// 「當期」下拉只列出目前起訖區間內的期別;原選期別若落在區間外,改挑區間內最新(有資料優先)那期。回傳當期是否被改動。
function syncGp(){
  const sel=document.getElementById("G_p"),cur=sel.value;
  const [i0,i1]=trendIdx(),sub=PERIODS.slice(i0,i1+1);
  let nv=sub.indexOf(cur)>=0?cur:null;
  if(nv===null){for(let k=sub.length-1;k>=0;k--){if(BANKS.some(b=>has(sub[k],b))){nv=sub[k];break;}}}
  if(nv===null)nv=sub[sub.length-1];
  sel.innerHTML="";
  sub.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;if(v===nv)o.selected=true;sel.appendChild(o);});
  return nv!==cur;
}
// 頂部資訊列的「期數 · 起–迄」跟著目前起訖區間即時更新(家數維持資料集總數)
function updateBarInfo(){
  const el=document.getElementById("barinfo");if(!el)return;
  const [i0,i1]=trendIdx();
  el.innerHTML="<b>"+BANKS.length+"</b> 家銀行 · <b>"+(i1-i0+1)+"</b> 期 · "+PERIODS[i0]+"–"+PERIODS[i1];
}
syncGp();updateBarInfo();
window.ixTrendRange=function(){const [i,j]=trendIdx();return [PERIODS[i],PERIODS[j]];};
function lgHTML(items){return items.map(i=>'<span><span class="ix-sw" style="background:'+i[2]+'"></span>'+i[1]+'</span>').join("");}

let focusBond=null,drillBank=null;
const tipEl=document.createElement("div");tipEl.className="ix-tip";document.body.appendChild(tipEl);
document.addEventListener("mousemove",e=>{
  const t=e.target.closest&&e.target.closest("[data-tip]");
  if(t){tipEl.innerHTML=t.dataset.tip;tipEl.style.opacity=1;
    let x=e.clientX+14,y=e.clientY+14;const r=tipEl.getBoundingClientRect();
    if(x+r.width>innerWidth-8)x=e.clientX-r.width-10;
    if(y+r.height>innerHeight-8)y=e.clientY-r.height-10;
    tipEl.style.left=x+"px";tipEl.style.top=y+"px";
  }else tipEl.style.opacity=0;
});

function renderDrill(bk){
  drillBank=bk;const p=gp(),BD=bondList(),el=document.getElementById("ix_drill");
  if(!bk||!has(p,bk)){el.innerHTML="";drillBank=null;return;}
  const catTots=CATS.map(c=>({c,segs:BD.map(bd=>val(p,bk,c,bd[0]))}));
  const mx=Math.max(...catTots.map(o=>o.segs.reduce((a,b)=>a+b,0)),1);
  const rows=catTots.map(o=>{
    const tot=o.segs.reduce((a,b)=>a+b,0);
    const inner=BD.map((bd,i)=>{const v=o.segs[i];return v<=0?"":'<div style="width:'+(v/mx*100)+'%;background:'+bd[2]+'" data-tip="<b>'+CLABEL[o.c]+' · '+bd[1]+'</b><br>'+fmt(v)+' 億"></div>';}).join("");
    return '<div class="ix-mini"><div class="lb">'+CLABEL[o.c]+'</div><div class="tk">'+inner+'</div><div class="vv">'+fmt(tot)+'</div></div>';
  }).join("");
  const vals=PERIODS.map(pp=>has(pp,bk)?total(pp,bk,"合計"):null);
  const vmax=Math.max(...vals.filter(v=>v!=null),1),W=170,H=38;
  let d="",pen=false;
  vals.forEach((v,i)=>{if(v==null){pen=false;return;}
    const x=(i/(PERIODS.length-1)*W).toFixed(1),y=(H-4-(v/vmax)*(H-8)).toFixed(1);
    d+=(pen?"L":"M")+x+","+y;pen=true;});
  const spark='<svg width="'+W+'" height="'+H+'" style="overflow:visible;vertical-align:middle"><path d="'+d+'" fill="none" stroke="#4f46e5" stroke-width="2" stroke-linecap="round"/></svg>';
  const bp1=prevP(p,1),bp2=prevP(p,2);
  const d1=(bp1&&has(bp1,bk))?sgn(total(p,bk,"合計")-total(bp1,bk,"合計"))+" 億":"—";
  const d2=(bp2&&has(bp2,bk))?sgn(total(p,bk,"合計")-total(bp2,bk,"合計"))+" 億":"—";
  el.innerHTML='<div class="ix-drill"><div class="ix-drill-h"><b>'+bk+'</b><span>'+p+' · 三分類 × 債種</span><button class="ix-drill-x" aria-label="關閉">×</button></div>'+rows+
    '<div class="ix-drill-ft"><span>合計走勢('+PERIODS[0]+'–'+PERIODS[PERIODS.length-1]+') '+spark+'</span><span>較上期 <b style="color:#111827">'+d1+'</b></span><span>較去年同期 <b style="color:#111827">'+d2+'</b></span></div></div>';
  el.querySelector(".ix-drill-x").onclick=()=>{drillBank=null;el.innerHTML="";};
}

// KPI 卡跟跨行比較/時間趨勢用同一份全域分類範圍——三張圖才對得起來(V1)。
function scopedTotal(p,bk){return sum(p,bk,{cats:[...catsSel]});}
function drawKPI(){
  const p=gp();
  const rows=AB().filter(b=>has(p,b)).map(b=>({b,t:scopedTotal(p,b)}));
  if(!rows.length){   // 所選銀行本期皆無資料 → 免 reduce 空陣列爆錯
    document.getElementById("ix_kpi").innerHTML='<div class="ix-kcard"><div class="ix-klabel">部位最大('+p+')</div><div class="ix-kval">—</div><div class="ix-ksub">所選銀行本期無資料</div></div>';
    document.getElementById("ix_concl").innerHTML="";return;}
  const sum2=rows.reduce((s,r)=>s+r.t,0),top=rows.reduce((a,b)=>b.t>a.t?b:a);
  const yp=prevP(p,2);
  const dts=yp?AB().filter(b=>has(p,b)&&has(yp,b)).map(b=>({b,d:scopedTotal(p,b)-scopedTotal(yp,b)})):[];
  const up=dts.length?dts.reduce((a,b)=>b.d>a.d?b:a):null,dn=dts.length?dts.reduce((a,b)=>b.d<a.d?b:a):null;
  const SHORT={GB:"公債","公司債":"公司債","金融債":"金融債","資產基礎":"資產基礎","其他":"其他","貨幣市場":"貨幣","股票":"股票"};
  const scope=ALLBONDS.filter(b=>incl.has(b[0])).map(b=>SHORT[b[0]]).join("+")||"(未選)";
  const cards=[["部位最大("+p+")",top.b,fmt(top.t)+" 億 · "+scope]];
  if(up)cards.push(["加碼最多(YoY)",up.b,sgn(up.d)+" 億"]);
  if(dn)cards.push(["減碼最多(YoY)",dn.b,sgn(dn.d)+" 億"]);
  document.getElementById("ix_kpi").innerHTML=cards.map(c=>'<div class="ix-kcard"><div class="ix-klabel">'+c[0]+'</div><div class="ix-kval">'+c[1]+'</div><div class="ix-ksub">'+c[2]+'</div></div>').join("");
  drawConcl(p);
}
function drawConcl(p){
  const el=document.getElementById("ix_concl");if(!el)return;
  const rows=AB().filter(b=>has(p,b));
  if(rows.length<2){el.innerHTML="";return;}
  const share=(bk,c)=>{const t=total(p,bk,"合計");return t?total(p,bk,c)/t:0;};
  const top=c=>rows.reduce((a,b)=>share(b,c)>share(a,c)?b:a);
  const pc=x=>Math.round(x*100)+"%";
  const items=[
    ["#eb6834","交易目的最重",top("Trading"),c=>"FVTPL 佔 "+pc(share(c,"Trading"))+" · 帳面波動風險吃得比同業重"],
    ["#2a78d6","利率最敏感",top("OCI"),c=>"FVOCI 佔 "+pc(share(c,"OCI"))+" · 利率一動,淨值(OCI)受衝擊最大"],
    ["#4a3aa7","帳面最穩",top("AC"),c=>"AC 佔 "+pc(share(c,"AC"))+" · 未實現損益不入帳、流動性較低"],
  ];
  el.innerHTML='<div class="ix-cl-h">本期同業離群點名 <span>'+p+' · 佔該行債券部位,點出偏離同業的姿態</span></div>'+
    '<div class="ix-cl-grid">'+items.map(it=>'<div class="ix-cl"><span class="ix-cl-dot" style="background:'+it[0]+'"></span><div><div class="ix-cl-tag">'+it[1]+'</div><div class="ix-cl-bk">'+it[2]+'</div><div class="ix-cl-note">'+it[3](it[2])+'</div></div></div>').join("")+'</div>';
}
// 全域取消勾某債種後,B_b 下拉不准還選得到它——UI 上不能留一條路繞過 incl。
function syncBbOptions(){
  const sel=document.getElementById("B_b");if(!sel)return;
  [...sel.options].forEach(o=>{if(o.value!=="合計")o.disabled=!incl.has(o.value);});
  if(sel.selectedOptions[0]&&sel.selectedOptions[0].disabled)sel.value="合計";
}
function syncIncl(){incl=new Set([...document.querySelectorAll(".inclbox:checked")].map(x=>x.value));syncBbOptions();}
document.querySelectorAll(".inclbox").forEach(cb=>cb.onchange=()=>{syncIncl();drawKPI();drawA();drawB();});
syncIncl();
const INCL_QUICK={
  bond:["GB","公司債","金融債","資產基礎","其他"],
  bondcp:["GB","公司債","金融債","資產基礎","其他","貨幣市場"],
  all:["GB","公司債","金融債","資產基礎","其他","貨幣市場","股票"],
};
function setIncl(list){
  document.querySelectorAll(".inclbox").forEach(cb=>{cb.checked=list.includes(cb.value);});
  syncIncl();drawKPI();drawA();drawB();
}
const inclQuickEl=document.getElementById("inclQuick");
if(inclQuickEl)inclQuickEl.addEventListener("click",e=>{
  const b=e.target.closest("button");if(!b)return;
  [...inclQuickEl.children].forEach(x=>x.classList.remove("on"));b.classList.add("on");
  setIncl(INCL_QUICK[b.dataset.q]||[]);
});

let A_mode="amt",A_by="bond";
const CLS=[["Trading","FVTPL","#eb6834"],["OCI","FVOCI","#2a78d6"],["AC","AC","#4a3aa7"]];
const CLABEL={Trading:"FVTPL",OCI:"FVOCI",AC:"AC"};
// 依底色亮度選字色:亮底用深字、暗底用白字(段內數字才讀得清)
function txtOn(hex){const h=hex.replace("#","");const r=parseInt(h.substr(0,2),16),g=parseInt(h.substr(2,2),16),b=parseInt(h.substr(4,2),16);
  return (0.299*r+0.587*g+0.114*b)>150?"#3a2a00":"#fff";}
function drawA(){
  const p=gp(),bp=prevP(p,1),byCls=A_by==="cls";
  const catsA=[...catsSel];
  const SEGS=byCls?CLS.filter(c=>catsSel.has(c[0])):bondList();
  // 攤開軸只剩一格時,結構% 沒有意義(恆為 100%)——鈕灰掉並附一句解釋,不准讓人按了看到沒意義的圖(R2 裁示)。
  const trivial=byCls?SEGS.length<=1:catsA.length<=1;
  A_pct.disabled=trivial;A_pct.title=trivial?"目前範圍只有一個分類,結構圖恆為 100%":"";
  if(trivial&&A_mode==="pct"){A_mode="amt";A_amt.classList.add("on");A_pct.classList.remove("on");}
  const segVal=(bk,seg,per)=>byCls?bondList().reduce((s,bd)=>s+val(per,bk,seg[0],bd[0]),0):catsA.reduce((s,c)=>s+val(per,bk,c,seg[0]),0);
  const catNote=(!byCls&&catsA.length<CATS.length)?' <span style="color:#999">('+catsA.map(c=>CLABEL[c]).join("+")+' 合計)</span>':'';
  document.getElementById("A_lg").innerHTML=SEGS.map(seg=>{
    const cls=(!byCls&&focusBond)?(focusBond===seg[0]?' sel':' dim'):'';
    return '<span class="lg-item'+cls+'" data-seg="'+seg[0]+'"><span class="ix-sw" style="background:'+seg[2]+'"></span>'+seg[1]+'</span>';}).join("")+catNote;
  if(!byCls)document.querySelectorAll("#A_lg .lg-item").forEach(li=>li.onclick=()=>{focusBond=(focusBond===li.dataset.seg)?null:li.dataset.seg;drawA();});
  const rows=AB().map(bk=>({bk,ok:has(p,bk),tot:SEGS.reduce((s,seg)=>s+segVal(bk,seg,p),0)}));
  const mx=Math.max(...rows.map(r=>r.tot),1);
  document.getElementById("A_bars").innerHTML=rows.map(r=>{
    if(!r.ok)return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div class="ix-na na-pattern-cell">無資料 · 該期財報為掃描影像檔</div><div class="ix-tot">N/A</div></div>';
    const base=A_mode==="pct"?(r.tot||1):mx,wp=A_mode==="pct"?100:(r.tot/mx*100);
    const inner=SEGS.map(seg=>{const v=segVal(r.bk,seg,p);if(v<=0)return"";
      const pct=r.tot?Math.round(v/r.tot*100):0;
      const pv=(bp&&has(bp,r.bk))?segVal(r.bk,seg,bp):null;
      const dtxt=pv==null?"—":sgn(v-pv)+" 億";
      const tip="<b>"+r.bk+" · "+seg[1]+"</b><br>"+fmt(v)+" 億 · 佔該行 "+pct+"%<br>較上期 "+dtxt;
      const dim=(!byCls&&focusBond&&focusBond!==seg[0])?" dim":"";
      const wp2=v/base*100;                                   // 段寬(占軌道 %)
      const lab=A_mode==="pct"?pct+"%":fmt(Math.round(v));
      const sl=wp2>=8?'<span class="s2l" style="color:'+txtOn(seg[2])+'">'+lab+'</span>':'';
      return '<div class="ix-s2'+dim+'" style="width:'+wp2+'%;background:'+seg[2]+'" data-tip="'+tip.replace(/"/g,"&quot;")+'">'+sl+'</div>';}).join("");
    const lab=A_mode==="pct"?(r.tot?"100%":"0"):(fmt(r.tot)+" 億");
    return '<div class="ix-row"><div class="ix-name click" data-bank="'+r.bk+'">'+r.bk+'</div><div class="ix-track" style="width:'+Math.max(wp,0.5)+'%">'+inner+'</div><div class="ix-tot">'+lab+'</div></div>';
  }).join("");
  document.querySelectorAll("#A_bars .ix-name.click").forEach(n=>n.onclick=()=>renderDrill(drillBank===n.dataset.bank?null:n.dataset.bank));
  if(drillBank)renderDrill(drillBank);
}
document.getElementById("G_p").addEventListener("change",()=>{drawKPI();drawA();drawB();renderBankChips();});
A_amt.onclick=()=>{A_mode="amt";A_amt.classList.add("on");A_pct.classList.remove("on");drawA();};
A_pct.onclick=()=>{A_mode="pct";A_pct.classList.add("on");A_amt.classList.remove("on");drawA();};
A_by_b.onclick=()=>{A_by="bond";A_by_b.classList.add("on");A_by_c.classList.remove("on");drawA();};
A_by_c.onclick=()=>{A_by="cls";A_by_c.classList.add("on");A_by_b.classList.remove("on");drawA();};


let chartB=null;
let trendFocus=null;   // 點圖例聚焦單一銀行(只強調/淡化,不隱藏、不動數字——R4 裁示 #3)
const TREND_BUF=4; // 圖表兩端各補幾期空白當緩衝(4期≈2年),避免線貼齊圖邊;不影響上方「起訖」實際選取範圍
let B_viewMode="cross",B_selBank=BANKS[0]; // 趨勢圖模式:cross=跨行比較,single=單行分類
let B_mode="amt"; // 檢視:amt=億元,pct=佔該行同期(勾選分類×勾選債種)合計的%
// 分母跟分子吃同一份全域範圍(勾選分類×勾選債種)——單行分類/跨行比較兩種模式的 % 因此自動是同一把尺,
// 不必再另外寫死「固定三分類」那種特例(R2:分類升上全域後,「同一把尺」不必再靠分母寫死達成)。
function B_denom(p,bk){const t=sum(p,bk,{cats:[...catsSel]});return t||null;}
function B_conv(v,p,bk){
  if(B_mode!=="pct")return v;
  const d=B_denom(p,bk);return d===null?null:v/d*100;
}
function B_fmt(v){return B_mode==="pct"?(v==null?"—":v.toFixed(1)+"%"):fmt(v)+" 億";}
function drawB(){
  const [i0,i1]=trendIdx();
  const P2=[];for(let k=i0-TREND_BUF;k<=i1+TREND_BUF;k++)P2.push(periodAt(k));
  updateBarInfo();
  const cp=gp(),cpIdx=P2.indexOf(cp);
  const bond=B_b.value;
  const pnote=document.getElementById("B_pctnote");if(pnote)pnote.style.display=B_mode==="pct"?"":"none";
  // 分子分母同一份範圍時,佔比在「全部債種」恆為 100%,沒有意義——鈕灰掉(R2 裁示)。
  const trivial=catsSel.size<=1;
  B_pct.disabled=trivial;B_pct.title=trivial?"目前範圍只有一個分類,佔比恆為 100%":"";
  if(trivial&&B_mode==="pct"){B_mode="amt";B_amt.classList.add("on");B_pct.classList.remove("on");}
  let ds,lgHtml;
  if(B_viewMode==="single"){
    const bk=B_selBank;
    const CC={Trading:["#eb6834",[]],OCI:["#2a78d6",[6,4]],AC:["#4a3aa7",[2,3]]};
    const vOf=(p,c)=>bond==="合計"?total(p,bk,c):val(p,bk,c,bond);
    const catsB=CATS.filter(c=>catsSel.has(c));
    ds=catsB.map(c=>({label:CLABEL[c],data:P2.map(p=>has(p,bk)?B_conv(vOf(p,c),p,bk):null),
      borderColor:CC[c][0],backgroundColor:CC[c][0],borderDash:CC[c][1],
      spanGaps:false,borderWidth:2,tension:0.25,
      pointRadius:P2.map(p=>p===cp?5:2),pointHoverRadius:6}));
    lgHtml='<span style="color:#8a919e;font-size:12px;margin-right:6px">選擇銀行</span>'+
      AB().map(b=>'<span class="lg-item'+(b===bk?' sel':'')+'" data-bank="'+b+'"><span class="ix-sw" style="background:'+BC[b]+'"></span>'+b+'</span>').join("")+
      '<span style="margin-left:18px;display:inline-flex;gap:14px;align-items:center">'+
      catsB.map(c=>'<span><span class="ix-sw" style="background:'+CC[c][0]+'"></span>'+CLABEL[c]+'</span>').join("")+'</span>';
  } else {
    const dash=[[],[6,4],[2,3],[8,3,2,3],[]];
    const withCP=incl.has("貨幣市場")&&(bond==="合計");
    const cats=[...catsSel];
    const vOf=(p,bk)=>cats.reduce((s,c)=>s+(bond==="合計"?total(p,bk,c):val(p,bk,c,bond)),0);
    const dimHex=hex=>hex+"33";
    ds=AB().map((bk)=>{const i=BANKS.indexOf(bk);const foc=!trendFocus||trendFocus===bk;const col=foc?BC[bk]:dimHex(BC[bk]);
      return {label:bk,data:P2.map(p=>has(p,bk)?B_conv(vOf(p,bk),p,bk):null),borderColor:col,backgroundColor:col,borderDash:dash[i%dash.length],spanGaps:false,borderWidth:foc?2:1.5,tension:0.25,pointRadius:P2.map(p=>p===cp?5:2),pointHoverRadius:6,order:foc?0:1};});
    const catNote=cats.length<CATS.length?' <span style="color:#999">('+cats.map(c=>CLABEL[c]).join("+")+' 合計)</span>':'';
    lgHtml=AB().map((bk)=>'<span class="lg-item'+(trendFocus===bk?' sel':(trendFocus?' dim':''))+'" data-bank="'+bk+'"><span class="ix-sw" style="background:'+BC[bk]+'"></span>'+bk+'</span>').join("")+(withCP?' <span style="color:#999">(已含貨幣市場)</span>':'')+catNote;
  }
  document.getElementById("B_lg").innerHTML=lgHtml;
  document.querySelectorAll("#B_lg .lg-item").forEach(li=>li.onclick=()=>{
    if(B_viewMode==="single"){B_selBank=li.dataset.bank;}
    else{const bk=li.dataset.bank;trendFocus=(trendFocus===bk)?null:bk;}
    drawB();
  });
  if(chartB)chartB.destroy();
  chartB=new Chart(document.getElementById("B_cv"),{type:"line",data:{labels:P2,datasets:ds},
    plugins:[{id:"curMark",afterDatasetsDraw(c){
      if(cpIdx<0)return;const x=c.scales.x.getPixelForTick(cpIdx),a=c.chartArea,g=c.ctx;
      g.save();
      g.strokeStyle="#111827";g.lineWidth=1.5;g.setLineDash([4,3]);
      g.beginPath();g.moveTo(x,a.top);g.lineTo(x,a.bottom);g.stroke();g.setLineDash([]);
      const t="當期 "+cp;g.font="600 11px -apple-system,system-ui,sans-serif";
      const w=g.measureText(t).width+10;let bx=x-w/2;bx=Math.max(a.left,Math.min(bx,a.right-w));
      g.fillStyle="#111827";g.beginPath();(g.roundRect?g.roundRect(bx,a.top-19,w,15,4):g.rect(bx,a.top-19,w,15));g.fill();
      g.fillStyle="#fff";g.textAlign="center";g.textBaseline="middle";g.fillText(t,bx+w/2,a.top-11);
      g.restore();
    }}],
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:22}},interaction:{mode:"index",intersect:false},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.dataset.label+": "+B_fmt(c.parsed.y)}}},
      scales:{y:{title:{display:true,text:B_mode==="pct"?"佔該行債券部位 %":"億元"},
                 ...(B_mode==="pct"?{min:0,suggestedMax:100,ticks:{callback:v=>v+"%"}}:{})},
              x:{grid:{display:false},ticks:{maxRotation:45,autoSkip:false}}}}});
}
B_amt.onclick=()=>{B_mode="amt";B_amt.classList.add("on");B_pct.classList.remove("on");drawB();};
B_pct.onclick=()=>{B_mode="pct";B_pct.classList.add("on");B_amt.classList.remove("on");drawB();};
B_mcross.onclick=()=>{B_viewMode="cross";B_mcross.classList.add("on");B_msingle.classList.remove("on");drawB();};
B_msingle.onclick=()=>{B_viewMode="single";B_msingle.classList.add("on");B_mcross.classList.remove("on");drawB();};
document.getElementById("B_b").onchange=drawB;
["B_from","B_to"].forEach(id=>document.getElementById(id).addEventListener("change",()=>{syncGp();drawKPI();drawA();drawB();renderBankChips();document.dispatchEvent(new CustomEvent("ix-trendrange"));}));

// 銀行小卡的「期數」與灰/彩色小方塊,只算目前起訖區間內的期別(隨上方工具列即時更新)
function renderBankChips(){
  const bcEl=document.getElementById("bankchips");if(!bcEl)return;
  const [i0,i1]=trendIdx(),subP=PERIODS.slice(i0,i1+1);
  const cur=gp();
  bcEl.innerHTML=BANKS.map(b=>{
    const filled=subP.map(p=>has(p,b));
    const cnt=filled.filter(Boolean).length;
    const pr=subP.filter((p,i)=>filled[i]);
    const range=pr.length?pr[0]+"–"+pr[pr.length-1]:"無資料";
    const ticks=filled.map(f=>'<span class="tk" style="background:'+(f?BC[b]:"#e3e5e9")+'"></span>').join("");
    const on=banksSel.has(b)?" on":"";
    const rv=revOf(cur,b);
    const badge=rv?'<span class="rev-badge" title="'+revTip(rv).replace(/"/g,"&quot;")+'">待複核</span>':"";
    return '<button class="ov-chip'+on+'" data-bank="'+b+'" title="'+b+':'+cnt+' 期 · '+range+(rv?' · '+revTip(rv):'')+'"><span class="top"><span class="ix-sw" style="background:'+BC[b]+'"></span>'+b+badge+'<span class="cnt">'+cnt+' 期</span></span><span class="ticks">'+ticks+'</span></button>';
  }).join("");
  bcEl.querySelectorAll(".ov-chip").forEach(ch=>ch.onclick=()=>{const b=ch.dataset.bank;
    if(banksSel.has(b)){if(banksSel.size<=1)return;banksSel.delete(b);ch.classList.remove("on");}
    else{banksSel.add(b);ch.classList.add("on");}
    if(drillBank&&!banksSel.has(drillBank)){drillBank=null;document.getElementById("ix_drill").innerHTML="";}
    drawKPI();drawA();drawB();});
}
renderBankChips();
(function(){
  const seg=document.getElementById("G_basis"),note=document.getElementById("ix_basis_note");
  if(!seg)return;
  const hasData=k=>{const t=RAW[k]||{};
    return Object.keys(t).some(c=>t[c]&&Object.keys(t[c]).some(m=>t[c][m]!=null));};
  // 該口徑一格資料都沒有時,把鈕停用而不是讓人按了看到空白 ——
  // 「按了沒反應」跟「這個口徑沒有資料」在畫面上分不出來。
  [].forEach.call(seg.children,function(b){
    if(!hasData(b.getAttribute("data-basis"))){
      b.disabled=true;b.title="這個口徑目前沒有任何資料";b.style.opacity=.4;}
  });
  // 預設挑**有資料**的口徑,不是永遠挑帳面。合併報表就是個例子:中信的合併附註
  // 逐項印成本,逐桶帳面在文件裡不存在,寫死帳面會讓那個分頁一開啟就是空的。
  if(!hasData(BASIS)){
    const alt=[].find.call(seg.children,b=>!b.disabled);
    if(alt){BASIS=alt.getAttribute("data-basis");W=RAW[BASIS]||{};
            [].forEach.call(seg.children,x=>x.classList.remove("on"));alt.classList.add("on");}
  }
  note.textContent=BASIS_NOTE[BASIS];
  // 下面「跨行比較」「時間趨勢」兩張圖讀的就是這個 W(同一個 BASIS),口徑說明
  // 因此要跟著同一個變數講,不能另外寫死一句 —— 合併報表沒有帳面資料時 BASIS
  // 會被上面的邏輯自動切成成本,寫死「本頁圖表均為帳面口徑」會變成假話(見
  // 2026-08-12 線上實測:合併分頁「跨行比較」畫的是成本卻標著帳面口徑)。
  const anote=document.getElementById("A_basis_note");
  if(anote)anote.textContent="本頁圖表口徑:"+BASIS_NOTE[BASIS]+
    (hasData("wide")&&hasData("wide_cost")?" 取得成本見上方「取得成本」切換鈕。":"");
  seg.addEventListener("click",function(e){
    const b=e.target.closest("button");if(!b||b.disabled)return;
    [].forEach.call(seg.children,x=>x.classList.remove("on"));b.classList.add("on");
    BASIS=b.getAttribute("data-basis");W=RAW[BASIS]||{};
    note.textContent=BASIS_NOTE[BASIS];
    if(anote)anote.textContent="本頁圖表口徑:"+BASIS_NOTE[BASIS]+
      (hasData("wide")&&hasData("wide_cost")?" 取得成本見上方「取得成本」切換鈕。":"");
    drillBank=null;const dr=document.getElementById("ix_drill");if(dr)dr.innerHTML="";
    drawKPI();drawA();drawB();
  });
})();
%%AUTORUN%%
"""
    js = js.replace("%%AUTORUN%%", "drawKPI();drawA();drawB();" if autorun else
                     "window.__lazyInitsP3=window.__lazyInitsP3||[];"
                     "window.__lazyInitsP3.push(function(){drawKPI();drawA();drawB();});")
    if not expose_trend_range:
        # 合併報表分頁自己的期間不投影到「估值視角」的全域起訖(那頁只看個體資料)
        js = js.replace(
            'window.ixTrendRange=function(){const [i,j]=trendIdx();return [PERIODS[i],PERIODS[j]];};', '')
    if prefix:
        # 同一元件在頁面上出現第二次(如「合併報表」分頁):id 全部加前綴,避免跟預設頁撞名
        for _id in sorted(_IX_IDS, key=len, reverse=True):
            markup = re.sub(r'\b' + _id + r'\b', prefix + _id, markup)
            js = re.sub(r'\b' + _id + r'\b', prefix + _id, js)
    script = '<script>(function(){\nconst RAW=' + payload + ';\n' + js + '\n})();</script>'
    if include_chartjs:
        script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>' + script
    # 全域列(期間/銀行/口徑/分類/債種)跟卡片本體分開回傳:全域列要浮到獨立的
    # sticky wrapper 裡,不再是 page1 的內部元件。
    panel_markup, body_markup = markup.split("<!--IX_PANEL_SPLIT-->", 1)
    # id 直接放在 sticky 元件本身,不要再包一層——包一層等於給它一個「剛好貼身」的父容器,
    # sticky 可移動的空間被壓成 0,滾動時完全黏不住(這是 R1 曾經踩到的真坑,不是理論疑慮)。
    panel_id = "panel_consol" if prefix else "panel_indiv"
    panel_hidden = " hidden" if prefix else ""
    return (css + f'<div class="ix-panelwrap" id="{panel_id}"{panel_hidden}>' + panel_markup + '</div>',
            body_markup + script)


# interactive_html() 內用到的元素 id,重複呼叫(第二個分頁)時要加前綴避免跟第一份撞名
_IX_IDS = ["A_by_b", "A_by_c", "A_amt", "A_pct", "A_lg", "A_bars",
           "A_basis_note", "G_ccb", "G_basis",
           "ix_drill", "ix_kpi", "ix_concl", "ix_basis_note",
           "bankchips", "inclQuick",
           "B_from", "B_to", "B_b", "B_lg", "B_cv", "B_mcross", "B_msingle",
           "B_amt", "B_pct", "B_pctnote",
           "G_p", "barinfo", "inclbox"]

now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
_panel1, _body1 = interactive_html()
_panel3, _body3 = interactive_html(prefix="c_", banks=BANKS_CONSOL, wide=WIDE_CONSOL, wide_cost=WIDE_COST_CONSOL,
                                    periods=PERIODS_CONSOL, review=REVIEW_CONSOL, expose_trend_range=False,
                                    include_chartjs=False, autorun=False) if HAS_CONSOL else ("", "")
html=f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>銀行債券投資 債種分析</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
{TOKENS_CSS}</style></head><body>
<script>
// 被工作台用 iframe 嵌著時,把自己的標頭降級成「頁內分頁」——
// 外層已經有一條全站導覽列(web/appnav.js),再擺一條同樣重的標頭就是兩層疊著,
// 那是 2026-08-10 之前「四個頁面像四個網站」的最後一塊。
// 站名與更新時間由外層負責,這裡只留真正屬於本頁的分頁(個體/合併)。
// **單獨開啟(GitHub Pages)時什麼都不做** —— 那時這條標頭是它唯一的標頭。
if (window.self !== window.top) document.documentElement.classList.add("embedded");
</script>
<style>
.embedded header{{position:static;border-bottom:0;padding:16px 20px 0;background:transparent}}
.embedded header h1,.embedded header .upd{{display:none}}.embedded .wrap{{padding-top:14px}}
</style>
<header><h1>銀行債券投資債種分析</h1>
<span class="ix-seg" id="pagetabs"><button id="tab1" class="on">個體報表</button>{'<button id="tab3">合併報表</button>' if HAS_CONSOL else ''}</span>
<span class="upd">更新 {now}</span></header>
<div class="wrap">
{_panel1}
{_panel3 if HAS_CONSOL else ''}
<div id="page1">
{_body1}
</div>
{f'<div id="page3" hidden>{_body3}</div>' if HAS_CONSOL else ''}
<details class="foot"><summary>資料說明與口徑</summary>
<div class="foot-in">
· 單位:新台幣億元。資料期間 {(_have or PERIODS)[0]}–{(_have or PERIODS)[-1]},每半年一期(H1=6/30、H2=12/31 期末餘額)。<br>
· 會計分類(IFRS 9):<b>FVTPL</b> 透過損益按公允價值衡量(即交易目的,附註六(三))、<b>FVOCI</b> 透過其他綜合損益(六(四))、<b>AC</b> 按攤銷後成本(六(五))。<br>
· <b>兆豐</b>債種明細來自其財報「證券部門變動明細表」;其證券部門無 FVTPL 部位,故 FVTPL 為 0。<br>
· 2020H1 國泰/玉山之個體財報為掃描影像檔,無法解析,標為「無資料」。<br>
· 個體(AI3)與合併(AI1)分開頁面顯示,不互相混算。<br>
· <b>待複核</b>角標:該期該行有弱錨/錨可疑(掃描圖 BS)/面板離群等旗標——數字已採信但建議人工抽查。<br>
· 數據經對帳(明細合計↔BS)+面板跨期驗證;本頁由 GitHub Actions 自動更新。
</div></details>
</div>
<script>(function(){{
  var p1=document.getElementById('page1'),p3=document.getElementById('page3');
  var t1=document.getElementById('tab1'),t3=document.getElementById('tab3');
  var panelIndiv=document.getElementById('panel_indiv'),panelConsol=document.getElementById('panel_consol');
  var initedP3=false;
  function show(which){{
    p1.hidden=(which!=='p1');if(p3)p3.hidden=(which!=='p3');
    // 全域列跟著分頁走,個體(page1)一份、合併(page3)另一份——
    // 期別軸不同(半年 vs 季度),混用會把季度選單套到半年資料上。
    if(panelIndiv)panelIndiv.hidden=(which==='p3');
    if(panelConsol)panelConsol.hidden=(which!=='p3');
    t1.classList.toggle('on',which==='p1');
    if(t3)t3.classList.toggle('on',which==='p3');
    history.replaceState(null,'',which==='p1'?(location.pathname+location.search):('#'+which));
    if(which==='p3'&&!initedP3){{initedP3=true;(window.__lazyInitsP3||[]).forEach(function(fn){{fn();}});}}
    window.scrollTo(0,0);
  }}
  t1.onclick=function(){{show('p1');}};
  if(t3)t3.onclick=function(){{show('p3');}};
  var start=(location.hash==='#p3'&&p3)?'p3':'p1';
  show(start);
  // 全域列黏頂的偏移量要量標頭實際高度,不能寫死——窄螢幕標頭會換行變高,
  // 寫死的話全域列會鑽到標頭底下(embedded 模式標頭改成 static,偏移量交給 CSS 的 .embedded 覆寫,這裡不用管)。
  var headerEl=document.querySelector('header');
  function syncHeaderH(){{if(!document.documentElement.classList.contains('embedded'))
    document.documentElement.style.setProperty('--header-h',headerEl.offsetHeight+'px');}}
  syncHeaderH();
  window.addEventListener('resize',syncHeaderH);
}})();</script>
</body></html>"""
# 單一設定源:把內嵌 JS 的品牌色改由 config.BANK_COLORS 注入(值不變,但改色只需動 config.py)
html = re.sub(r"const BANKHUE=\{[^;]*\};", _BANKHUE_JS, html)
(SITE/"index.html").write_text(html, encoding="utf-8")
print("已產生 site/ (index.html + 圖1.png + 圖2.png)")
