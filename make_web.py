"""產生給 GitHub Pages 的網頁:site/index.html(兩張儀表板圖 + Excel 下載)。
讀 data.json;圖用 matplotlib(伺服器/CI 需裝 CJK 字型,如 fonts-noto-cjk)。
"""
import json, shutil, datetime
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

SITE=Path("site"); SITE.mkdir(exist_ok=True)
D=json.load(open("data.json")); PERIODS=D["periods"]; BANKS=D["banks"]; DATA=D["data"]
try: P0=json.load(open("phase0.json"))
except FileNotFoundError: P0={"periods":PERIODS,"banks":BANKS,"data":{}}
COLOR={"中信":"#4a5e2a","兆豐":"#8a8a3a","國泰":"#e8c020","富邦":"#3a8fd0","玉山":"#8bc34a"}
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
def tot(r): return sum(mv(r[c]) for c in ("Trading","OCI","AC"))

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
tmv=lambda k:(lambda r:sum(r[c][k] for c in ("Trading","OCI","AC")))
credit=lambda r:sum(r[c]["公司債"]+r[c]["金融債"] for c in ("Trading","OCI","AC"))
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

# ---- 寬表 HTML(那張 spreadsheet)----
def wide_table_html():
    metrics=D.get("wide_metrics",[]); wide=D.get("wide",{})
    if not metrics: return ""
    th_p="".join(f'<th colspan="{len(BANKS)}">{p}</th>' for p in PERIODS)
    th_b="<th>指標＼期間</th>"+"".join(f"<th>{b}</th>" for _ in PERIODS for b in BANKS)
    rows=""
    for m in metrics:
        tds=""
        for p in PERIODS:
            for b in BANKS:
                v=(wide.get(f"{p}|{b}") or {}).get(m)
                tds+=f"<td>{'' if v is None else format(v,',')}</td>"
        rows+=f"<tr><th class='rowh'>{m}</th>{tds}</tr>"
    return f"""<div class="card"><h2>數字明細(億元)</h2>
    <div class="tblwrap"><table class="wide">
    <thead><tr><th></th>{th_p}</tr><tr>{th_b}</tr></thead><tbody>{rows}</tbody></table></div></div>"""

