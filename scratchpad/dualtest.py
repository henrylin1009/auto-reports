import universal as U
r=U.auto_extract_dual("pdf_cache/202404_5843_AI3.pdf","OCI")
print("兆豐 OCI 雙值(億):")
for b in list(U.S.BUCKETS)+["股票"]:
    d=r[b]
    if d["帳面"] or d["公允"]:
        print(f"  {b:8} 帳面={d['帳面']}  公允={d['公允']}")
print("帳面:",r['_book'])
print("公允:",r['_fair'])
