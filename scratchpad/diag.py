import pdfplumber, re, schema as S
p='pdf_cache/202104_5836_AI3.pdf'
lab=S.ANCHOR_BS['OCI']; code='12100'
with pdfplumber.open(p) as pdf:
  for i,pg in enumerate(pdf.pages):
    t=pg.extract_text() or ''
    flat=t.replace(' ','')
    if '資產負債表' not in flat: continue
    pos=flat.find(lab)
    src='label'
    if pos<0:
      pos=flat.find(code+'透過'); src='code透過'
      if pos<0: pos=flat.find(code+'按'); src='code按'
    if pos<0: continue
    seg=flat[pos:pos+140]
    m=re.search(r'\d{1,3}(?:,\d{3})+',seg)
    print('頁',i,'定位來源=',src)
    print('片段=',seg[:120])
    print('抓到=',m.group() if m else None)
    break
