#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用『詞座標重組』抽兆豐 OCI/AC 主附註,對帳 override。
   不寫任何逐年規則:同一套 regroup + 桶對照 跑六期。"""
import pdfplumber, re, json

PERIODS = {  # period -> pdf file (年報)
    '2020H2':'202004','2021H2':'202104','2022H2':'202204',
    '2023H2':'202304','2024H2':'202404','2025H2':'202504',
}
SYN = [  # (桶, 關鍵字) 順序即優先序
    ('貨幣市場','央行定期存單'),('貨幣市場','央行定存單'),('貨幣市場','短期票券'),
    ('貨幣市場','國庫券'),('可轉讓定存單','銀行定期存單'),('可轉讓定存單','定存單'),
    ('金融債','金融債'),('公債','政府債'),('公債','政府公債'),
    ('資產基礎','資產基礎'),('資產基礎','證券化'),('資產基礎','受益證券'),
    ('公司債','公司債'),
]

def cells(words, gap=12):
    """把一列的詞依 x 間距切成『格』(品名 / 各年數字各成一格)。"""
    words=sorted(words)
    out=[]; cur=[words[0]]
    for (x,t) in words[1:]:
        if x-cur[-1][0] > gap:
            out.append(cur); cur=[(x,t)]
        else:
            cur.append((x,t))
    out.append(cur)
    return [''.join(t for _,t in c) for c in out]

def regroup(pg):
    rows={}
    for w in pg.extract_words():
        rows.setdefault(round(w['top']/3.0),[]).append((w['x0'],w['text']))
    return [(k, sorted(r)) for k,r in sorted(rows.items())]

def rowtext(r): return ''.join(t for _,t in r)

def first_num(r):
    # 取這列切格後『第一個數字格』= 當期(民國當年,年報中排最左)
    for cell in cells(r):
        raw=cell.replace('$','').replace(',','').replace('(','').replace(')','')
        if raw.isdigit() and len(raw)>=5:
            neg = '(' in cell
            return -int(raw) if neg else int(raw)
    return None

def bucket_of(name):
    n=name.replace(' ','')
    for b,kw in SYN:
        if kw in n: return b
    return None

def parse_table(block):
    """block = [(k,r)...]。抽 桶->值(仟元,取當期)。碰 小計/淨額 停(避免權益工具區)。"""
    out={}
    for _,r in block:
        txt=rowtext(r)
        if any(k in txt for k in ('小計','合計','淨額')):
            break
        b=bucket_of(txt)
        if not b: continue
        v=first_num(r)
        if v is None: continue
        out[b]=out.get(b,0)+v
    return out

def find_block(pdf, title_kw):
    """回傳含該分類 債務工具彙總 的重組列(從第一個債種列到第一個淨額/小計)。"""
    for i,pg in enumerate(pdf.pages):
        raw=pg.extract_text() or ''
        if title_kw not in raw: continue
        rows=regroup(pg)
        start=None
        for j,(k,r) in enumerate(rows):
            if bucket_of(rowtext(r)) and first_num(r) is not None:
                start=j; break
        if start is None: continue
        blk=[]
        for k,r in rows[start:]:
            blk.append((k,r))
            if '淨額' in rowtext(r) or '小計' in rowtext(r): break
        if blk: return i,blk
    return None,None

def main():
    ov=json.load(open('megabank_override.json'))['data']
    print(f"{'期別':<8}{'類':<4}{'桶':<12}{'重組直讀(億)':>14}{'override(億)':>14}  判定")
    print('-'*70)
    for per,fn in PERIODS.items():
        pdf=pdfplumber.open(f'pdf_cache/{fn}_5843_AI3.pdf')
        for cls,title in [('OCI','透過其他綜合損益按公允價值衡量之金融資產'),
                          ('AC','按攤銷後成本衡量之債務工具投資')]:
            _,blk=find_block(pdf,title)
            got=parse_table(blk) if blk else {}
            got={k:round(v/1e5,1) for k,v in got.items()}
            ovc={k:round(v,1) for k,v in ov[per][cls].items() if v}
            keys=sorted(set(got)|set(ovc))
            for k in keys:
                g=got.get(k); o=ovc.get(k)
                if g is None: mark='△ override有我沒抓'
                elif o is None: mark='○ 我有override沒'
                elif abs(g-o)<=max(3,abs(o)*0.03): mark='✅'
                else: mark=f'⚠️ 差{round((g or 0)-(o or 0),1)}'
                print(f"{per:<8}{cls:<4}{k:<12}{str(g):>14}{str(o):>14}  {mark}")
            print()

if __name__=='__main__':
    main()