# ---- 互動儀表板(A跨行比較 / B時間趨勢 / D增減 / C探索 + KPI + 含CP開關)----
def interactive_html():
    payload=json.dumps({"periods":_have or PERIODS,"banks":BANKS,"wide":D.get("wide",{})}, ensure_ascii=False)
    css="""<style>
.ix{font-family:inherit}
.ix-sub{font-weight:400;color:#8a919e;font-size:12px;margin-left:8px}
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
.ix-seg{display:inline-flex;background:#eef0f3;border-radius:8px;padding:2px}
.ix-seg button{border:none;background:transparent;font-size:12px;padding:6px 12px;cursor:pointer;color:#5f6672;border-radius:6px}
.ix-seg button.on{background:#fff;color:#111827;font-weight:600;box-shadow:0 1px 2px rgba(16,24,40,.08)}
.ix-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.ix-kcard{background:#fff;border:1px solid #e9ebef;border-radius:12px;padding:14px 16px}
.ix-klabel{font-size:12px;color:#8a919e;margin-bottom:8px}
.ix-kval{font-size:24px;font-weight:600;color:#111827;line-height:1.15;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.ix-ksub{font-size:12px;color:#8a919e;margin-top:4px}
.ix-legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px;font-size:12px;color:#5f6672;align-items:center}
.ix-legend span{display:flex;align-items:center;gap:5px}
.ix-sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.ix-hatch{background:repeating-linear-gradient(45deg,#f2f3f5,#f2f3f5 3px,#c4c9d1 3px,#c4c9d1 4px)}
.ix-row{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.ix-name{width:38px;font-size:13px;color:#111827;text-align:right;flex:none}
.ix-track{flex:1;display:flex;height:26px;border-radius:6px;overflow:hidden;background:#f2f3f5}
.ix-s2{height:100%}
.ix-tot{width:64px;font-size:12px;color:#5f6672;text-align:right;flex:none;font-variant-numeric:tabular-nums}
.ix-na{flex:1;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#8a919e;background:repeating-linear-gradient(45deg,#f5f6f8,#f5f6f8 5px,rgba(150,156,168,.25) 5px,rgba(150,156,168,.25) 7px)}
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
.ix-bar{position:sticky;top:57px;z-index:9;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:rgba(245,246,248,.92);backdrop-filter:blur(6px);padding:10px 2px;margin:-8px 0 14px}
.ix-bar-info{font-size:12px;color:#8a919e}
.ix-bar-info b{color:#111827;font-weight:600}
.ix-bar-ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ix-bar-sel{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#5f6672}
.ix-bar-sel select{height:36px;border:1px solid #e0e3e8;border-radius:9px;padding:0 10px;background:#fff;color:#111827;font-size:13px;font-weight:600;outline:none;cursor:pointer}
.ix-bar-sel select:hover{border-color:#c6cbd4}
</style>"""
    _p=_have or PERIODS
    markup=f"""<div class="ix">
<div class="ix-bar">
<div class="ix-bar-info"><b>{len(BANKS)}</b> 家銀行 · <b>{len(_p)}</b> 期 · {_p[0]}–{_p[-1]}</div>
<div class="ix-bar-ctl">
<span class="ix-bar-sel"><label>期間</label><select id="G_p"></select></span>
<details class="ix-cfg"><summary><span class="ix-cfg-ic">🏦</span>顯示銀行<span class="ix-cfg-ar">▾</span></summary>
<div class="ix-cfg-panel" style="min-width:340px">
<div class="ix-cfg-h">點選要顯示的銀行(全頁連動:比較 / 趨勢 / 速覽)</div>
<div id="bankchips"></div></div></details>
<details class="ix-cfg"><summary><span class="ix-cfg-ic">⚙</span>計入項目<span class="ix-cfg-ar">▾</span></summary>
<div class="ix-cfg-panel">
<div class="ix-cfg-h">計入「部位」的項目(全頁與 KPI 連動)</div>
<label><input type="checkbox" class="inclbox" value="GB" checked autocomplete="off"><span class="ix-sw" style="background:#2a78d6"></span>政府公債</label>
<label><input type="checkbox" class="inclbox" value="公司債" checked autocomplete="off"><span class="ix-sw" style="background:#1baf7a"></span>公司債</label>
<label><input type="checkbox" class="inclbox" value="金融債" checked autocomplete="off"><span class="ix-sw" style="background:#eda100"></span>金融債</label>
<label><input type="checkbox" class="inclbox" value="資產基礎" checked autocomplete="off"><span class="ix-sw" style="background:#d4318c"></span>資產基礎證券</label>
<label><input type="checkbox" class="inclbox" value="其他" checked autocomplete="off"><span class="ix-sw" style="background:#a0a6b0"></span>其他債券</label>
<label><input type="checkbox" class="inclbox" value="貨幣市場" autocomplete="off"><span class="ix-sw" style="background:#888780"></span>貨幣市場（短天期）<span class="ix-cfg-note">國庫券／可轉讓定存單／商業本票,短天期,非投資型債券</span></label>
<label><input type="checkbox" class="inclbox" value="股票" autocomplete="off"><span class="ix-sw" style="background:#8b7fd6"></span>股票（權益工具,非債券）<span class="ix-cfg-note">FVTPL＋FVOCI 股票／受益憑證;FVOCI 股票玉山、國泰暫無</span></label>
</div></details>
</div></div>
<div class="card">
<div class="ix-kpihead"><h2 style="margin:0">本期速覽 <span class="ix-sub">所選期別,五家一眼(期間見上方工具列)</span></h2></div>
<div class="ix-kpi" id="ix_kpi"></div>
<div class="ix-concl" id="ix_concl"></div>
</div>

<div class="card">
<h2>跨行比較 <span class="ix-sub">同一期,誰的部位大、怎麼配(可切依債種或依會計分類)</span></h2>
<div class="ix-ctl"><label>分段</label><span class="ix-seg"><button id="A_by_b" class="on">依債種</button><button id="A_by_c">依會計分類</button></span><span id="A_catwrap"><label>分類</label><select id="A_c"><option value="合計" selected>三分類合計</option><option value="Trading">FVTPL</option><option value="OCI">FVOCI</option><option value="AC">AC</option></select></span><label>檢視</label><span class="ix-seg"><button id="A_amt" class="on">金額(億)</button><button id="A_pct">結構(%)</button></span></div>
<div class="ix-legend" id="A_lg"></div><div id="A_bars"></div><div id="ix_drill"></div>
<div style="font-size:12px;color:#8a919e;margin-top:6px">點銀行名展開該行明細;依債種檢視時,點圖例可聚焦單一債種。</div>
</div>

<div class="card">
<h2>時間趨勢 <span class="ix-sub">2020 以來,各家部位怎麼變</span></h2>
<div class="ix-ctl"><label>分類</label><select id="B_c"><option value="合計" selected>三分類合計</option><option value="Trading">FVTPL</option><option value="OCI">FVOCI</option><option value="AC">AC</option></select><label>債種</label><select id="B_b"><option value="合計">全部債種</option><option value="GB">政府公債</option><option value="公司債">公司債</option><option value="金融債">金融債</option><option value="資產基礎">資產基礎證券</option><option value="貨幣市場">貨幣市場(短)</option><option value="股票">股票</option></select></div>
<div class="ix-legend" id="B_lg"></div><div style="position:relative;width:100%;height:320px"><canvas id="B_cv" role="img" aria-label="五家銀行債券部位時間趨勢"></canvas></div>
</div>

<div class="ix-legend" style="margin-top:2px">
<span><span class="ix-sw" style="background:#f0f0f0;border:1px solid #ccc"></span>0 = 真實零部位</span>
<span><span class="ix-sw ix-hatch"></span>無資料(當期財報為掃描影像檔)</span></div>
</div>"""
    js=r"""
const BANKS=RAW.banks,PERIODS=RAW.periods,W=RAW.wide;
const ALLBONDS=[["GB","政府公債","#2a78d6"],["公司債","公司債","#1baf7a"],["金融債","金融債","#eda100"],["資產基礎","資產基礎證券","#d4318c"],["其他","其他債券","#a0a6b0"],["貨幣市場","貨幣市場","#888780"],["股票","股票","#8b7fd6"]];
const CATS=["Trading","OCI","AC"],SC=["#2a78d6","#1baf7a","#eda100","#4a3aa7","#d4318c"];
const PAL=SC.concat(["#e34948","#eb6834","#008300","#1d9e75","#534ab7"]);
const BC={};BANKS.forEach((b,i)=>BC[b]=PAL[i%PAL.length]);
let banksSel=new Set(BANKS);
function AB(){return BANKS.filter(b=>banksSel.has(b));}
let incl=new Set(["GB","公司債","金融債","資產基礎","其他"]);
function bondList(){return ALLBONDS.filter(b=>incl.has(b[0]));}
function has(p,bk){return W[p+"|"+bk]!=null;}
function val(p,bk,cat,bond){
  const row=W[p+"|"+bk];if(!row)return 0;
  if(cat==="合計")return CATS.reduce((s,c)=>s+(row[c+"_"+bond]||0),0);
  return row[cat+"_"+bond]||0;}
function total(p,bk,cat){return bondList().reduce((s,bd)=>s+val(p,bk,cat,bd[0]),0);}
function fmt(n){return Math.round(n).toLocaleString();}
function sgn(n){return (n>=0?"+":"−")+fmt(Math.abs(n));}
function prevP(p,step){const i=PERIODS.indexOf(p);return i-step>=0?PERIODS[i-step]:null;}
function fillSel(id,def){const s=document.getElementById(id);PERIODS.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;if(v===def)o.selected=true;s.appendChild(o);});}
function latestP(){for(let i=PERIODS.length-1;i>=0;i--){if(BANKS.some(b=>has(PERIODS[i],b)))return PERIODS[i];}return PERIODS[0];}
fillSel("G_p",latestP());
function gp(){return document.getElementById("G_p").value;}
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

function drawKPI(){
  const p=gp(),cat="合計";
  const rows=AB().filter(b=>has(p,b)).map(b=>({b,t:total(p,b,cat)}));
  const sum=rows.reduce((s,r)=>s+r.t,0),top=rows.reduce((a,b)=>b.t>a.t?b:a);
  const yp=prevP(p,2);
  const dts=yp?AB().filter(b=>has(p,b)&&has(yp,b)).map(b=>({b,d:total(p,b,cat)-total(yp,b,cat)})):[];
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
function syncIncl(){incl=new Set([...document.querySelectorAll(".inclbox:checked")].map(x=>x.value));}
document.querySelectorAll(".inclbox").forEach(cb=>cb.onchange=()=>{syncIncl();drawKPI();drawA();drawB();});
syncIncl();

let A_mode="amt",A_by="bond";
const CLS=[["Trading","FVTPL","#eb6834"],["OCI","FVOCI","#2a78d6"],["AC","AC","#4a3aa7"]];
const CLABEL={Trading:"FVTPL",OCI:"FVOCI",AC:"AC"};
function drawA(){
  const p=gp(),cat=A_c.value,bp=prevP(p,1),byCls=A_by==="cls";
  const cw=document.getElementById("A_catwrap");if(cw)cw.style.display=byCls?"none":"";
  const SEGS=byCls?CLS:bondList();
  const segVal=(bk,seg,per)=>byCls?bondList().reduce((s,bd)=>s+val(per,bk,seg[0],bd[0]),0):val(per,bk,cat,seg[0]);
  document.getElementById("A_lg").innerHTML=SEGS.map(seg=>{
    const cls=(!byCls&&focusBond)?(focusBond===seg[0]?' sel':' dim'):'';
    return '<span class="lg-item'+cls+'" data-seg="'+seg[0]+'"><span class="ix-sw" style="background:'+seg[2]+'"></span>'+seg[1]+'</span>';}).join("");
  if(!byCls)document.querySelectorAll("#A_lg .lg-item").forEach(li=>li.onclick=()=>{focusBond=(focusBond===li.dataset.seg)?null:li.dataset.seg;drawA();});
  const rows=AB().map(bk=>({bk,ok:has(p,bk),tot:SEGS.reduce((s,seg)=>s+segVal(bk,seg,p),0)}));
  const mx=Math.max(...rows.map(r=>r.tot),1);
  document.getElementById("A_bars").innerHTML=rows.map(r=>{
    if(!r.ok)return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div class="ix-na">無資料 · 該期財報為掃描影像檔</div><div class="ix-tot">N/A</div></div>';
    const base=A_mode==="pct"?(r.tot||1):mx,wp=A_mode==="pct"?100:(r.tot/mx*100);
    const inner=SEGS.map(seg=>{const v=segVal(r.bk,seg,p);if(v<=0)return"";
      const pct=r.tot?Math.round(v/r.tot*100):0;
      const pv=(bp&&has(bp,r.bk))?segVal(r.bk,seg,bp):null;
      const dtxt=pv==null?"—":sgn(v-pv)+" 億";
      const tip="<b>"+r.bk+" · "+seg[1]+"</b><br>"+fmt(v)+" 億 · 佔該行 "+pct+"%<br>較上期 "+dtxt;
      const dim=(!byCls&&focusBond&&focusBond!==seg[0])?" dim":"";
      return '<div class="ix-s2'+dim+'" style="width:'+(v/base*100)+'%;background:'+seg[2]+'" data-tip="'+tip.replace(/"/g,"&quot;")+'"></div>';}).join("");
    const lab=A_mode==="pct"?(r.tot?"100%":"0"):fmt(r.tot);
    return '<div class="ix-row"><div class="ix-name click" data-bank="'+r.bk+'">'+r.bk+'</div><div class="ix-track" style="width:'+Math.max(wp,0.5)+'%">'+inner+'</div><div class="ix-tot">'+lab+'</div></div>';
  }).join("");
  document.querySelectorAll("#A_bars .ix-name.click").forEach(n=>n.onclick=()=>renderDrill(drillBank===n.dataset.bank?null:n.dataset.bank));
  if(drillBank)renderDrill(drillBank);
}
document.getElementById("A_c").onchange=drawA;
document.getElementById("G_p").addEventListener("change",()=>{drawKPI();drawA();});
A_amt.onclick=()=>{A_mode="amt";A_amt.classList.add("on");A_pct.classList.remove("on");drawA();};
A_pct.onclick=()=>{A_mode="pct";A_pct.classList.add("on");A_amt.classList.remove("on");drawA();};
A_by_b.onclick=()=>{A_by="bond";A_by_b.classList.add("on");A_by_c.classList.remove("on");drawA();};
A_by_c.onclick=()=>{A_by="cls";A_by_c.classList.add("on");A_by_b.classList.remove("on");drawA();};


let chartB=null;
function drawB(){
  const cat=B_c.value,bond=B_b.value,dash=[[],[6,4],[2,3],[8,3,2,3],[]];
  const withCP=incl.has("貨幣市場")&&(bond==="合計");
  const vOf=(p,bk)=>bond==="合計"?total(p,bk,cat):val(p,bk,cat,bond);
  const ds=AB().map((bk)=>{const i=BANKS.indexOf(bk);return {label:bk,data:PERIODS.map(p=>has(p,bk)?vOf(p,bk):null),borderColor:BC[bk],backgroundColor:BC[bk],borderDash:dash[i%dash.length],spanGaps:false,borderWidth:2,tension:0.25,pointRadius:2,pointHoverRadius:5};});
  document.getElementById("B_lg").innerHTML=AB().map((bk)=>'<span><span class="ix-sw" style="background:'+BC[bk]+'"></span>'+bk+'</span>').join("")+(withCP?' <span style="color:#999">(已含貨幣市場)</span>':'');
  if(chartB)chartB.destroy();
  chartB=new Chart(document.getElementById("B_cv"),{type:"line",data:{labels:PERIODS,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.dataset.label+": "+fmt(c.parsed.y)+" 億"}}},
      scales:{y:{title:{display:true,text:"億元"}},x:{grid:{display:false},ticks:{maxRotation:45,autoSkip:false}}}}});
}
["B_c","B_b"].forEach(id=>document.getElementById(id).onchange=drawB);

const bcEl=document.getElementById("bankchips");
if(bcEl){bcEl.innerHTML=BANKS.map(b=>{
    const filled=PERIODS.map(p=>has(p,b));
    const cnt=filled.filter(Boolean).length;
    const pr=PERIODS.filter((p,i)=>filled[i]);
    const range=pr.length?pr[0]+"–"+pr[pr.length-1]:"無資料";
    const ticks=filled.map(f=>'<span class="tk" style="background:'+(f?BC[b]:"#e3e5e9")+'"></span>').join("");
    return '<button class="ov-chip on" data-bank="'+b+'" title="'+b+':'+cnt+' 期 · '+range+'"><span class="top"><span class="ix-sw" style="background:'+BC[b]+'"></span>'+b+'<span class="cnt">'+cnt+' 期</span></span><span class="ticks">'+ticks+'</span></button>';
  }).join("");
  bcEl.querySelectorAll(".ov-chip").forEach(ch=>ch.onclick=()=>{const b=ch.dataset.bank;
    if(banksSel.has(b)){if(banksSel.size<=1)return;banksSel.delete(b);ch.classList.remove("on");}
    else{banksSel.add(b);ch.classList.add("on");}
    if(drillBank&&!banksSel.has(drillBank)){drillBank=null;document.getElementById("ix_drill").innerHTML="";}
    drawKPI();drawA();drawB();});
}
drawKPI();drawA();drawB();
"""
    return (css + markup
            + '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
            + '<script>const RAW=' + payload + ';\n' + js + '</script>')

