"""★ 一鍵主程式:解析五家全期間 → 產出含【原生 Excel 圖表】的報表。
   python3 build_report.py            # 用現有快取
   python3 build_report.py --refresh  # 明年新報表:先自動補抓當期個體檔再產出

輸出 銀行債券_完整報表.xlsx:寬表(全期間) + 資料表 + 兩張原生圖儀表板(版面同參考圖)。
圖表可調參數見下方 CONFIG。
"""
import sys, pdfplumber
from pathlib import Path
import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import openpyxl.utils as XU
import extract3 as E

# ===================== CONFIG(想調圖就改這裡)=====================
GAP_WIDTH   = 20        # 長條群間距(越小越擠;參考圖約 20~40)
CHART_W, CHART_H = 11, 6.5
# 圖表只顯示這些期間(避免太密);寬表仍保留全部。改這行即可增減。
SHOW_PERIODS = ["2022H1","2022H2","2023H1","2023H2","2024H1","2024H2"]
# ================================================================

CACHE=Path("pdf_cache"); OUT="銀行債券_完整報表.xlsx"
BANKS=[("5841","中信"),("5843","兆豐"),("5835","國泰"),("5836","富邦"),("5847","玉山")]
ALL_PERIODS=[(roc,mth) for roc in range(109,114) for mth in ("02","04")]
COLOR={"中信":"4a5e2a","兆豐":"8a8a3a","國泰":"e8c020","富邦":"3a8fd0","玉山":"8bc34a"}
def plabel(roc,mth): return f"{1911+roc}{'H1' if mth=='02' else 'H2'}"

# ---------- 解析 ----------
def parse_all():
    if "--refresh" in sys.argv:
        import resolve
        for roc,mth in ALL_PERIODS:
            for code,_ in BANKS:
                if code!="5843": resolve.download(code,roc,mth)
    rec={}
    for roc,mth in ALL_PERIODS:
        lbl=plabel(roc,mth)
        for code,name in BANKS:
            p=CACHE/f"{1911+roc}{mth}_{code}_AI3.pdf"
            if name=="兆豐" or not p.exists() or p.stat().st_size<100000:
                rec[(lbl,name)]=None; continue
            t="\n".join((pg.extract_text() or "") for pg in pdfplumber.open(p).pages)
            items={c:E.parse_class(t,c) for c in ("Trading","OCI","AC")}
            r={c:E.bond_buckets(items[c]) for c in ("Trading","OCI","AC")}
            r["_cp"]=items["Trading"].get("商業本票",0)/1e5
            rec[(lbl,name)]=r
    return rec

# ---------- 指標 ----------
def mv(b): return b["公債"]+b["公司債"]+b["金融債"]+b["資產基礎"]+b["國庫券"]+b["可轉讓定存單"]+b["其他"]
def tot(r): return sum(mv(r[c]) for c in ("Trading","OCI","AC"))
def clsmv(c): return lambda r: mv(r[c])
def clspct(c): return lambda r: (mv(r[c])/tot(r) if tot(r) else 0)
def typ(k): return lambda r: sum(r[c][k] for c in ("Trading","OCI","AC"))
def credit(r): return sum(r[c]["公司債"]+r[c]["金融債"] for c in ("Trading","OCI","AC"))
def typpct(k): return lambda r: (typ(k)(r)/tot(r) if tot(r) else 0)
otherbond=lambda r: typ("資產基礎")(r)+typ("其他")(r)+typ("國庫券")(r)+typ("可轉讓定存單")(r)

DASH1=[("債券MV合計",tot,0),("Trading MV",clsmv("Trading"),0),("OCI MV",clsmv("OCI"),0),("AC MV",clsmv("AC"),0),
       ("Trading比重",clspct("Trading"),1),("OCI比重",clspct("OCI"),1),("AC比重",clspct("AC"),1)]
DASH2=[("債券MV合計",tot,0),("公債MV",typ("公債"),0),("信用債MV",credit,0),("金融債MV",typ("金融債"),0),
       ("公司債MV",typ("公司債"),0),("其他債MV",otherbond,0),("公債比重",typpct("公債"),1),
       ("信用債比重",lambda r:(credit(r)/tot(r) if tot(r) else 0),1)]

# ---------- 原生圖表(列=銀行、欄=期間、每家一色) ----------
def write_block(ws, top, title, fn, pct, rec):
    ws.cell(top,1,title).font=Font(bold=True); hr=top+1
    ws.cell(hr,1,"銀行").font=Font(bold=True)
    for j,per in enumerate(SHOW_PERIODS): ws.cell(hr,2+j,per).font=Font(bold=True)
    for i,(_,bn) in enumerate(BANKS):
        r=hr+1+i; ws.cell(r,1,bn).font=Font(bold=True)
        for j,per in enumerate(SHOW_PERIODS):
            rb=rec.get((per,bn)); v=None if rb is None else fn(rb)
            c=ws.cell(r,2+j, None if v is None else round(v,4 if pct else 1))
            c.number_format="0%" if pct else "#,##0"
    return hr, hr+len(BANKS)

