# -*- coding: utf-8 -*-
"""作業圖 + 指紋快取 + 子行程執行。C3-b(`docs/plan_local_first.md` §1.5/§4.1)。

**每個作業是一個子行程**,`cwd` 設成 workspace(§0.1 的裁示:用 chdir 而不是
路徑注入 —— 這樣禁改清單上那些寫死相對路徑的模組一行都不用改)。

**每個作業宣告輸入指紋**,重跑時比對指紋,相同就跳過並標「快取命中」,
且**跳過必須看得見**(不變量第 9 條)——`run_all()` 回傳的結果裡每個作業都
帶著 `cached: bool`,不准吞掉這個資訊。

**作業圖是寫死的固定拓樸**(見 `GRAPH`),不是動態發現的:

    ingest ─→ decide ─→ reconcile ─→ report

`ingest` 目前是空的階段(C3-a 的 `core.ingest` 只處理單一格的抄列判斷,
還沒有「重跑整批 ingest」這個概念),先佔位,C3-b 之後有真的 batch ingest
時再接上。

⚠️ 本檔**只做編排**,不做任何分類/對帳/報表邏輯 —— 那些邏輯永遠在
`core/decisions.py` `core/reconcile.py` `build.py` 等既有模組裡,本檔只負責
「決定要不要跑」與「跑的時候 cwd 對不對」。

⚠️ 沒有 UI。本檔要能被純 CLI 呼叫與驗證(`python3 -m core.jobs run <workspace>`)。
"""
import hashlib
import json
import os
import subprocess
import sys
import time

RUNS_DIR = "runs"
MAX_RUNS_KEPT = 20  # 使用者裁示:留最近 20 次,其餘可被 prune() 清除


# ── 指紋 ─────────────────────────────────────────────────────────────────

def _file_sha(path):
    """單一檔案內容的 sha256。檔案不存在 → 用固定哨兵值(而非 raise),
    因為「這一版輸入裡某檔案不存在」本身就是指紋的一部分(例如 taxonomy
    還沒批准出 derivations.json 之前它是空陣列,不是不存在)。
    """
    if not os.path.exists(path):
        return "absent"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _tree_sha(root):
    """目錄底下所有檔案(依相對路徑排序)內容的合併 sha256。"""
    if not os.path.isdir(root):
        return "absent"
    h = hashlib.sha256()
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            h.update(rel.encode("utf-8"))
            h.update(_file_sha(os.path.join(dirpath, name)).encode("utf-8"))
    return h.hexdigest()


def _code_version(*module_names):
    """程式碼版本進指紋 —— 否則改了 decide() 的邏輯,但 facts 沒變,
    重跑會被誤判成「可以跳過」,吐出一份用舊邏輯算的結果。

    做法:每個模組檔案內容的 sha256(不是 import 後的行為指紋 —— 那樣做不到,
    純粹用原始碼字節當版本號,改一個字元就變號)。
    """
    h = hashlib.sha256()
    for name in sorted(module_names):
        path = name.replace(".", "/") + ".py"
        h.update(name.encode("utf-8"))
        h.update(_file_sha(path).encode("utf-8"))
    return h.hexdigest()


def fingerprint(inputs):
    """inputs: {label: sha_str} → 單一 fingerprint 字串。

    帶標籤是為了讓「哪個輸入變了」在 diff 時可讀 —— fingerprint 本身只是
    這些標籤與值序列化後的 sha256。
    """
    blob = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── 作業圖:固定拓樸 ──────────────────────────────────────────────────────

def _fp_ingest(workspace):
    return fingerprint({
        "pdf_cache": _tree_sha(os.path.join(workspace, "pdf_cache")),
        "code": _code_version("core.ingest", "locate", "transcribe"),
    })


def _fp_decide(workspace):
    return fingerprint({
        "facts": _tree_sha(os.path.join(workspace, "facts")),
        "taxonomy": _tree_sha(os.path.join(workspace, "taxonomy")),
        "code": _code_version("core.decisions", "buckets", "rules"),
    })


