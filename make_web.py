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
    payload=json.dumps({"periods":PERIODS,"banks":BANKS,"wide":D.get("wide",{})}, ensure_ascii=False)
    css="""<style>
.ix{font-family:inherit}
.ix-tabs{display:inline-flex;gap:2px;flex-wrap:wrap;margin-bottom:12px;background:#eef0f3;border-radius:10px;padding:3px}
.ix-tab{font-size:13px;padding:7px 16px;border:none;border-radius:8px;background:transparent;cursor:pointer;color:#5f6672;transition:all .15s}
.ix-tab.on{background:#fff;color:#111827;font-weight:600;box-shadow:0 1px 2px rgba(16,24,40,.08)}
.ix-cptog{display:flex;align-items:center;gap:8px;font-size:13px;color:#5f6672;margin:0 0 20px;cursor:pointer}
.ix-cptog input{accent-color:#4f46e5}
.ix-ctl{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.ix-ctl label{font-size:12px;color:#8a919e;margin-left:6px}
.ix-ctl select{height:34px;border:1px solid #e0e3e8;border-radius:8px;padding:0 8px;background:#fff;color:#111827;font-size:13px;outline:none}
.ix-ctl select:hover{border-color:#c6cbd4}
.ix-seg{display:inline-flex;background:#eef0f3;border-radius:8px;padding:2px}
.ix-seg button{border:none;background:transparent;font-size:12px;padding:6px 12px;cursor:pointer;color:#5f6672;border-radius:6px}
.ix-seg button.on{background:#fff;color:#111827;font-weight:600;box-shadow:0 1px 2px rgba(16,24,40,.08)}
.ix-sentence{font-size:17px;line-height:1.75;color:#111827;margin-bottom:18px;letter-spacing:-.01em}
.ix-sentence b{color:#4f46e5}
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
</style>"""
    markup="""<div class="ix">
<div class="ix-sentence" id="ix_sentence"></div>
<div class="ix-kpi" id="ix_kpi"></div>
<div class="ix-tabs">
<button class="ix-tab on" data-t="A">A · 跨行比較</button>
<button class="ix-tab" data-t="B">B · 時間趨勢</button>
<button class="ix-tab" data-t="D">D · 增減(Δ)</button>
<button class="ix-tab" data-t="C">C · 自由探索</button></div>
<label class="ix-cptog"><input type="checkbox" id="ix_cp"> 含貨幣市場(CP／短期票券) — 看「總部位規模」勾選;看「純債券配置」不勾</label>
<div id="ixA">
<div class="ix-ctl"><label>期間</label><select id="A_p"></select><label>分類</label><select id="A_c"><option value="合計">三分類合計</option><option value="Trading">Trading</option><option value="OCI" selected>OCI</option><option value="AC">AC</option></select><label>檢視</label><span class="ix-seg"><button id="A_amt" class="on">金額(億)</button><button id="A_pct">結構(%)</button></span></div>
<div class="ix-legend" id="A_lg"></div><div id="A_bars"></div></div>
<div id="ixB" style="display:none">
<div class="ix-ctl"><label>分類</label><select id="B_c"><option value="合計">三分類合計</option><option value="Trading">Trading</option><option value="OCI" selected>OCI</option><option value="AC">AC</option></select><label>債種</label><select id="B_b"><option value="合計">全部債種</option><option value="GB">政府公債</option><option value="公司債">公司債</option><option value="金融債">金融債</option></select></div>
<div class="ix-legend" id="B_lg"></div><div style="position:relative;width:100%;height:320px"><canvas id="B_cv" role="img" aria-label="五家銀行債券部位時間趨勢"></canvas></div></div>
<div id="ixD" style="display:none">
<div class="ix-ctl"><label>期間</label><select id="D_p"></select><label>對比</label><select id="D_base"><option value="1">較上期(半年)</option><option value="2" selected>較去年同期</option></select><label>分類</label><select id="D_c"><option value="合計">三分類合計</option><option value="Trading">Trading</option><option value="OCI" selected>OCI</option><option value="AC">AC</option></select></div>
<div class="ix-legend"><span><span class="ix-sw" style="background:#1baf7a"></span>加碼(增)</span><span><span class="ix-sw" style="background:#e34948"></span>減碼(減)</span></div>
<div id="D_bars"></div></div>
<div id="ixC" style="display:none">
<div class="ix-ctl"><label>期間</label><select id="C_p"></select><label>分類</label><select id="C_c"><option value="合計">三分類合計</option><option value="Trading">Trading</option><option value="OCI" selected>OCI</option><option value="AC">AC</option></select></div>
<div id="C_grid"></div></div>
<div class="ix-legend" style="margin-top:14px;border-top:1px solid #e5e5e5;padding-top:10px">
<span><span class="ix-sw" style="background:#f0f0f0;border:1px solid #ccc"></span>0 = 真實零部位</span>
<span><span class="ix-sw ix-hatch"></span>無資料(當期財報為掃描影像檔)</span></div></div>"""
    js=r"""
const BANKS=RAW.banks,PERIODS=RAW.periods,W=RAW.wide;
const BONDS3=[["GB","政府公債","#2a78d6"],["公司債","公司債","#1baf7a"],["金融債","金融債","#eda100"]];
const CPBOND=["CP","貨幣市場(CP)","#888780"];
const CATS=["Trading","OCI","AC"],SC=["#2a78d6","#1baf7a","#eda100","#4a3aa7","#008300"];
let incCP=false;
function bondList(){return incCP?[CPBOND,...BONDS3]:BONDS3;}
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
["A_p","C_p","D_p"].forEach(id=>fillSel(id,latestP()));
function lgHTML(items){return items.map(i=>'<span><span class="ix-sw" style="background:'+i[2]+'"></span>'+i[1]+'</span>').join("");}

function drawKPI(){
  const p=latestP(),cat="合計";
  const rows=BANKS.filter(b=>has(p,b)).map(b=>({b,t:total(p,b,cat)}));
  const sum=rows.reduce((s,r)=>s+r.t,0),top=rows.reduce((a,b)=>b.t>a.t?b:a);
  const yp=prevP(p,2);
  const dts=yp?BANKS.filter(b=>has(p,b)&&has(yp,b)).map(b=>({b,d:total(p,b,cat)-total(yp,b,cat)})):[];
  const up=dts.length?dts.reduce((a,b)=>b.d>a.d?b:a):null,dn=dts.length?dts.reduce((a,b)=>b.d<a.d?b:a):null;
  const scope=incCP?"總部位(含CP)":"純債券";
  document.getElementById("ix_sentence").innerHTML="<b>"+p+"</b> "+scope+":五家合計 <b>"+fmt(sum)+"</b> 億;<b>"+top.b+"</b> 部位最大("+fmt(top.t)+"億)"+(up?"。較去年同期,<b>"+up.b+"</b> 加碼最多("+sgn(up.d)+"億)、<b>"+dn.b+"</b> 減碼最多("+sgn(dn.d)+"億)":"")+"。";
  const cards=[["本期五家合計",fmt(sum)+" 億",scope+" · "+p],["部位最大",top.b,fmt(top.t)+" 億"]];
  if(up)cards.push(["加碼最多(YoY)",up.b,sgn(up.d)+" 億"]);
  if(dn)cards.push(["減碼最多(YoY)",dn.b,sgn(dn.d)+" 億"]);
  document.getElementById("ix_kpi").innerHTML=cards.map(c=>'<div class="ix-kcard"><div class="ix-klabel">'+c[0]+'</div><div class="ix-kval">'+c[1]+'</div><div class="ix-ksub">'+c[2]+'</div></div>').join("");
}
document.querySelectorAll(".ix-tab").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".ix-tab").forEach(x=>x.classList.remove("on"));b.classList.add("on");
  ["A","B","C","D"].forEach(t=>document.getElementById("ix"+t).style.display=(t===b.dataset.t)?"":"none");
  if(b.dataset.t==="B")drawB();});
document.getElementById("ix_cp").onchange=e=>{incCP=e.target.checked;drawKPI();drawA();drawC();drawD();if(document.getElementById("ixB").style.display!=="none")drawB();};

let A_mode="amt";
function drawA(){
  const p=A_p.value,cat=A_c.value,BD=bondList();
  document.getElementById("A_lg").innerHTML=lgHTML(BD);
  const rows=BANKS.map(bk=>({bk,ok:has(p,bk),segs:BD.map(bd=>val(p,bk,cat,bd[0])),tot:total(p,bk,cat)}));
  const mx=Math.max(...rows.map(r=>r.tot),1);
  document.getElementById("A_bars").innerHTML=rows.map(r=>{
    if(!r.ok)return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div class="ix-na">無資料 · 該期財報為掃描影像檔</div><div class="ix-tot">N/A</div></div>';
    const base=A_mode==="pct"?(r.tot||1):mx,wp=A_mode==="pct"?100:(r.tot/mx*100);
    const inner=BD.map((bd,i)=>{const v=r.segs[i];return v<=0?"":'<div class="ix-s2" style="width:'+(v/base*100)+'%;background:'+bd[2]+'" title="'+bd[1]+' '+fmt(v)+'億"></div>';}).join("");
    const lab=A_mode==="pct"?(r.tot?"100%":"0"):fmt(r.tot);
    return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div class="ix-track" style="width:'+Math.max(wp,0.5)+'%">'+inner+'</div><div class="ix-tot">'+lab+'</div></div>';
  }).join("");
}
["A_p","A_c"].forEach(id=>document.getElementById(id).onchange=drawA);
A_amt.onclick=()=>{A_mode="amt";A_amt.classList.add("on");A_pct.classList.remove("on");drawA();};
A_pct.onclick=()=>{A_mode="pct";A_pct.classList.add("on");A_amt.classList.remove("on");drawA();};

function drawD(){
  const p=D_p.value,step=+D_base.value,cat=D_c.value,bp=prevP(p,step);
  const bl=step===2?"去年同期":"上期";
  const rows=BANKS.map(bk=>{const ok=has(p,bk)&&bp&&has(bp,bk);return {bk,ok,d:ok?total(p,bk,cat)-total(bp,bk,cat):0};});
  const mx=Math.max(...rows.map(r=>Math.abs(r.d)),1);
  document.getElementById("D_bars").innerHTML='<div style="font-size:12px;color:#999;margin-bottom:10px">'+p+' 較 '+(bp||"—")+'('+bl+')的部位增減,單位億元。</div>'+rows.map(r=>{
    if(!r.ok)return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div class="ix-na">無可對比資料</div><div class="ix-tot"></div></div>';
    const w=Math.abs(r.d)/mx*50,pos=r.d>=0;
    const bar=pos?'<div style="width:50%"></div><div style="width:'+w+'%;height:22px;background:#1baf7a;border-radius:0 3px 3px 0"></div>':'<div style="width:'+(50-w)+'%"></div><div style="width:'+w+'%;height:22px;background:#e34948;border-radius:3px 0 0 3px"></div><div style="width:50%"></div>';
    return '<div class="ix-row"><div class="ix-name">'+r.bk+'</div><div style="flex:1;display:flex;align-items:center;border-left:1px solid #ddd">'+bar+'</div><div class="ix-tot" style="color:'+(pos?"#0f6e56":"#a32d2d")+'">'+sgn(r.d)+'</div></div>';
  }).join("");
}
["D_p","D_base","D_c"].forEach(id=>document.getElementById(id).onchange=drawD);

function drawC(){
  const p=C_p.value,cat=C_c.value,BD=bondList();
  let mx=1;BANKS.forEach(bk=>{if(has(p,bk))BD.forEach(bd=>{const v=val(p,bk,cat,bd[0]);if(v>mx)mx=v;});});
  let h='<div style="font-size:12px;color:#999;margin-bottom:8px">色深=部位規模(億元)。</div><div style="display:grid;grid-template-columns:40px repeat('+BD.length+',1fr);gap:4px">';
  h+='<div></div>'+BD.map(bd=>'<div style="font-size:12px;color:#666;text-align:center;padding-bottom:2px">'+bd[1]+'</div>').join("");
  BANKS.forEach(bk=>{
    h+='<div style="font-size:13px;display:flex;align-items:center;justify-content:flex-end;padding-right:4px">'+bk+'</div>';
    if(!has(p,bk)){h+='<div style="grid-column:span '+BD.length+';height:52px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#999;background:repeating-linear-gradient(45deg,#f5f6f5,#f5f6f5 5px,rgba(150,150,150,.25) 5px,rgba(150,150,150,.25) 7px)">無資料(掃描影像檔)</div>';return;}
    BD.forEach(bd=>{const v=val(p,bk,cat,bd[0]),t=v/mx;const bg=v<=0?"#f0f0f0":"rgba(42,120,214,"+(0.12+t*0.8).toFixed(2)+")",col=t>0.45?"#fff":"#222";
      h+='<div style="background:'+bg+';border-radius:6px;height:52px;display:flex;align-items:center;justify-content:center;font-size:13px;color:'+col+'">'+(v>0?fmt(v):"0")+'</div>';});
  });
  document.getElementById("C_grid").innerHTML=h+'</div>';
}
["C_p","C_c"].forEach(id=>document.getElementById(id).onchange=drawC);

let chartB=null;
function drawB(){
  const cat=B_c.value,bond=B_b.value,dash=[[],[6,4],[2,3],[8,3,2,3],[]];
  const withCP=incCP&&(bond==="合計");
  const ds=BANKS.map((bk,i)=>({label:bk,data:PERIODS.map(p=>{if(!has(p,bk))return null;return bond==="合計"?total(p,bk,cat):val(p,bk,cat,bond);}),borderColor:SC[i],backgroundColor:SC[i],borderDash:dash[i],spanGaps:false,borderWidth:2,tension:0.25,pointRadius:2,pointHoverRadius:5}));
  document.getElementById("B_lg").innerHTML=BANKS.map((bk,i)=>'<span><span class="ix-sw" style="background:'+SC[i]+'"></span>'+bk+'</span>').join("")+(withCP?' <span style="color:#999">(已含CP)</span>':'');
  if(chartB)chartB.destroy();
  chartB=new Chart(document.getElementById("B_cv"),{type:"line",data:{labels:PERIODS,datasets:ds},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.dataset.label+": "+fmt(c.parsed.y)+"億"}}},scales:{y:{title:{display:true,text:"億元"}},x:{grid:{display:false},ticks:{maxRotation:45,autoSkip:false}}}}});
}
["B_c","B_b"].forEach(id=>document.getElementById(id).onchange=drawB);
drawKPI();drawA();drawC();drawD();
"""
    return ('<div class="card"><h2>互動儀表板(可切換期間 / 分類 / 債種)</h2>'
            + css + markup
            + '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
            + '<script>const RAW=' + payload + ';\n' + js + '</script></div>')

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
header{{background:#fff;border-bottom:1px solid var(--line);padding:18px 28px;position:sticky;top:0;z-index:10}}
header h1{{margin:0;font-size:16px;font-weight:600;letter-spacing:-.01em}}
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
.tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px}}
table.wide{{border-collapse:collapse;font-size:12px;white-space:nowrap;width:100%}}
table.wide th,table.wide td{{border-bottom:1px solid var(--line);padding:6px 10px;text-align:right}}
table.wide thead th{{background:#f8f9fb;color:var(--sub);font-weight:600;text-align:center;position:sticky;top:0}}
table.wide th.rowh{{background:#f8f9fb;text-align:left;position:sticky;left:0;z-index:1;color:var(--ink);font-weight:500}}
table.wide tbody tr:hover td{{background:#fafbfc}}
@media print{{header{{position:static}}.card{{box-shadow:none;break-inside:avoid}}details.card{{display:none}}}}
</style></head><body>
<header><h1>銀行五家 · 債券投資債種分析</h1>
<p>國泰 5835 / 富邦 5836 / 中信 5841 / 兆豐 5843 / 玉山 5847 · 個體財報 · 公開資訊觀測站 · 更新 {now}</p></header>
<div class="wrap">
{interactive_html()}
<details class="card"><summary>靜態總覽圖(列印/貼信件用)</summary><div class="inner">
<h2 style="margin-top:4px">按會計分類 (Trading / OCI / AC)</h2><img src="圖1.png" alt="按分類">
<h2 style="margin-top:20px">按債種 (公債 / 信用債 / 公司債 / 金融債 / 其他)</h2><img src="圖2.png" alt="按債種">
</div></details>
{wide_table_html()}
<div class="card note">
<b style="color:var(--ink)">說明</b><br>
· 單位:億元。靜態圖 x 軸=五家銀行、每家一色、時間序列(顯示 {SHOW[0]}–{SHOW[-1]})。<br>
· <b>兆豐</b>債種明細來自其財報「證券部門變動明細表」(排版與他家不同);其證券部門無 Trading 部位,故 Trading 列為 0。<br>
· 2020H1 國泰/玉山之個體財報為掃描影像檔,無法解析,標為「無資料」。<br>
· 數據經三層 checksum 驗算;完整方法與腳本見 repo。本頁由 GitHub Actions 自動更新。
</div></div></body></html>"""
(SITE/"index.html").write_text(html, encoding="utf-8")
print("已產生 site/ (index.html + 圖1/圖2.png + xlsx)")
