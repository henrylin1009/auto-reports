import universal as U
p='pdf_cache/202104_5836_AI3.pdf'
for cls in ['OCI','AC','Trading']:
    c=U.candidates(p,cls)
    pages=[i for i,_ in c]
    print(f'{cls}: {len(pages)}頁 {pages}  {"含149明細表" if 149 in pages else "已排除149明細表"}')
