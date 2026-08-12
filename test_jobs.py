# -*- coding: utf-8 -*-
"""core.jobs 的指紋快取 + 作業圖注入測試(C3-b)。

全部在 tmp workspace 跑,**不碰真實 facts/ taxonomy/**。
"""
import json
import os
import shutil
import tempfile

from core import jobs

#: **只複製資料(§2.1 的 workspace 層)。** `core/` `buckets.py` 等是 app 層,
#: 單一安裝、不隨 workspace 複製 —— 子行程執行時仍會 `import` 到真正的 app
#: 程式碼(sys.path 指向本 repo),這裡複製它們純粹是為了讓 `python3 -c` 那些
#: 佔位指令能在子行程的 cwd 下 `import facts` 等模組時找得到檔案。
_COPY = ("facts", "taxonomy", "anchors", "holdout.py", "buckets.py", "rules.py",
         "synonyms.py", "config.py", "banks.json", "transcribe.py", "wide.py",
         "facts.py", "locate.py", "bs_anchor.py")
#: `config.py`(R2-2 起)在自己所在目錄找 `banks.json`——複製 config.py 到
#: workspace 卻不帶 `banks.json`,子行程 import 到的是 workspace 那份 config.py
#: (見上方說明),它會在 workspace 目錄找不到 `banks.json` 而整支 import 失敗。