def add_chart(wsd, hr, last, title, pct, anchor, wsc):
    ch=BarChart(); ch.type="col"; ch.grouping="clustered"; ch.title=title
    ch.height=CHART_H; ch.width=CHART_W; ch.gapWidth=GAP_WIDTH
    data=Reference(wsd,min_col=2,max_col=1+len(SHOW_PERIODS),min_row=hr,max_row=last)
    cats=Reference(wsd,min_col=1,min_row=hr+1,max_row=last)
    ch.add_data(data,titles_from_data=True); ch.set_categories(cats)
    for s in ch.series:                       # 每序列的第 i 點染成第 i 家色
        for i,(_,bn) in enumerate(BANKS):
            dp=DataPoint(idx=i); dp.graphicalProperties=GraphicalProperties(solidFill=COLOR[bn])
            s.data_points.append(dp)
    ch.legend=None
    ch.x_axis.title="銀行"; ch.y_axis.title=("占比" if pct else "億元")
    ch.x_axis.delete=False; ch.y_axis.delete=False
    if pct: ch.y_axis.numFmt="0%"
    wsc.add_chart(ch, anchor)

# ---------- 寬表 ----------
def wide_sheet(ws, rec):
    green=PatternFill("solid",fgColor="2E5B4E"); white=Font(bold=True,color="FFFFFF",size=10)
    cen=Alignment(horizontal="center"); thin=Side(style="thin",color="CCCCCC"); bd=Border(thin,thin,thin,thin)
    METRICS=["Trading_CP+NCD+BA","Trading_GB","Trading_公司債","Trading_金融債","OCI_GB","OCI_公司債","OCI_金融債","AC_GB","AC_公司債","AC_金融債"]
    def metric(rbk,m):
        if rbk is None: return None
        cls,tp=m.split("_",1); b=rbk[cls]
        if tp=="CP+NCD+BA": return rbk["_cp"]+b["國庫券"]+b["可轉讓定存單"]
        return {"GB":b["公債"],"公司債":b["公司債"],"金融債":b["金融債"]}.get(tp)
    plabels=[plabel(r,m) for r,m in ALL_PERIODS]; banks=[n for _,n in BANKS]; nb=len(banks)
    ws.cell(1,1,"(億元)").font=white; ws.cell(1,1).fill=green
    ws.cell(2,1,"銀行合併").font=white; ws.cell(2,1).fill=green
    for pi,pl in enumerate(plabels):
        c0=2+pi*nb; ws.merge_cells(start_row=1,start_column=c0,end_row=1,end_column=c0+nb-1)
        h=ws.cell(1,c0,pl); h.font=white; h.fill=green; h.alignment=cen
        for bi,bn in enumerate(banks):
            hc=ws.cell(2,c0+bi,bn); hc.font=white; hc.fill=green; hc.alignment=cen
    for ri,mn in enumerate(METRICS):
        r=3+ri; ws.cell(r,1,mn).font=Font(bold=True,size=10)
        for pi,pl in enumerate(plabels):
            for bi,bn in enumerate(banks):
                v=metric(rec.get((pl,bn)),mn); c0=2+pi*nb+bi
                cc=ws.cell(r,c0,"" if v is None else round(v)); cc.alignment=Alignment(horizontal="right"); cc.border=bd; cc.number_format="#,##0"
    ws.freeze_panes="B3"; ws.column_dimensions["A"].width=18
    for c in range(2,2+len(plabels)*nb): ws.column_dimensions[XU.get_column_letter(c)].width=6

# ---------- 組裝 ----------
def build(rec):
    wb=openpyxl.Workbook(); wide_sheet(wb.active,rec); wb.active.title="寬表"
    for dash,specs in [("圖-按分類",DASH1),("圖-按債種",DASH2)]:
        wsd=wb.create_sheet(f"資料_{dash[-3:]}"); wsc=wb.create_sheet(dash); top=1
        for idx,(title,fn,pct) in enumerate(specs):
            hr,last=write_block(wsd,top,title,fn,pct,rec)
            col="A" if idx%2==0 else "L"; row=1+(idx//2)*14
            add_chart(wsd,hr,last,title,pct,f"{col}{row}",wsc); top=last+3
        wsd.column_dimensions["A"].width=8
    wb.save(OUT)

WIDE_METRICS=["Trading_CP+NCD+BA","Trading_GB","Trading_公司債","Trading_金融債",
              "OCI_GB","OCI_公司債","OCI_金融債","AC_GB","AC_公司債","AC_金融債"]
def wide_metric(r, m):
    if r is None: return None
    cls,tp=m.split("_",1); b=r[cls]
    if tp=="CP+NCD+BA": return round(r["_cp"]+b["國庫券"]+b["可轉讓定存單"])
    return round({"GB":b["公債"],"公司債":b["公司債"],"金融債":b["金融債"]}[tp])

def dump_json(rec, path="data.json"):
    import json
    out={"periods":[plabel(r,m) for r,m in ALL_PERIODS],"banks":[n for _,n in BANKS],
         "wide_metrics":WIDE_METRICS,"data":{},"wide":{}}
    for (lbl,name),r in rec.items():
        k=f"{lbl}|{name}"
        out["data"][k]= None if r is None else {c:{x:r[c][x] for x in ("公債","公司債","金融債","其他")} for c in ("Trading","OCI","AC")}
        out["wide"][k]= None if r is None else {m:wide_metric(r,m) for m in WIDE_METRICS}
    json.dump(out, open(path,"w"), ensure_ascii=False)

if __name__=="__main__":
    rec=parse_all(); build(rec); dump_json(rec)
    print("完成 →",OUT,"+ data.json | 圖表期間:",SHOW_PERIODS)
