"""畫兩張儀表板 PNG,對應 image001(按分類)/ image002(按債種)。"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

# 中文字型
for path in ["/System/Library/Fonts/PingFang.ttc","/Library/Fonts/Arial Unicode.ttf",
             "/System/Library/Fonts/STHeiti Medium.ttc"]:
    try:
        fm.fontManager.addfont(path); plt.rcParams["font.family"]=fm.FontProperties(fname=path).get_name(); break
    except Exception: pass
plt.rcParams["axes.unicode_minus"]=False

D=json.load(open("data.json"))
PERIODS=D["periods"]; BANKS=D["banks"]; DATA=D["data"]
COLOR={"中信":"#4a5e2a","兆豐":"#8a8a3a","國泰":"#e8c020","富邦":"#3a8fd0","玉山":"#8bc34a"}

def val(bank,period,fn):
    r=DATA.get(f"{period}|{bank}")
    return None if r is None else fn(r)

def panel(ax, fn, title, pct=False):
    ax.set_title(title, fontsize=10, fontweight="bold")
    nb=len(BANKS); np_=len(PERIODS); w=0.8/np_
    for bi,bank in enumerate(BANKS):
        for pi,per in enumerate(PERIODS):
            v=val(bank,per,fn)
            if v is None: continue
            x=bi + (pi-np_/2)*w + w/2
            ax.bar(x, v, width=w*0.95, color=COLOR[bank], edgecolor="none")
    ax.set_xticks(range(nb)); ax.set_xticklabels(BANKS, fontsize=8)
    ax.grid(axis="y", color="#eee"); ax.set_axisbelow(True)
    if pct:
        ax.set_ylim(0,1); ax.yaxis.set_major_formatter(lambda y,_:f"{y*100:.0f}%")
    for s in ("top","right"): ax.spines[s].set_visible(False)

# 各種取值函式
cls_mv=lambda c: (lambda r: sum(r[c].values()))
tot_mv=lambda r: sum(sum(r[c].values()) for c in ("Trading","OCI","AC"))
cls_pct=lambda c: (lambda r: (sum(r[c].values())/tot_mv(r)) if tot_mv(r) else 0)
type_mv=lambda k: (lambda r: sum(r[c][k] for c in ("Trading","OCI","AC")))
credit_mv=lambda r: sum(r[c]["公司債"]+r[c]["金融債"] for c in ("Trading","OCI","AC"))
tot_bond=lambda r: sum(sum(r[c].values()) for c in ("Trading","OCI","AC"))
type_pct=lambda k: (lambda r: (type_mv(k)(r)/tot_bond(r)) if tot_bond(r) else 0)

# ---- 儀表板1:按分類 ----
fig,axes=plt.subplots(2,4,figsize=(18,8)); fig.suptitle("債券投資 — 按會計分類 (Trading/OCI/AC)  單位:億元",fontsize=13,fontweight="bold")
A=axes.flat
panel(next(A), tot_mv, "債券MV(合計)")
panel(next(A), cls_mv("Trading"), "Trading MV")
panel(next(A), cls_mv("OCI"), "OCI MV")
panel(next(A), cls_mv("AC"), "AC MV")
panel(next(A), cls_pct("Trading"), "Trading 比重", pct=True)
panel(next(A), cls_pct("OCI"), "OCI 比重", pct=True)
panel(next(A), cls_pct("AC"), "AC 比重", pct=True)
next(A).axis("off")
fig.tight_layout(rect=[0,0,1,0.96]); fig.savefig("圖1_按分類.png",dpi=110); plt.close(fig)

# ---- 儀表板2:按債種 ----
fig,axes=plt.subplots(2,4,figsize=(18,8)); fig.suptitle("債券投資 — 按債種 (公債/信用債/公司債/金融債/其他)  單位:億元",fontsize=13,fontweight="bold")
A=axes.flat
panel(next(A), tot_bond, "債券MV(合計)")
panel(next(A), type_mv("公債"), "公債MV")
panel(next(A), credit_mv, "信用債MV(公司債+金融債)")
panel(next(A), type_mv("金融債"), "金融債MV")
panel(next(A), type_mv("公司債"), "公司債MV")
panel(next(A), type_mv("其他"), "其他債MV")
panel(next(A), type_pct("公債"), "公債比重", pct=True)
panel(next(A), lambda r:(credit_mv(r)/tot_bond(r) if tot_bond(r) else 0), "信用債比重", pct=True)
fig.tight_layout(rect=[0,0,1,0.96]); fig.savefig("圖2_按債種.png",dpi=110); plt.close(fig)
print("已輸出 圖1_按分類.png, 圖2_按債種.png")