# 美國10年期公債殖利率(期末,%)— render-only 內建參考值;2020–2024為市場實績,2025為估計待校正
US10Y={"2020H1":0.66,"2020H2":0.93,"2021H1":1.45,"2021H2":1.52,
       "2022H1":3.01,"2022H2":3.88,"2023H1":3.81,"2023H2":3.88,
       "2024H1":4.40,"2024H2":4.58,"2025H1":4.24,"2025H2":4.40}

# ---- 估值視角:帳上(AOCI)vs 帳外(AC隱藏損失) ----
def valuation_html():
    payload=json.dumps(P0, ensure_ascii=False)
    css="""<style>
.vw{font-family:inherit}
.vrow{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.vrow .ix-name{width:38px}
.vpair{flex:1;display:flex;flex-direction:column;gap:6px}
.vline{display:flex;align-items:center;gap:10px}
.vtag{width:74px;font-size:11px;color:#8a919e;text-align:right;flex:none}
.vtrack{position:relative;flex:1;height:19px;background:#f2f3f5;border-radius:5px}
.vcenter{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#c6cbd4}
.vfill{position:absolute;top:0;bottom:0;border-radius:4px;transition:all .2s}
.vval{width:104px;font-size:12px;text-align:left;flex:none;font-variant-numeric:tabular-nums;color:#111827}
.vna{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:10px;color:#a0a6b0;background:repeating-linear-gradient(45deg,#f5f6f8,#f5f6f8 5px,rgba(150,156,168,.22) 5px,rgba(150,156,168,.22) 7px);border-radius:5px}
.vhint{font-size:12px;color:#8a919e;margin-top:8px;line-height:1.7}
</style>"""
    markup="""<div class="vw">
<div class="card">
<div class="ix-kpihead"><h2 style="margin:0">估值視角:債券含損,帳上 vs 帳外 <span class="ix-sub">升息後 FVOCI 已進權益、AC 按成本藏在帳外</span></h2></div>
<div class="ix-kpi" id="v_kpi"></div>
<div class="ix-ctl"><label>檢視</label><span class="ix-seg"><button id="v_amt" class="on">金額(億)</button><button id="v_pct">占AC%</button></span><span class="ix-sub" style="margin-left:auto">期間由上方工具列控制</span></div>
<div class="ix-legend"><span><span class="ix-sw" style="background:#4a3aa7"></span>帳上 AOCI(FVOCI 已認列於權益)</span><span><span class="ix-sw" style="background:#e34948"></span>帳外 AC 隱藏損失(未認列)</span><span><span class="ix-sw" style="background:#b3261e"></span>真實含損 = 帳上+帳外</span><span style="color:#8a919e">綠=含益、紅=含損</span></div>
<div id="v_bars"></div>
<div class="vhint">AOCI=透過其他綜合損益之金融資產未實現損益(稅後,已在權益);AC 隱藏損失=按攤銷後成本部位的公允價值−帳面,升息時為負且<b>不反映在權益</b>。兩者相加≈債券部位的真實含損。</div>
</div>
<div class="card">
<h2>AC 隱藏損失趨勢 <span class="ix-sub">占 AC 帳面 %,看利率循環(2022 升息谷底)</span></h2>
<div class="ix-legend" id="vt_lg"></div>
<div style="position:relative;width:100%;height:300px"><canvas id="vt_cv" role="img" aria-label="AC隱藏損失占比時間趨勢"></canvas></div>
</div>
<div class="card">
<h2>利率風險視角 <span class="ix-sub">AC 隱藏損失反推:同樣升息下,誰的 AC 對利率最敏感(duration 最長)</span></h2>
<div id="ir_bars"></div>
<div class="vhint">利率一起漲時,AC 跌越多 = 存續期間(duration)越長。<b>隱含 duration(粗估)≈ AC隱藏損失% ÷ 期間累計升幅</b>(美 10Y 較 2020 低點 0.9%)。此為<b>跨行相對</b>強弱的 proxy,受買進時點、台美利率、外幣匯率影響,非精算 duration。</div>
</div>
</div>"""
    js=r"""
(function(){
const P=PH0.periods,B=PH0.banks,DD=PH0.data;
const VC={"中信":"#2a78d6","兆豐":"#1baf7a","國泰":"#eda100","富邦":"#4a3aa7","玉山":"#008300"};
const g=(p,bk)=>DD[p+"|"+bk]||null;
const fmt=n=>Math.round(n).toLocaleString();
const sgn=n=>(n>=0?"+":"−")+fmt(Math.abs(n));
const sel=document.getElementById("G_p");   // 期間改用全域工具列選擇器
let vMode="amt";
function divbar(v,mx,neg,pos){
  if(v==null||mx<=0)return '<div class="vtrack"><div class="vna">無資料</div></div>';
  const w=Math.min(Math.abs(v)/mx*50,50),isn=v<0,col=isn?neg:pos;
  const left=isn?(50-w):50;
  return '<div class="vtrack"><div class="vcenter"></div><div class="vfill" style="left:'+left+'%;width:'+w+'%;background:'+col+'"></div></div>';
}
function drawV(){
  const p=sel.value,pctm=vMode==="pct";
  const comb=bk=>{const d=g(p,bk);return (d&&d.aoci!=null&&d.ac_hidden!=null)?d.aoci+d.ac_hidden:null;};
  let aociMax=0,acMax=0,cMax=0;
  B.forEach(bk=>{const d=g(p,bk);if(!d)return;
    if(d.aoci!=null)aociMax=Math.max(aociMax,Math.abs(d.aoci));
    if(pctm){if(d.ac_hidden_pct!=null)acMax=Math.max(acMax,Math.abs(d.ac_hidden_pct*100));}
    else if(d.ac_hidden!=null)acMax=Math.max(acMax,Math.abs(d.ac_hidden));
    const c=comb(bk);if(c!=null)cMax=Math.max(cMax,Math.abs(c));});
  aociMax=aociMax||1;acMax=acMax||1;cMax=cMax||1;
  document.getElementById("v_bars").innerHTML=B.map(bk=>{
    const d=g(p,bk);
    const aoci=d?d.aoci:null, ach=d?d.ac_hidden:null, pct=d?d.ac_hidden_pct:null, c=comb(bk);
    const upVal = aoci==null? 'N/A' : (sgn(aoci)+' 億');
    const dnVal = pctm? (pct==null?'N/A':(pct>=0?'+':'−')+Math.abs(pct*100).toFixed(2)+'%')
                      : (ach==null?'N/A':sgn(ach)+' 億');
    const cVal = c==null? 'N/A' : (sgn(c)+' 億');
    const upBar = divbar(aoci, aociMax, "#8b7fd6", "#8bc34a");     // 帳上 AOCI 恆用億
    const dnBar = pctm? divbar(pct==null?null:pct*100, acMax, "#e34948", "#1baf7a")
                      : divbar(ach, acMax, "#e34948", "#1baf7a");  // 帳外 AC 切億/%
    const cBar = divbar(c, cMax, "#b3261e", "#1e7d4f");            // 真實含損合計 恆用億
    return '<div class="vrow"><div class="ix-name">'+bk+'</div><div class="vpair">'+
      '<div class="vline"><div class="vtag">帳上 AOCI</div>'+upBar+'<div class="vval">'+upVal+'</div></div>'+
      '<div class="vline"><div class="vtag">帳外 AC隱藏</div>'+dnBar+'<div class="vval">'+dnVal+'</div></div>'+
      '<div class="vline"><div class="vtag" style="font-weight:600;color:#5f6672">真實含損</div>'+cBar+'<div class="vval" style="font-weight:600">'+cVal+'</div></div>'+
      '</div></div>';
  }).join("");
  drawVKPI(p);
  drawIR(p);
}
function drawIR(p){
  const el=document.getElementById("ir_bars");if(!el)return;
  const RBASE=0.93, dy=(RATE[p]!=null)?(RATE[p]-RBASE):null;   // 期間累計升幅(pp)
  let rows=B.map(bk=>{const d=g(p,bk);return {bk,pct:d?d.ac_hidden_pct:null};}).filter(o=>o.pct!=null);
  rows.sort((a,b)=>Math.abs(b.pct)-Math.abs(a.pct));            // 風險大→小
  if(!rows.length){el.innerHTML='<div class="vhint">本期無 AC 隱藏損失資料</div>';return;}
  const mx=Math.max(...rows.map(o=>Math.abs(o.pct)),0.0001);
  el.innerHTML=rows.map(o=>{
    const lp=o.pct*100, w=Math.abs(o.pct)/mx*100;
    const dur=(dy&&dy>1)?(Math.abs(lp)/dy):null;
    const durTxt=dur!=null?('隱含 '+dur.toFixed(1)+' 年'):'利率仍低,不適用';
    return '<div class="vrow"><div class="ix-name">'+o.bk+'</div>'+
      '<div class="vtrack" style="height:22px"><div class="vfill" style="left:0;width:'+w+'%;background:'+(VC[o.bk]||"#c2410c")+'"></div></div>'+
      '<div class="vval" style="width:158px">'+lp.toFixed(1)+'% · '+durTxt+'</div></div>';
  }).join("");
}
function drawVKPI(p){
  const hid=B.map(bk=>({bk,d:g(p,bk)})).filter(o=>o.d&&o.d.ac_hidden!=null);
  const sum=hid.reduce((s,o)=>s+o.d.ac_hidden,0);
  const worst=hid.length?hid.reduce((a,b)=>(b.d.ac_hidden_pct<a.d.ac_hidden_pct?b:a)):null;
  const aoc=B.map(bk=>g(p,bk)).filter(d=>d&&d.aoci!=null);
  const asum=aoc.reduce((s,d)=>s+d.aoci,0);
  const cards=[
    worst?["AC隱藏損失最深(占AC%)",worst.bk,(worst.d.ac_hidden_pct*100).toFixed(1)+"% · "+p]:null,
    ["AOCI帳上合計("+aoc.length+"家)",sgn(asum)+" 億","已認列於權益"]].filter(Boolean);
  document.getElementById("v_kpi").innerHTML=cards.map(c=>'<div class="ix-kcard"><div class="ix-klabel">'+c[0]+'</div><div class="ix-kval">'+c[1]+'</div><div class="ix-ksub">'+c[2]+'</div></div>').join("");
}
sel.addEventListener("change",drawV);
document.getElementById("v_amt").onclick=()=>{vMode="amt";v_amt.classList.add("on");v_pct.classList.remove("on");drawV();};
document.getElementById("v_pct").onclick=()=>{vMode="pct";v_pct.classList.add("on");v_amt.classList.remove("on");drawV();};
// 趨勢圖
const dash=[[],[6,4],[2,3],[8,3,2,3],[]];
const ds=B.map((bk,i)=>({label:bk,data:P.map(p=>{const d=g(p,bk);return d&&d.ac_hidden_pct!=null?+(d.ac_hidden_pct*100).toFixed(2):null;}),
  borderColor:VC[bk],backgroundColor:VC[bk],borderDash:dash[i%dash.length],spanGaps:false,borderWidth:2,tension:.25,pointRadius:2,pointHoverRadius:5,yAxisID:"y"}));
// 疊美國10年公債殖利率(右軸,參考驅動線):升息→隱藏損失擴大,兩線反向
ds.push({label:"美國10Y殖利率",data:P.map(p=>RATE[p]!=null?RATE[p]:null),borderColor:"#111827",
  backgroundColor:"#111827",borderDash:[3,3],borderWidth:2.5,tension:.25,pointRadius:0,spanGaps:true,yAxisID:"y1"});
document.getElementById("vt_lg").innerHTML=B.map(bk=>'<span><span class="ix-sw" style="background:'+VC[bk]+'"></span>'+bk+'</span>').join("")
  +'<span style="margin-left:6px"><span class="ix-sw" style="background:#111827"></span>美國10Y殖利率(右軸,參考)</span>';
new Chart(document.getElementById("vt_cv"),{type:"line",data:{labels:P,datasets:ds},
  options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
    plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.y==null?null:c.dataset.label+": "+c.parsed.y+"%"}}},
    scales:{y:{position:"left",title:{display:true,text:"AC隱藏損失 占AC %"},ticks:{callback:v=>v+"%"}},
      y1:{position:"right",title:{display:true,text:"美10Y殖利率 %"},grid:{display:false},ticks:{callback:v=>v+"%"}},
      x:{grid:{display:false},ticks:{maxRotation:45,autoSkip:false}}}}});
drawV();
})();
"""
    return (css + markup
            + '<script>const PH0=' + payload + ';\nconst RATE=' + json.dumps(US10Y, ensure_ascii=False) + ';\n' + js + '</script>')