def _fp_reconcile(workspace):
    # ⚠️ 也直接讀 taxonomy,**不能只靠 decisions/**——即使 `decide` 步驟現在
    # 真的會寫 decisions/(`core.ingest.backfill_decisions`),它**只補缺的**,
    # 不會在 taxonomy 改變時重算已經存在的紀錄(那是刻意的:不能覆蓋掉已經
    # 走過 B2 supersede/rebind 的歷史)。所以改 taxonomy 不保證 decisions/
    # 的內容跟著變,指紋鏈若只走 decisions/ 一樣會斷在這裡——taxonomy 這道
    # 安全網因此是永久性的,不是「等 decide 接上就能拿掉」的過渡措施。
    return fingerprint({
        "facts": _tree_sha(os.path.join(workspace, "facts")),
        "taxonomy": _tree_sha(os.path.join(workspace, "taxonomy")),
        "decisions": _tree_sha(os.path.join(workspace, "decisions")),
        "code": _code_version("core.reconcile", "transcribe", "wide"),
    })


def _fp_report(workspace):
    return fingerprint({
        "reconcile": _fp_reconcile(workspace),
        "holdout": _code_version("holdout"),
        "code": _code_version("results"),
    })


#: 作業圖節點:name → (指紋函式, 執行函式)。**固定拓樸,不是動態發現**——
#: 順序就是資料流順序(ingest → decide → reconcile → report),下游的指紋
#: 天然涵蓋上游(見 `_fp_decide` 讀 facts,`_fp_reconcile` 讀 decisions,
#: 因為上游變了下游的輸入內容就變,不需要額外的「upstream changed」訊號)。
GRAPH = ("ingest", "decide", "reconcile", "report")


def _run_step_subprocess(workspace, step, argv):
    """在 cwd=workspace 的子行程裡跑 argv,回傳 (rc, stdout, stderr, 秒數)。

    **子行程是刻意的**(§0.1):cwd 是行程級的狀態,唯有子行程才能讓
    `facts.py` `results.py` 這些寫死相對路徑的模組,在不同 workspace 之間
    正確運作而不必修改它們。副作用是好的:可逾時、可擷取 log、一個作業
    壞掉不會拖垮呼叫者。
    """
    t0 = time.time()
    try:
        # cwd=workspace 讓 `facts.py`/`buckets.py` 這類寫死相對路徑的模組讀對
        # workspace 的資料(§0.1);但 `core/` 這種 app 層套件不隨 workspace
        # 複製,子行程若只認 cwd 會 import 不到它 —— 所以另外把 app 安裝目錄
        # (本檔所在 repo 的根)塞進 PYTHONPATH,讓套件 import 不受 cwd 影響。
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = app_root + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            argv, cwd=workspace, capture_output=True, text=True,
            timeout=600, env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr, time.time() - t0
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + "\n[jobs] timeout after 600s", time.time() - t0


_FP_FUNCS = {
    "ingest": _fp_ingest,
    "decide": _fp_decide,
    "reconcile": _fp_reconcile,
    "report": _fp_report,
}

#: step → 在 workspace 裡實際要跑的指令(argv)。用 `sys.executable` 而不是
#: 寫死 "python3",確保跑的是同一個直譯器/venv(避免子行程撿到系統 python)。
_STEP_ARGV = {
    "ingest": [sys.executable, "-c",
               "print('ingest: no batch ingest job yet, placeholder step')"],
    "decide": [sys.executable, "-c",
               "import facts\n"
               "from core import ingest\n"
               "cells = facts.load()\n"
               "n = ingest.backfill_decisions(cells)\n"
               "print(f'decide: {len(cells)} 格,補了 {n} 格新的 Decision(其餘沿用既有紀錄)')"],
    "reconcile": [sys.executable, "-c",
                  "import facts\n"
                  "from core import reconcile\n"
                  "cells = facts.load()\n"
                  "verdict, audit = reconcile.verify_all(cells)\n"
                  "bad = [k for k, v in verdict.items() if not v['pass']]\n"
                  "print(f'reconcile: {len(verdict)} 格,不通過 {len(bad)}')\n"
                  # 2026-08-12:不再 `raise SystemExit(1 if bad else 0)`。有格子
                  # 沒過(PROVISIONAL/UNCLASSIFIED 待人審)是活資料庫的正常穩態,
                  # 不是這個批次任務本身出錯——`publish_gate` 已經在管「能不能
                  # 發布」,reconcile 這一步只負責把現況印出來給人看。
                  ],
    "report": [sys.executable, "-c",
               "print('report: placeholder — C4 才會產出 out/report/')"],
}


# ── runs/ 紀錄 ───────────────────────────────────────────────────────────

