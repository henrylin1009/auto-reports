# -*- coding: utf-8 -*-
"""E2 等價閘門:core.reconcile(吃 anchors/,零 PDF)vs results.build()(吃 PDF)。

斷言:
  1. key 集合相同
  2. 每格 pass/wide/wide_cost/side/others/anchor 逐欄相同
  3. 每格 checks 的訊息字串逐字相同(不是「都失敗」就算過)
  4. audit 的 sources/basis_gap/unknown 逐項相同
"""
import time

import facts
import holdout
import results
from core import reconcile


def main():
    cells = facts.load()
    train, _leak = holdout.split(cells)

    t0 = time.time()
    old_verdict, old_audit = results.build(train)
    t_old = time.time() - t0

    t0 = time.time()
    new_verdict, new_audit = reconcile.verify_all(train)
    t_new = time.time() - t0

    print(f"core.reconcile.verify_all: {t_new:.3f}s   results.build: {t_old:.3f}s")

    ok = True

    # 1. key 集合相同
    ks_old, ks_new = set(old_verdict), set(new_verdict)
    same_keys = ks_old == ks_new
    ok &= same_keys
    print(f"  {'✓' if same_keys else '✗'} 1. key 集合相同:old={len(ks_old)} new={len(ks_new)} "
          f"diff={sorted(ks_old ^ ks_new)}")

    # 2. 每格 pass/wide/wide_cost/side/others/anchor 逐欄相同
    fields = ("pass", "wide", "wide_cost", "side", "others", "anchor")
    bad2 = []
    for key in sorted(ks_old & ks_new):
        for f in fields:
            if old_verdict[key].get(f) != new_verdict[key].get(f):
                bad2.append((key, f))
    ok2 = not bad2
    ok &= ok2
    print(f"  {'✓' if ok2 else '✗'} 2. verdict 逐欄相同:不一致 {len(bad2)}:{bad2[:10]}")

    # 3. checks 訊息字串逐字相同
    bad3 = []
    for key in sorted(ks_old & ks_new):
        oc, nc = old_audit[key]["checks"], new_audit[key]["checks"]
        if oc != nc:
            bad3.append((key, {k: (oc.get(k), nc.get(k)) for k in set(oc) | set(nc)
                                if oc.get(k) != nc.get(k)}))
    ok3 = not bad3
    ok &= ok3
    print(f"  {'✓' if ok3 else '✗'} 3. checks 訊息逐字相同:不一致 {len(bad3)}:{bad3[:5]}")

    # 4. audit 的 sources/basis_gap/unknown 逐項相同
    bad4 = []
    for key in sorted(ks_old & ks_new):
        for f in ("sources", "basis_gap", "unknown"):
            if old_audit[key][f] != new_audit[key][f]:
                bad4.append((key, f))
    ok4 = not bad4
    ok &= ok4
    print(f"  {'✓' if ok4 else '✗'} 4. audit sources/basis_gap/unknown 逐項相同:不一致 {len(bad4)}:{bad4[:10]}")

    print(f"\n{'E2 全綠' if ok else 'E2 有不一致'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
