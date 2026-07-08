"""診斷:在執行環境測 TWSE 抓取是否可行(判斷 CI 被擋是 UA 還是 IP/地理)。"""
import resolve, requests
BASE="https://doc.twse.com.tw"
print("出口 IP:", end=" ")
try: print(requests.get("https://api.ipify.org", timeout=15).text)
except Exception as e: print("查不到", e)

print("\n[1] 抓 5841 民國113 清單 …")
try:
    html=resolve.list_year("5841",113)
    print("  回應長度:", len(html))
    print("  含『個體』:", "個體" in html)
    import re
    files=re.findall(r'readfile2\("A","5841","([^"]+)"\)', html)
    print("  找到檔案數:", len(files), files[:4])
except Exception as e:
    print("  ✗ 清單抓取失敗:", e)

print("\n[2] 實抓 5841 2024H1 個體 PDF …")
try:
    p=resolve.download("5841",113,"02")
    if p and p.stat().st_size>100000:
        print(f"  ✅ 成功!{p.name} = {p.stat().st_size:,} bytes  → 雲端可抓,能全自動")
    else:
        print("  ✗ 沒抓到檔(清單無個體檔或下載空)→ 可能 IP/地理封鎖")
except Exception as e:
    print("  ✗ 下載失敗:", e, "→ 可能 IP/地理封鎖")