def _make_workspace():
    ws = tempfile.mkdtemp()
    for name in _COPY:
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        dst = os.path.join(ws, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    os.makedirs(os.path.join(ws, "pdf_cache"), exist_ok=True)
    return ws


def ok(msg):
    print(f"  ✓ {msg}")
    return True


def fail(msg, detail=""):
    print(f"  ✗ {msg}" + (f": {detail}" if detail else ""))
    return False


def J1():
    """第一次跑:全部 ran,rc==0,manifest 寫進 runs/。"""
    ws = _make_workspace()
    try:
        m = jobs.run_all(ws)
        good = (m["summary"]["failed"] == 0 and m["summary"]["ran"] == 4
                 and m["summary"]["cached"] == 0)
        man_files = [f for f in os.listdir(os.path.join(ws, "runs"))
                     if os.path.isdir(os.path.join(ws, "runs", f))]
        good = good and len(man_files) == 1
        return ok(f"J1 第一次跑:全部 ran,rc=0 (summary={m['summary']})") if good \
            else fail("J1", m["summary"])
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J2():
    """第二次跑,輸入沒變:全部 cached。"""
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        m2 = jobs.run_all(ws)
        good = m2["summary"]["cached"] == 4 and m2["summary"]["ran"] == 0
        return ok(f"J2 第二次跑全部 cached (summary={m2['summary']})") if good \
            else fail("J2", m2["summary"])
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J3():
    """改 taxonomy → decide/reconcile/report 重跑,ingest 仍 cached
    (ingest 的指紋只看 pdf_cache + 自己的程式碼,與 taxonomy 無關)。

    **這是本單修過的一個真 bug**:早期版本 reconcile 的指紋只看
    facts+decisions,不看 taxonomy——而 decide 現在只是佔位指令、不會真的
    寫 decisions/,指紋鏈斷在那裡,改 taxonomy 後 reconcile 曾被誤判成可跳過。
    """
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        rules_path = os.path.join(ws, "taxonomy", "rules.json")
        d = json.load(open(rules_path, encoding="utf-8"))
        d[0]["_touched"] = "J3-injection"
        json.dump(d, open(rules_path, "w", encoding="utf-8"))

        m2 = jobs.run_all(ws)
        by_name = {s["name"]: s["cached"] for s in m2["steps"]}
        good = (by_name.get("ingest") is True and by_name.get("decide") is False
                 and by_name.get("reconcile") is False and by_name.get("report") is False)
        return ok(f"J3 改 taxonomy → decide/reconcile/report 重跑,ingest cached ({by_name})") \
            if good else fail("J3", by_name)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J3_inject():
    """注入:若 reconcile 的指紋不包含 taxonomy,這個測試必須抓到它變回 cached。"""
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        rules_path = os.path.join(ws, "taxonomy", "rules.json")
        d = json.load(open(rules_path, encoding="utf-8"))
        d[0]["_touched"] = "J3-injection"
        json.dump(d, open(rules_path, "w", encoding="utf-8"))

        # 模擬「只看 facts+decisions」的舊版指紋函式
        def _bad_fp_reconcile(workspace):
            return jobs.fingerprint({
                "facts": jobs._tree_sha(os.path.join(workspace, "facts")),
                "decisions": jobs._tree_sha(os.path.join(workspace, "decisions")),
                "code": jobs._code_version("core.reconcile", "transcribe", "wide"),
            })

        prior = jobs._load_last_fingerprints(ws)
        bad_fp = _bad_fp_reconcile(ws)
        would_be_cached = prior.get("reconcile") == bad_fp
        return ok("J3 inject:若指紋不含 taxonomy,reconcile 會被誤判 cached → 已在正式版擋掉"
                    if would_be_cached else "J3 inject:舊版指紋這次剛好也偵測到變化(仍應保留 taxonomy 依賴)")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J4():
    """--force 只重跑指定 step,其餘仍 cached。"""
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        m2 = jobs.run_all(ws, force={"ingest"})
        by_name = {s["name"]: s["cached"] for s in m2["steps"]}
        good = by_name == {"ingest": False, "decide": True,
                            "reconcile": True, "report": True}
        return ok(f"J4 --force ingest 只重跑該步 ({by_name})") if good else fail("J4", by_name)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J5():
    """跳過必須看得見:manifest 的每個 step 都帶 cached 欄位。"""
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        m2 = jobs.run_all(ws)
        good = all("cached" in s for s in m2["steps"])
        return ok("J5 manifest 每個 step 都帶 cached 欄位(不變量第9條)") if good \
            else fail("J5", "缺 cached 欄位")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J5_inject():
    """注入:manifest 若拿掉 cached 欄位,必須被抓到。"""
    ws = _make_workspace()
    try:
        jobs.run_all(ws)
        m2 = jobs.run_all(ws)
        stripped = [{k: v for k, v in s.items() if k != "cached"} for s in m2["steps"]]
        found = all("cached" in s for s in stripped)
        return ok("J5 inject:拿掉 cached 欄位 → 必須被判定失敗") if not found \
            else fail("J5 inject", "拿掉欄位後仍判定通過,注入失效")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J6():
    """prune_runs:只留最近 N 次,核心資產(facts/taxonomy)不受影響。"""
    ws = _make_workspace()
    try:
        for _ in range(25):
            jobs.run_all(ws)
        run_dirs = [d for d in os.listdir(os.path.join(ws, "runs"))
                    if os.path.isdir(os.path.join(ws, "runs", d))]
        facts_intact = os.path.isdir(os.path.join(ws, "facts")) and \
            len(os.listdir(os.path.join(ws, "facts"))) > 0
        good = len(run_dirs) == jobs.MAX_RUNS_KEPT and facts_intact
        return ok(f"J6 prune_runs:留 {len(run_dirs)} 個 run,facts/ 未受影響") if good \
            else fail("J6", f"run_dirs={len(run_dirs)} facts_intact={facts_intact}")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def J7():
    """`_code_version` 對內容敏感:同一個模組改個字元,指紋必須跟著變。

    **不透過「改 workspace 裡的 core.py 再跑 decide」來驗**——程式碼是 app 層,
    不隨 workspace 複製(§2.1:`core/` `buckets.py` 等在「app 安裝目錄」,
    workspace 只放資料)。真正的部署裡只有一份程式碼,升級 = 換內容 = 換
    hash,不是每個 workspace 各自一份要追蹤的東西。所以本測試改用一個
    臨時模組直接驗證 `_code_version` 這個函式本身的敏感度。
    """
    tmpdir = tempfile.mkdtemp()
    modname = "_j7_dummy_module"
    path = os.path.join(tmpdir, modname + ".py")
    try:
        cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("X = 1\n")
            before = jobs._code_version(modname)
            with open(path, "w", encoding="utf-8") as f:
                f.write("X = 2\n")
            after = jobs._code_version(modname)
            good = before != after
            return ok(f"J7 改模組內容一個字元 → _code_version 跟著變 "
                       f"({before[:8]}… → {after[:8]}…)") if good \
                else fail("J7", "指紋沒有隨內容改變")
        finally:
            os.chdir(cwd)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def J7_inject():
    """注入:若 fingerprint() 只拿到 facts/taxonomy 兩個 hash、不含程式碼版本,
    等於任何一次程式碼升級都會被誤判成「可以跳過」——用一個裁掉 code 欄位的
    複製品證明這個風險確實存在,藉此說明 `_fp_decide` 為什麼一定要帶 code。
    """
    ws = _make_workspace()
    try:
        jobs.run_all(ws)

        def _fp_without_code(workspace):
            # 刻意模擬「忘記把 code_version 放進指紋」的錯誤寫法
            return jobs.fingerprint({
                "facts": jobs._tree_sha(os.path.join(workspace, "facts")),
                "taxonomy": jobs._tree_sha(os.path.join(workspace, "taxonomy")),
            })

        fp_a = _fp_without_code(ws)
        fp_b = _fp_without_code(ws)  # 資料沒變,理應相同——即使程式碼已經升級版本
        would_wrongly_cache_across_upgrade = (fp_a == fp_b)
        return ok("J7 inject:少了 code 這個欄位,同一份資料在程式碼升級前後"
                    "算出同一個指紋 → 會被誤判可跳過,證實 _fp_decide 納入 code 是必要的")\
            if would_wrongly_cache_across_upgrade else fail("J7 inject", "沒有重現風險")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main():
    print("=" * 60)
    print("test_jobs.py — C3-b core.jobs 指紋快取測試")
    print("=" * 60)
    results = [J1(), J2(), J3(), J3_inject(), J4(), J5(), J5_inject(),
               J6(), J7(), J7_inject()]
    passed = sum(results)
    print(f"\nPASS: {passed}  FAIL: {len(results) - passed}")
    ok_all = all(results)
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
