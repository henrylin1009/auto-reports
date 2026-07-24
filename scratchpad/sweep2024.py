import universal as U
banks={"中信":"5841","兆豐":"5843","國泰":"5835","富邦":"5836","玉山":"5847"}
for bn,code in banks.items():
    for cls in ("Trading","OCI","AC"):
        try:
            r=U.auto_extract(f"pdf_cache/202404_{code}_AI3.pdf",cls)
            if "_error" in r: print(f"{bn} {cls}: ERR {r['_error']}"); continue
            tag="✅" if (r.get("_pass") and r.get("_cross") in (True,None)) else "❌"
            b={k:v for k,v in r.items() if not k.startswith('_') and v}
            print(f"{tag} {bn} {cls} p{r.get('_page')} 對帳{r['_pass']}交叉{r['_cross']} 股={r['股票']} {b}")
        except Exception as e:
            print(f"{bn} {cls}: EXC {type(e).__name__} {e}")
