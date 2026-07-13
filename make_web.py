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
</style>"""
    markup="""<div class="ix">
<div class="card">
<div class="ix-kpihead"><h2 style="margin:0">本期速覽 <span class="ix-sub">最新一期,五家一眼</span></h2>
<details class="ix-cfg"><summary><span class="ix-cfg-ic">⚙</span>選擇項目<span class="ix-cfg-ar">▾</span></summary>
<div class="ix-cfg-panel">
<div class="ix-cfg-h">計入「部位」的項目(全頁與 KPI 連動)</div>
<label><input type="checkbox" class="inclbox" value="GB" checked autocomplete="off"><span class="ix-sw" style="background:#2a78d6"></span>政府公債</label>
<label><input type="checkbox" class="inclbox" value="公司債" checked autocomplete="off"><span class="ix-sw" style="background:#1baf7a"></span>公司債</label>
<label><input type="checkbox" class="inclbox" value="金融債" checked autocomplete="off"><span class="ix-sw" style="background:#eda100"></span>金融債</label>
<label><input type="checkbox" class="inclbox" value="CP" autocomplete="off"><span class="ix-sw" style="background:#888780"></span>貨幣市場<span class="ix-cfg-note">商業本票／可轉讓定存單／國庫券,非債券,僅 Trading 有</span></label>
</div></details></div>
<div class="ix-kpi" id="ix_kpi"></div>
</div>

<div class="card">
<h2>跨行比較 <span class="ix-sub">同一期,誰的部位大、怎麼配(可切依債種或依會計分類)</span></h2>
<div class="ix-ctl"><label>期間</label><select id="A_p"></select><label>分段</label><span class="ix-seg"><button id="A_by_b" class="on">依債種</button><button id="A_by_c">依會計分類</button></span><span id="A_catwrap"><label>分類</label><select id="A_c"><option value="合計" selected>三分類合計</option><option value="Trading">Trading</option><option value="OCI">OCI</option><option value="AC">AC</option></select></span><label>檢視</label><span class="ix-seg"><button id="A_amt" class="on">金額(億)</button><button id="A_pct">結構(%)</button></span></div>
<div class="ix-legend" id="A_lg"></div><div id="A_bars"></div><div id="ix_drill"></div>
<div style="font-size:12px;color:#8a919e;margin-top:6px">點銀行名展開該行明細;依債種檢視時,點圖例可聚焦單一債種。</div>
</div>

<div class="card">
<h2>時間趨勢 <span class="ix-sub">2020 以來,各家部位怎麼變</span></h2>
<div class="ix-ctl"><label>分類</label><select id="B_c"><option value="合計" selected>三分類合計</option><option value="Trading">Trading</option><option value="OCI">OCI</option><option value="AC">AC</option></select><label>債種</label><select id="B_b"><option value="合計">全部債種</option><option value="GB">政府公債</option><option value="公司債">公司債</option><option value="金融債">金融債</option></select></div>
<div class="ix-legend" id="B_lg"></div><div style="position:relative;width:100%;height:320px"><canvas id="B_cv" role="img" aria-label="五家銀行債券部位時間趨勢"></canvas></div>
</div>

<div class="card">
<h2>自由探索 <span class="ix-sub">銀行 × 債種熱力圖,掃全局</span></h2>
<div class="ix-ctl"><label>期間</label><select id="C_p"></select><label>分類</label><select id="C_c"><option value="合計" selected>三分類合計</option><option value="Trading">Trading</option><option value="OCI">OCI</option><option value="AC">AC</option></select></div>
<div id="C_grid"></div>
<div class="ix-legend" style="margin-top:14px;border-top:1px solid #e9ebef;padding-top:12px">
<span><span class="ix-sw" style="background:#f0f0f0;border:1px solid #ccc"></span>0 = 真實零部位</span>
<span><span class="ix-sw ix-hatch"></span>無資料(當期財報為掃描影像檔)</span></div>
</div>
</div>"""
    js=r"""
