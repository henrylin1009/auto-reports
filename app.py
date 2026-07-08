"""雙擊執行的入口:抓最新財報 → 產出 銀行債券_完整報表.xlsx(含圖表)。
打包成 .exe 給非技術使用者(mentor)在 Windows 雙擊即可。
"""
import sys, os, traceback

# 讓輸出檔產在 exe(或腳本)所在資料夾
base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
os.chdir(base)

print("=" * 44)
print("   銀行五家 債券投資報表 產生器")
print("=" * 44)
print("\n正在抓最新財報並計算(約 2-3 分鐘,需連網)...\n")

try:
    sys.argv = ["app", "--refresh"]          # 讓 parse_all 會上網補抓當期檔
    import build_report
    rec = build_report.parse_all()
    build_report.build(rec)
    build_report.dump_json(rec)
    n = sum(1 for v in rec.values() if v)
    print(f"\n✅ 完成!已產生:銀行債券_完整報表.xlsx")
    print(f"   ({n} 筆銀行×期間資料,就在這個資料夾裡)")
except Exception:
    print("\n❌ 產生失敗,請把下面訊息截圖給冠亨:\n")
    traceback.print_exc()

input("\n按 Enter 關閉視窗...")
