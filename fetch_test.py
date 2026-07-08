"""診斷 v2:細看兩段式下載卡在哪一步。"""
import re, requests, resolve
BASE="https://doc.twse.com.tw"
print("出口 IP:", end=" ")
try: print(requests.get("https://api.ipify.org", timeout=15).text)
except Exception as e: print("?", e)

s=resolve._sess()
# step1: 清單
html=resolve.list_year("5841",113)
fn=resolve.indiv_filename(html,"202402")
print("清單找到個體檔:", fn)

# step2: POST step=9 取臨時連結
print("\n--- POST step=9 ---")
r=s.post(f"{BASE}/server-java/t57sb01",
    data={"step":"9","kind":"A","co_id":"5841","filename":fn,"colorchg":"1"},timeout=30)
r.encoding="big5"
print("HTTP:", r.status_code, "| 長度:", len(r.text))
print("回應前300字:", r.text[:300].replace("\n"," "))
mm=re.search(r"href='(/pdf/[^']+\.pdf)'", r.text)
print("找到 /pdf/ 連結:", mm.group(1) if mm else "✗ 沒有")

# step3: 抓實體 PDF
if mm:
    print("\n--- GET 實體 PDF ---")
    pr=s.get(BASE+mm.group(1),timeout=60)
    print("HTTP:", pr.status_code, "| bytes:", len(pr.content), "| 前16位元組:", pr.content[:16])