const BANKS=RAW.banks,PERIODS=RAW.periods,W=RAW.wide;
const ALLBONDS=[["GB","政府公債","#2a78d6"],["公司債","公司債","#1baf7a"],["金融債","金融債","#eda100"],["CP","貨幣市場","#888780"]];
const CATS=["Trading","OCI","AC"],SC=["#2a78d6","#1baf7a","#eda100","#4a3aa7","#d4318c"];
const PAL=SC.concat(["#e34948","#eb6834","#008300","#1d9e75","#534ab7"]);
const BC={};BANKS.forEach((b,i)=>BC[b]=PAL[i%PAL.length]);
let banksSel=new Set(BANKS);
function AB(){return BANKS.filter(b=>banksSel.has(b));}
let incl=new Set(["GB","公司債","金融債"]);
function bondList(){return ALLBONDS.filter(b=>incl.has(b[0]));}
function has(p,bk){return W[p+"|"+bk]!=null;}
function val(p,bk,cat,bond){
  const row=W[p+"|"+bk];if(!row)return 0;
  if(bond==="CP")return (cat==="Trading"||cat==="合計")?(row["Trading_CP+NCD+BA"]||0):0;
  if(cat==="合計")return CATS.reduce((s,c)=>s+(row[c+"_"+bond]||0),0);
  return row[cat+"_"+bond]||0;}
