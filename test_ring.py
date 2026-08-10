# -*- coding: utf-8 -*-
"""R3 的分層測試(T-R3):Ring 1(純)不得碰 PDF / state / 時鐘。

Ring 1:core.classify(尚不存在,C2 才有) / core.reconcile /
        core.publish(尚不存在,C4 才有) / core.units
        (core.contracts 已刪除,`docs/plan_schema_derive.md` D3 —— 零 production 引用,
        跟 facts.py 重複一份驗證邏輯,只有自己的測試在用)
Ring 0:core.store 的 anchors 產生器 / core.ingest(尚不存在,C3 才有) / resolve
"""
import json
import os
import subprocess
import sys


def test_ring1_no_pdf():
    """把 pdf_cache/ 與 state/ 暫時改名,跑 Ring 1 的 verify/build 路徑
    → 要能跑完且輸出逐位元組相同。**測試結束一定要改回來**(try/finally)。"""
    moved = []
    for d in ("pdf_cache", "state"):
        if os.path.isdir(d):
            os.rename(d, d + ".ring1test")
            moved.append(d)
    try:
        import facts
        import holdout
        from core import reconcile

        cells = facts.load()
        train, _ = holdout.split(cells)
        v1, a1 = reconcile.verify_all(train)
        v2, a2 = reconcile.verify_all(train)
        same = (json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True)
                and json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True))
        ok = same and len(v1) == len(train)
        print(f"  {'✓' if ok else '✗'} test_ring1_no_pdf:pdf_cache/state 不在時仍可跑完,"
              f"逐位元組相同={same},格數={len(v1)}")
        return ok
    finally:
        for d in moved:
            os.rename(d + ".ring1test", d)


def test_ring1_imports():
    """import core.reconcile 之後,sys.modules 不含 pypdfium2 / requests。"""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; import core.reconcile; "
         "print('pypdfium2' in sys.modules, 'requests' in sys.modules)"],
        capture_output=True, text=True)
    ok = out.stdout.strip() == "False False"
    print(f"  {'✓' if ok else '✗'} test_ring1_imports:{out.stdout.strip()} {out.stderr[-300:] if not ok else ''}")
    return ok


def test_ring1_deterministic():
    """同輸入連跑兩次,payload 逐位元組相同(時鐘只准出現在 manifest,不准進 data.json)。"""
    import facts
    import holdout
    from core import reconcile

    cells = facts.load()
    train, _ = holdout.split(cells)
    v1, a1 = reconcile.verify_all(train)
    v2, a2 = reconcile.verify_all(train)
    ok = (json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True)
          and json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True))
    print(f"  {'✓' if ok else '✗'} test_ring1_deterministic:{ok}")
    return ok


def main():
    print("test_ring1_no_pdf")
    ok = test_ring1_no_pdf()
    print("test_ring1_imports")
    ok &= test_ring1_imports()
    print("test_ring1_deterministic")
    ok &= test_ring1_deterministic()
    print(f"\n{'全部通過' if ok else '有失敗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
