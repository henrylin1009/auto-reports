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
SHOW=["2022H1","2022H2","2023H1","2023H2","2024H1","2024H2"]

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
for f in ["銀行債券_完整報表.xlsx"]:
    if Path(f).exists(): shutil.copy(f, SITE/f)

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

now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
html=f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>銀行債券投資 債種分析</title>
<style>
body{{font-family:-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;margin:0;background:#f5f6f5;color:#222}}
header{{background:#2e5b4e;color:#fff;padding:20px 24px}}
header h1{{margin:0;font-size:20px}} header p{{margin:6px 0 0;opacity:.85;font-size:13px}}
.wrap{{max-width:1200px;margin:0 auto;padding:20px}}
.dl{{display:inline-block;background:#2e5b4e;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:bold;margin:10px 0}}
.card{{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);padding:16px;margin:18px 0}}
.card h2{{margin:0 0 12px;font-size:16px;color:#2e5b4e}}
img{{width:100%;height:auto;border-radius:6px}}
.note{{font-size:13px;color:#666;line-height:1.7}}
.tblwrap{{overflow-x:auto}}
table.wide{{border-collapse:collapse;font-size:12px;white-space:nowrap}}
table.wide th,table.wide td{{border:1px solid #ddd;padding:4px 8px;text-align:right}}
table.wide thead th{{background:#2e5b4e;color:#fff;text-align:center;position:sticky;top:0}}
table.wide th.rowh{{background:#eef3f1;text-align:left;position:sticky;left:0;z-index:1}}
table.wide tbody tr:nth-child(even) td{{background:#fafafa}}
</style></head><body>
<header><h1>銀行五家 債券投資 債種分析</h1>
<p>國泰5835 / 富邦5836 / 中信5841 / 兆豐5843 / 玉山5847 · 個體財報 · 資料來源:公開資訊觀測站 · 最後更新:{now}</p></header>
<div class="wrap">
<a class="dl" href="銀行債券_完整報表.xlsx" download>⬇ 下載完整 Excel(寬表 + 原生圖表)</a>
<div class="card"><h2>按會計分類 (Trading / OCI / AC)</h2><img src="圖1.png" alt="按分類"></div>
<div class="card"><h2>按債種 (公債 / 信用債 / 公司債 / 金融債 / 其他)</h2><img src="圖2.png" alt="按債種"></div>
{wide_table_html()}
<div class="card note">
<b>說明</b><br>
· 單位:億元。x軸=五家銀行,每家一色、時間序列(顯示 {SHOW[0]}–{SHOW[-1]})。<br>
· <b>兆豐</b>整條留白:其財報未揭露債券債種明細(先天缺料)。<br>
· 數據經三層 checksum 驗算;完整方法與腳本見 repo。<br>
· 本頁由 GitHub Actions 自動更新。
</div></div></body></html>"""
(SITE/"index.html").write_text(html, encoding="utf-8")
print("已產生 site/ (index.html + 圖1/圖2.png + xlsx)")
