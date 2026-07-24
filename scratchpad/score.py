import unified as U, json
oracle=json.load(open('scratchpad/oracle.json'))
P={'2022H1':'202202','2022H2':'202204','2023H1':'202302','2023H2':'202304','2024H1':'202402','2024H2':'202404','2025H1':'202502','2025H2':'202504'}
BK={'中信':'5841','兆豐':'5843','國泰':'5835','富邦':'5836','玉山':'5847'}
good=tot=0; miss=[]
for per,fn in P.items():
    for b,c in BK.items():
        exp=oracle.get(per+'|'+b)
        for cls in ('Trading','OCI','AC'):
            got=U.extract(f'pdf_cache/{fn}_{c}_AI3.pdf',cls)
            ks=['公債','公司債','金融債']
            gs={k:round(got.get(k,0),1) for k in ks} if got else None
            es={k:round(exp[cls].get(k,0),1) for k in ks} if exp else None
            # 現行空(gap)不算 miss
            gap = es in (None,{'公債':0.0,'公司債':0.0,'金融債':0.0})
            tot+=1
            if gs==es: good+=1
            elif gap and gs: good+=1  # 填空算好
            else: miss.append(f'{per} {b} {cls}: uni={gs} exp={es}')
    print(per,'done',flush=True)
print(f'=== {good}/{tot} 綠(含填空) ===')
for m in miss: print(' X',m)
