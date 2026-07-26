# -*- coding: utf-8 -*-
"""把新抄的一格併進 rows_v3.json,**先驗過才寫**。

    python3 scratchpad/add.py new.json          # 驗;過了才併
    python3 scratchpad/add.py new.json --dry    # 只驗不併

`new.json` 形狀 = `{"檔名|類別": [record, ...]}`,與 rows_v3.json 同構。

⚠️ 驗不過就**不寫**。抄列是手工的,寫進去再回頭找哪一格壞了很貴;而且
半驗過的資料混進 rows_v3.json 之後,下游每一個測試都會開始騙人。
"""
import json
import sys

sys.path.insert(0, ".")
import buckets
import locate
import transcribe

STORE = "scratchpad/rows_v3.json"


def check(key, recs):
    doc, _ = key.split("|")
    loc = locate.locate(f"pdf_cache/{doc}.pdf")
    ok = transcribe.report(recs, loc)
    bad = [r["name"] for rec in recs for r in rec["rows"]
           if not buckets.bucket(r) and not buckets.is_adj(r)]
    if bad:
        print(f"    ✗ 未涵蓋名字: {sorted(set(bad))}")
    return ok and not bad


def main(path, dry=False):
    new = json.load(open(path, encoding="utf-8"))
    store = json.load(open(STORE, encoding="utf-8"))
    fail = []
    for key, recs in new.items():
        print(f"\n{key}  ({len(recs)} 份 record)")
        if not check(key, recs):
            fail.append(key)
    if fail:
        print(f"\n✗ {len(fail)} 格沒過,一格都不寫:{fail}")
        return 1
    if dry:
        print("\n(--dry,未寫檔)")
        return 0
    store.update(new)
    json.dump(store, open(STORE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n✓ 全過,已併入 {STORE}(現有 {len(store)} 格)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], "--dry" in sys.argv))