def _new_run_dir(workspace):
    # 秒級時間戳 + pid 在同一秒內連續呼叫(測試常見)會撞名 —— 加微秒與短隨機值。
    os.makedirs(os.path.join(workspace, RUNS_DIR), exist_ok=True)
    import random
    for _ in range(10):
        run_id = (time.strftime("%Y%m%dT%H%M%S")
                  + f"-{int(time.time() * 1e6) % 1000000:06d}"
                  + f"-{os.getpid()}-{random.randint(0, 9999):04d}")
        d = os.path.join(workspace, RUNS_DIR, run_id)
        try:
            os.makedirs(d, exist_ok=False)
            return run_id, d
        except FileExistsError:
            continue
    raise RuntimeError("jobs: 無法產生唯一的 run_id(異常重複衝突)")


def run_all(workspace, force=None):
    """依 GRAPH 固定順序跑每一步,能跳過的跳過。

    force: 要強制重跑的 step 名稱集合(即使指紋相同)。None = 不強制任何一步。

    回傳一份完整結果並寫進 `runs/<run_id>/manifest.json`:
        {run_id, steps: [{name, fingerprint, cached, rc, seconds, stdout, stderr}]}

    **跳過必須看得見**:每個 step 都帶 `cached: bool`,manifest 裡逐項列出,
    不做「靜靜跳過」這件事。
    """
    force = set(force or ())
    run_id, run_dir = _new_run_dir(workspace)
    steps_out = []
    prior_fp = _load_last_fingerprints(workspace)

    for step in GRAPH:
        fp = _FP_FUNCS[step](workspace)
        cached = (not force.intersection({step})) and prior_fp.get(step) == fp
        if cached:
            steps_out.append({
                "name": step, "fingerprint": fp, "cached": True,
                "rc": 0, "seconds": 0.0, "stdout": "", "stderr": "",
            })
            continue
        rc, out, err, secs = _run_step_subprocess(workspace, step, _STEP_ARGV[step])
        steps_out.append({
            "name": step, "fingerprint": fp, "cached": False,
            "rc": rc, "seconds": round(secs, 3), "stdout": out, "stderr": err,
        })
        if rc != 0:
            # 下游作業的輸入依賴這一步的產出,它失敗就不繼續跑下去 ——
            # 但已經跑完/命中的步驟結果仍然完整寫進 manifest。
            break

    manifest = {
        "run_id": run_id,
        "workspace": os.path.abspath(workspace),
        "steps": steps_out,
        "summary": {
            "total": len(steps_out),
            "cached": sum(1 for s in steps_out if s["cached"]),
            "ran": sum(1 for s in steps_out if not s["cached"]),
            "failed": sum(1 for s in steps_out if s["rc"] != 0),
        },
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    _save_fingerprints(workspace, {s["name"]: s["fingerprint"] for s in steps_out})
    prune_runs(workspace)
    return manifest


_FP_STATE_FILE = os.path.join(RUNS_DIR, "_last_fingerprints.json")


def _load_last_fingerprints(workspace):
    p = os.path.join(workspace, _FP_STATE_FILE)
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8"))


def _save_fingerprints(workspace, fps):
    os.makedirs(os.path.join(workspace, RUNS_DIR), exist_ok=True)
    p = os.path.join(workspace, _FP_STATE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(fps, f, ensure_ascii=False, indent=1, sort_keys=True)


def prune_runs(workspace, keep=MAX_RUNS_KEPT):
    """只留最近 keep 次的 run 目錄。**runs/ 全部是可重建的 runtime**,
    刪掉不會遺失任何核心資產(facts/ taxonomy/ decisions/ 都不在這裡)。
    """
    base = os.path.join(workspace, RUNS_DIR)
    if not os.path.isdir(base):
        return
    run_dirs = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and d != "__pycache__"
    )
    for d in run_dirs[:-keep] if keep > 0 else run_dirs:
        import shutil
        shutil.rmtree(os.path.join(base, d), ignore_errors=True)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2 or argv[0] != "run":
        print("用法: python3 -m core.jobs run <workspace> [--force step1,step2]")
        return 2
    workspace = argv[1]
    force = set()
    if "--force" in argv:
        idx = argv.index("--force")
        if idx + 1 < len(argv):
            force = set(argv[idx + 1].split(","))
    manifest = run_all(workspace, force=force)
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=1))
    return 1 if manifest["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
