# -*- coding: utf-8 -*-
"""抽 附註「金融工具之公允價值」的 AC 那一行:帳面價值 vs 公允價值。

不是投資明細表 —— 那裡的『總額/總面額』是面額(總額+未攤銷溢折價−備抵損失=帳面金額)。

三家印法各不相同,所以認**版面**不認字串:
  · 頁面同時出現「帳面價值」與「公允價值」,且有「攤銷後成本」
  · 該列開頭是攤銷後成本科目,後面**剛好兩個**大數字
兩個數字這條同時把公允價值**等級**表擋掉 —— 那張是「合計 第一等級 第二等級 第三等級」,
四個數字,抓進來會得到 −27% 這種假浮虧(前一版就是這樣汙染的)。

兆豐把 AC 拆成「債券投資」與「央行定期存單及短期票券」,只揭露前者 ——
那正好就是有久期的那段,不必自己扣。
"""
import re, os, json
import pdfplumber

BK = {"5841": "中信", "5843": "兆豐", "5835": "國泰", "5836": "富邦", "5847": "玉山"}
BIG = re.compile(r'[\d,]{9,}')
HEAD = re.compile(r'攤銷後成本衡量之(金融資產|債務工具)')

out = {}
docs = [f"{y}04_{c}_AI3" for y in [2021, 2022, 2023, 2024, 2025] for c in BK]
for n, doc in enumerate(docs, 1):
    fp = f"pdf_cache/{doc}.pdf"
    if not os.path.exists(fp):
        continue
    print(f"[{n}/{len(docs)}] {doc}", flush=True)
    try:
        pdf = pdfplumber.open(fp)
    except Exception as e:
        print("   開檔失敗", e, flush=True); continue
    got = []
    for i, pg in enumerate(pdf.pages):
        t = pg.extract_text() or ''
        if '帳面價值' not in t or '公允價值' not in t or '攤銷後成本' not in t:
            continue
        if '證券部門' in t or '人壽' in t:
            continue
        for ln in t.split('\n'):
            if not HEAD.search(ln):
                continue
            nums = [int(x.replace(',', '')) for x in BIG.findall(ln)]
            nums = [v for v in nums if v > 1_000_000]
            if len(nums) != 2:                      # 3+ = 等級表,擋掉
                continue
            got.append([i + 1, ln.strip()[:40], nums[0], nums[1]])
    pdf.close()
    if got:
        out[doc] = got
        for p, name, a, b in got:
            print(f"   p{p}  {name}  帳面 {a:,}  公允 {b:,}  ({(b/a-1)*100:+.2f}%)", flush=True)
    else:
        print("   ✗ 沒抓到", flush=True)
json.dump(out, open('scratchpad/ac_fv.json', 'w'), ensure_ascii=False, indent=1)
print("完成", len(out), "份", flush=True)