function total(p,bk,cat){return bondList().reduce((s,bd)=>s+val(p,bk,cat,bd[0]),0);}
function fmt(n){return Math.round(n).toLocaleString();}
function sgn(n){return (n>=0?"+":"−")+fmt(Math.abs(n));}
function prevP(p,step){const i=PERIODS.indexOf(p);return i-step>=0?PERIODS[i-step]:null;}
function fillSel(id,def){const s=document.getElementById(id);PERIODS.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;if(v===def)o.selected=true;s.appendChild(o);});}
function latestP(){for(let i=PERIODS.length-1;i>=0;i--){if(BANKS.some(b=>has(PERIODS[i],b)))return PERIODS[i];}return PERIODS[0];}
["A_p","C_p"].forEach(id=>fillSel(id,latestP()));
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
  drillBank=bk;const p=A_p.value,BD=bondList(),el=document.getElementById("ix_drill");
  if(!bk||!has(p,bk)){el.innerHTML="";drillBank=null;return;}
  const catTots=CATS.map(c=>({c,segs:BD.map(bd=>val(p,bk,c,bd[0]))}));
  const mx=Math.max(...catTots.map(o=>o.segs.reduce((a,b)=>a+b,0)),1);
  const rows=catTots.map(o=>{
    const tot=o.segs.reduce((a,b)=>a+b,0);
    const inner=BD.map((bd,i)=>{const v=o.segs[i];return v<=0?"":'<div style="width:'+(v/mx*100)+'%;background:'+bd[2]+'" data-tip="<b>'+o.c+' · '+bd[1]+'</b><br>'+fmt(v)+' 億"></div>';}).join("");
    return '<div class="ix-mini"><div class="lb">'+o.c+'</div><div class="tk">'+inner+'</div><div class="vv">'+fmt(tot)+'</div></div>';
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
  const p=latestP(),cat="合計";
  const rows=AB().filter(b=>has(p,b)).map(b=>({b,t:total(p,b,cat)}));
  const sum=rows.reduce((s,r)=>s+r.t,0),top=rows.reduce((a,b)=>b.t>a.t?b:a);
  const yp=prevP(p,2);
  const dts=yp?AB().filter(b=>has(p,b)&&has(yp,b)).map(b=>({b,d:total(p,b,cat)-total(yp,b,cat)})):[];
  const up=dts.length?dts.reduce((a,b)=>b.d>a.d?b:a):null,dn=dts.length?dts.reduce((a,b)=>b.d<a.d?b:a):null;
  const SHORT={GB:"公債","公司債":"公司債","金融債":"金融債",CP:"貨幣"};
  const scope=ALLBONDS.filter(b=>incl.has(b[0])).map(b=>SHORT[b[0]]).join("+")||"(未選)";
  const cards=[["本期合計("+rows.length+"家)",fmt(sum)+" 億",scope+" · "+p],["部位最大",top.b,fmt(top.t)+" 億"]];
  if(up)cards.push(["加碼最多(YoY)",up.b,sgn(up.d)+" 億"]);
  if(dn)cards.push(["減碼最多(YoY)",dn.b,sgn(dn.d)+" 億"]);
  document.getElementById("ix_kpi").innerHTML=cards.map(c=>'<div class="ix-kcard"><div class="ix-klabel">'+c[0]+'</div><div class="ix-kval">'+c[1]+'</div><div class="ix-ksub">'+c[2]+'</div></div>').join("");
}
function syncIncl(){incl=new Set([...document.querySelectorAll(".inclbox:checked")].map(x=>x.value));}
document.querySelectorAll(".inclbox").forEach(cb=>cb.onchange=()=>{syncIncl();drawKPI();drawA();drawC();drawB();});
syncIncl();

let A_mode="amt",A_by="bond";
const CLS=[["Trading","Trading","#eb6834"],["OCI","OCI","#2a78d6"],["AC","AC","#4a3aa7"]];
function drawA(){
  const p=A_p.value,cat=A_c.value,bp=prevP(p,1),byCls=A_by==="cls";
  const cw=document.getElementById("A_catwrap");if(cw)cw.style.display=byCls?"none":"";
  const SEGS=byCls?CLS:bondList();
  const segVal=(bk,seg,per)=>byCls?bondList().reduce((s,bd)=>s+val(per,bk,seg[0],bd[0]),0):val(per,bk,cat,seg[0]);
  document.getElementById("A_lg").innerHTML=SEGS.map(seg=>{
    const cls=(!byCls&&focusBond)?(focusBond===seg[0]?' sel':' dim'):'';
    return '<span class="lg-item'+cls+'" data-seg="'+seg[0]+'"><span class="ix-sw" style="background:'+seg[2]+'"></span>'+seg[1]+'</span>';}).join("");
  if(!byCls)document.querySelectorAll("#A_lg .lg-item").forEach(li=>li.onclick=()=>{focusBond=(focusBond===li.dataset.seg)?null:li.dataset.seg;drawA();drawC();});
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
["A_p","A_c"].forEach(id=>document.getElementById(id).onchange=drawA);
A_amt.onclick=()=>{A_mode="amt";A_amt.classList.add("on");A_pct.classList.remove("on");drawA();};
A_pct.onclick=()=>{A_mode="pct";A_pct.classList.add("on");A_amt.classList.remove("on");drawA();};
A_by_b.onclick=()=>{A_by="bond";A_by_b.classList.add("on");A_by_c.classList.remove("on");drawA();};
A_by_c.onclick=()=>{A_by="cls";A_by_c.classList.add("on");A_by_b.classList.remove("on");drawA();};

function drawC(){
  const p=C_p.value,cat=C_c.value,BD=bondList();
  let mx=1;AB().forEach(bk=>{if(has(p,bk))BD.forEach(bd=>{const v=val(p,bk,cat,bd[0]);if(v>mx)mx=v;});});
  let h='<div style="font-size:12px;color:#999;margin-bottom:8px">色深=部位規模(億元)。</div><div style="display:grid;grid-template-columns:40px repeat('+BD.length+',1fr);gap:4px">';
  h+='<div></div>'+BD.map(bd=>'<div style="font-size:12px;color:#666;text-align:center;padding-bottom:2px">'+bd[1]+'</div>').join("");
  AB().forEach(bk=>{
    h+='<div style="font-size:13px;display:flex;align-items:center;justify-content:flex-end;padding-right:4px">'+bk+'</div>';
    if(!has(p,bk)){h+='<div style="grid-column:span '+BD.length+';height:52px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#999;background:repeating-linear-gradient(45deg,#f5f6f5,#f5f6f5 5px,rgba(150,150,150,.25) 5px,rgba(150,150,150,.25) 7px)">無資料(掃描影像檔)</div>';return;}
    BD.forEach(bd=>{const v=val(p,bk,cat,bd[0]),t=v/mx;const bg=v<=0?"#f0f0f0":"rgba(42,120,214,"+(0.12+t*0.8).toFixed(2)+")",col=t>0.45?"#fff":"#222";
      const dim=(focusBond&&focusBond!==bd[0])?" dim":"";
      const tip="<b>"+bk+" · "+bd[1]+"</b><br>"+fmt(v)+" 億 · "+p+"("+cat+")";
      h+='<div class="ix-cell'+dim+'" style="background:'+bg+';border-radius:6px;height:52px;display:flex;align-items:center;justify-content:center;font-size:13px;color:'+col+';transition:opacity .15s" data-tip="'+tip.replace(/"/g,"&quot;")+'">'+(v>0?fmt(v):"0")+'</div>';});
  });
  document.getElementById("C_grid").innerHTML=h+'</div>';
}
["C_p","C_c"].forEach(id=>document.getElementById(id).onchange=drawC);

let chartB=null;
function drawB(){
  const cat=B_c.value,bond=B_b.value,dash=[[],[6,4],[2,3],[8,3,2,3],[]];
  const withCP=incl.has("CP")&&(bond==="合計");
  const vOf=(p,bk)=>bond==="合計"?total(p,bk,cat):val(p,bk,cat,bond);
  const ds=AB().map((bk)=>{const i=BANKS.indexOf(bk);return {label:bk,data:PERIODS.map(p=>has(p,bk)?vOf(p,bk):null),borderColor:BC[bk],backgroundColor:BC[bk],borderDash:dash[i%dash.length],spanGaps:false,borderWidth:2,tension:0.25,pointRadius:2,pointHoverRadius:5};});
  document.getElementById("B_lg").innerHTML=AB().map((bk)=>'<span><span class="ix-sw" style="background:'+BC[bk]+'"></span>'+bk+'</span>').join("")+(withCP?' <span style="color:#999">(已含CP)</span>':'');
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
    drawKPI();drawA();drawC();drawB();});
}
drawKPI();drawA();drawC();drawB();
"""
    return (css + markup
            + '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
            + '<script>const RAW=' + payload + ';\n' + js + '</script>')

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
<div class="card ov">
<div class="ov-stats">
<div class="ov-stat"><div class="ov-n">{len(BANKS)}</div><div class="ov-l">家銀行</div></div>
<div class="ov-stat"><div class="ov-n">{len(_have or PERIODS)}</div><div class="ov-l">期(半年)</div></div>
<div class="ov-stat"><div class="ov-n">{(_have or PERIODS)[0]}–{(_have or PERIODS)[-1]}</div><div class="ov-l">涵蓋期間</div></div>
</div>
<div class="ov-filter"><span class="ov-fl">顯示銀行</span><div id="bankchips"></div></div>
</div>
{interactive_html()}
<details class="foot"><summary>資料說明與口徑</summary>
<div class="foot-in">
· 單位:億元。資料期間 {(_have or PERIODS)[0]}–{(_have or PERIODS)[-1]},每半年一期(H1=6/30、H2=12/31 期末餘額)。<br>
· <b>兆豐</b>債種明細來自其財報「證券部門變動明細表」;其證券部門無 Trading 部位,故 Trading 為 0。<br>
· 2020H1 國泰/玉山之個體財報為掃描影像檔,無法解析,標為「無資料」。<br>
· 數據經三層 checksum 驗算;本頁由 GitHub Actions 自動更新。
</div></details>
</div></body></html>"""
(SITE/"index.html").write_text(html, encoding="utf-8")
print("已產生 site/ (index.html + 圖1/圖2.png + xlsx)")