now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
html=f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>銀行債券投資 債種分析</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--ink:#111827;--sub:#5f6672;--mut:#8a919e;--line:#e9ebef;--bg:#f5f6f8;--accent:#4f46e5}}
*{{box-sizing:border-box}}
body{{font-family:Inter,-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;margin:0;background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}}
header{{background:#fff;border-bottom:1px solid var(--line);padding:18px 28px;position:sticky;top:0;z-index:10;display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}}
header h1{{margin:0;font-size:16px;font-weight:600;letter-spacing:-.01em}}
header .upd{{color:var(--mut);font-size:12px;white-space:nowrap}}
header p{{margin:3px 0 0;color:var(--mut);font-size:12px}}
.wrap{{max-width:1100px;margin:0 auto;padding:28px 20px 60px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 2px rgba(16,24,40,.04);padding:22px 24px;margin:0 0 20px}}
.card h2{{margin:0 0 16px;font-size:14px;font-weight:600;color:var(--sub);text-transform:none;letter-spacing:.01em}}
img{{width:100%;height:auto;border-radius:8px}}
details.card{{padding:0}}
details.card>summary{{cursor:pointer;list-style:none;padding:18px 24px;font-size:14px;font-weight:600;color:var(--sub);display:flex;align-items:center;gap:8px}}
details.card>summary::before{{content:"▸";color:var(--mut);transition:transform .15s}}
details.card[open]>summary::before{{transform:rotate(90deg)}}
details.card>.inner{{padding:0 24px 22px}}
.note{{font-size:13px;color:var(--sub);line-height:1.8}}
.ov-stats{{display:flex;gap:36px;flex-wrap:wrap;margin-bottom:18px}}
.ov-n{{font-size:24px;font-weight:600;color:var(--ink);letter-spacing:-.02em;line-height:1.1}}
.ov-l{{font-size:12px;color:var(--mut);margin-top:4px}}
.ov-filter{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:16px}}
.ov-fl{{font-size:12px;color:var(--mut)}}
#bankchips{{display:flex;gap:10px;flex-wrap:wrap}}
.ov-chip{{display:inline-flex;flex-direction:column;align-items:flex-start;gap:6px;font-size:13px;padding:9px 13px;border:1px solid var(--line);border-radius:12px;background:#fff;color:var(--mut);cursor:pointer}}
.ov-chip .top{{display:flex;align-items:center;gap:6px}}
.ov-chip .cnt{{font-size:11px;color:var(--mut);font-weight:400;margin-left:2px}}
.ov-chip .ticks{{display:flex;gap:2px}}
.ov-chip .tk{{width:6px;height:6px;border-radius:2px}}
.ov-chip .ix-sw{{opacity:.35}}
.ov-chip.on{{border-color:#c6cbd4;color:var(--ink);font-weight:500}}
.ov-chip.on .ix-sw{{opacity:1}}
.ov-chip:not(.on) .ticks{{opacity:.4}}
.foot{{margin:4px 2px 0}}
.foot>summary{{list-style:none;cursor:pointer;font-size:12px;color:var(--mut);user-select:none}}
.foot>summary::-webkit-details-marker{{display:none}}
.foot>summary::before{{content:"▸ ";color:var(--mut)}}
.foot[open]>summary::before{{content:"▾ "}}
.foot-in{{font-size:12px;color:var(--mut);line-height:1.9;padding:8px 2px 0}}
.tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px}}
table.wide{{border-collapse:collapse;font-size:12px;white-space:nowrap;width:100%}}
table.wide th,table.wide td{{border-bottom:1px solid var(--line);padding:6px 10px;text-align:right}}
table.wide thead th{{background:#f8f9fb;color:var(--sub);font-weight:600;text-align:center;position:sticky;top:0}}
table.wide th.rowh{{background:#f8f9fb;text-align:left;position:sticky;left:0;z-index:1;color:var(--ink);font-weight:500}}
table.wide tbody tr:hover td{{background:#fafbfc}}
@media print{{header{{position:static}}.card{{box-shadow:none;break-inside:avoid}}details.card{{display:none}}}}
</style></head><body>
<header><h1>銀行債券投資債種分析</h1><span class="upd">更新 {now}</span></header>
<div class="wrap">
{interactive_html()}
{valuation_html()}
<details class="foot"><summary>資料說明與口徑</summary>
<div class="foot-in">
· 單位:億元。資料期間 {(_have or PERIODS)[0]}–{(_have or PERIODS)[-1]},每半年一期(H1=6/30、H2=12/31 期末餘額)。<br>
· 會計分類(IFRS 9):<b>FVTPL</b> 透過損益按公允價值衡量(即交易目的,附註六(三))、<b>FVOCI</b> 透過其他綜合損益(六(四))、<b>AC</b> 按攤銷後成本(六(五))。<br>
· <b>兆豐</b>債種明細來自其財報「證券部門變動明細表」;其證券部門無 FVTPL 部位,故 FVTPL 為 0。<br>
· 2020H1 國泰/玉山之個體財報為掃描影像檔,無法解析,標為「無資料」。<br>
· 數據經三層 checksum 驗算;本頁由 GitHub Actions 自動更新。
</div></details>
</div></body></html>"""
(SITE/"index.html").write_text(html, encoding="utf-8")
print("已產生 site/ (index.html + 圖1/圖2.png + xlsx)")
