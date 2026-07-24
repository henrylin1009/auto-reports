import importlib, schema, unified; importlib.reload(schema)
import unified as U, schema as S
banks={"中信":"5841","兆豐":"5843","國泰":"5835","富邦":"5836","玉山":"5847"}
periods=["202002","202004","202102","202104","202202","202204","202302","202304"]
plabel={"02":"H1","04":"H2"}
out=[]
for p in periods:
    yr=p[:4]; h=plabel[p[4:]]
    for bn,code in banks.items():
        path=f"pdf_cache/{p}_{code}_AI3.pdf"
        for cls in ("OCI","AC"):
            try:
                r=U.extract(path,cls)
                ok = "✅" if r else "❌N/A"
            except Exception as e:
                ok=f"ERR:{type(e).__name__}"
            out.append(f"{yr}{h} {bn} {cls}: {ok}")
    U._CACHE.clear()
print("\n".join(out))
# 統計
g=sum(1 for x in out if "✅" in x); print(f"\n=== OCI/AC 過對帳: {g}/{len(out)} ===")
for x in out:
    if "✅" not in x: print("  ",x)
