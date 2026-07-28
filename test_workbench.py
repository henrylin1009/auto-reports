# -*- coding: utf-8 -*-
"""test_workbench.py — 工作台六個頁面的路由煙霧測試 + POST 處置。

GET 路由對真實 repo 唯讀(Dashboard/Review/Results/Trace/Data 都只讀,不寫),
POST(Update/Review 處置)一律在 tmp workspace 裡跑,絕不對真實 repo 發 POST。
"""
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request

from core import workbench

PASS = 0
FAIL = 0


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  {detail}" if detail else ""))


def fail(label, msg=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {msg}")


def _free_port():
    s = socket.socket()
    s.bind((workbench.HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, cwd):
        self.port = _free_port()
        self.cwd = cwd

    def __enter__(self):
        self._orig_cwd = os.getcwd()
        os.chdir(self.cwd)
        import socketserver
        self.httpd = socketserver.TCPServer((workbench.HOST, self.port), workbench.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.1)
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.chdir(self._orig_cwd)

    def get(self, path):
        with urllib.request.urlopen(f"http://{workbench.HOST}:{self.port}{path}", timeout=5) as r:
            return r.status, r.read().decode("utf-8")

    def post(self, path, data):
        body = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in data.items())
        req = urllib.request.Request(
            f"http://{workbench.HOST}:{self.port}{path}", data=body.encode(), method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8")


# ── GET 路由煙霧測試(對真實 repo 唯讀)──────────────────────────────────

def GET_all_six_pages_on_real_repo():
    with _Server(os.getcwd()) as s:
        results = {}
        for path in ("/", "/update", "/review", "/results", "/trace", "/data"):
            status, body = s.get(path)
            results[path] = (status, "<title>" in body)
        good = all(status == 200 and has_title for status, has_title in results.values())
        return ok("六個頁面 GET 全部 200,對真實 repo 唯讀", results) if good \
            else fail("GET_all_six_pages", results)


def GET_binds_only_127_0_0_1():
    with _Server(os.getcwd()) as s:
        sock_name = s.httpd.server_address
        good = sock_name[0] == "127.0.0.1"
        return ok(f"伺服器只綁 127.0.0.1(server_address={sock_name})") if good \
            else fail("GET_binds_only_127_0_0_1", sock_name)


def GET_404_for_unknown_path():
    with _Server(os.getcwd()) as s:
        try:
            s.get("/nonexistent")
            fail("GET_404", "沒有拋出 HTTPError")
        except urllib.error.HTTPError as e:
            good = e.code == 404
            return ok("未知路徑回 404") if good else fail("GET_404", e.code)


def GET_static_out_report_blocks_traversal():
    with _Server(os.getcwd()) as s:
        try:
            s.get("/out/../fill.py")
            fail("static_traversal", "應該被擋下來卻沒有")
        except urllib.error.HTTPError as e:
            good = e.code in (403, 404)
            return ok(f"靜態檔案路由擋下 ../ 逃逸(status={e.code})") if good \
                else fail("static_traversal", e.code)


# ── POST(在 tmp workspace 跑,不碰真實 repo)────────────────────────────

def _make_workspace():
    ws = tempfile.mkdtemp()
    for name in ("facts", "taxonomy", "anchors", "holdout.py", "buckets.py", "rules.py",
                "synonyms.py", "config.py", "transcribe.py", "wide.py", "facts.py",
                "locate.py", "bs_anchor.py"):
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        dst = os.path.join(ws, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    os.makedirs(os.path.join(ws, "pdf_cache"), exist_ok=True)
    return ws


def POST_update_runs_jobs_in_tmp_workspace():
    ws = _make_workspace()
    try:
        with _Server(ws) as s:
            status, body = s.post("/update", {})
            good = status == 200 and "run_id" in body
            has_review = os.path.exists(os.path.join(ws, "review", "queue.jsonl"))
            good = good and has_review
            return ok("POST /update 觸發 core.jobs.run_all(),補出 review 佇列",
                       f"has_review={has_review}") if good \
                else fail("POST_update", f"status={status}, has_review={has_review}")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _load_review_jsonl(ws):
    p = os.path.join(ws, "review", "queue.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def POST_review_confirm_upgrades_taxonomy_in_tmp_workspace():
    """真實 36 格裡每個非 CONFIRMED 的名字,taxonomy 早就有對應的 PROVISIONAL
    rule 了(B1 遷移時全覆蓋過)——所以這裡測的是「用既有 mapping 重新確認」,
    不是憑空生一個全新名字(那種情況今天的資料裡找不到)。"""
    ws = _make_workspace()
    try:
        with _Server(ws) as s:
            s.post("/update", {})  # 先補出 review 佇列
            entries = _load_review_jsonl(ws)  # 直接讀 tmp 路徑,不靠 cwd 相依的 decision_store
            if not entries:
                return fail("POST_review_confirm", "tmp workspace 沒有任何待審項(環境變了?)")
            e = entries[0]
            existing_mapping = e["decision"]["mapping"]  # taxonomy 裡已有的 mapping
            occ = e["decision"]["occurrence"]
            occ_id = f"{occ['record_fp']}:{occ['row_fp']}"
            status, body = s.post("/review/confirm", {
                "cell_key": e["cell_key"], "occ_id": occ_id,
                "norm_name": e["decision"]["name"], "mapping": existing_mapping,
                "reason": "smoke test"})
            good = status == 200 and "已收錄" in body
            rules = json.load(open(os.path.join(ws, "taxonomy", "rules.json"), encoding="utf-8"))
            confirmed = any(r["state"] == "CONFIRMED" and r["mapping"] == existing_mapping
                            and r["rule_id"] == e["decision"]["taxonomy_ref"] for r in rules)
            good = good and confirmed
            return ok(f"POST /review/confirm 把既有 rule({e['decision']['taxonomy_ref']})升成 CONFIRMED") \
                if good else fail("POST_review_confirm", f"status={status}, confirmed={confirmed}")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def POST_review_confirm_rejects_mapping_mismatch():
    """真實踩到的坑,已修:review 名字剛好對到 taxonomy 已存在但 mapping
    不同的 rule 時,**不准靜靜沿用舊值蓋掉使用者輸入**——必須明確拒絕,
    讓使用者知道自己填的桶名沒有被採用,而不是誤以為採用了。"""
    ws = _make_workspace()
    try:
        with _Server(ws) as s:
            s.post("/update", {})
            entries = _load_review_jsonl(ws)
            if not entries:
                return fail("POST_review_confirm_mismatch", "沒有待審項")
            e = entries[0]
            wrong_mapping = e["decision"]["mapping"] + "_不是這個"
            occ = e["decision"]["occurrence"]
            occ_id = f"{occ['record_fp']}:{occ['row_fp']}"
            status, body = s.post("/review/confirm", {
                "cell_key": e["cell_key"], "occ_id": occ_id,
                "norm_name": e["decision"]["name"], "mapping": wrong_mapping,
                "reason": "smoke test"})
            good = status == 200 and "收錄失敗" in body and "已取消" in body
            rules = json.load(open(os.path.join(ws, "taxonomy", "rules.json"), encoding="utf-8"))
            not_wrongly_confirmed = not any(r["mapping"] == wrong_mapping for r in rules)
            good = good and not_wrongly_confirmed
            return ok("填錯的桶名被明確擋下(不是靜靜沿用舊 mapping)") if good \
                else fail("POST_review_confirm_mismatch", f"body 有錯誤訊息={('收錄失敗' in body)}")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main():
    print("=" * 60)
    print("test_workbench.py — 工作台六頁面 + POST 處置")
    print("=" * 60)
    tests = [GET_all_six_pages_on_real_repo, GET_binds_only_127_0_0_1,
             GET_404_for_unknown_path, GET_static_out_report_blocks_traversal,
             POST_update_runs_jobs_in_tmp_workspace,
             POST_review_confirm_upgrades_taxonomy_in_tmp_workspace,
             POST_review_confirm_rejects_mapping_mismatch]
    for t in tests:
        t()
    print(f"\nPASS: {PASS}  FAIL: {FAIL}")
    ok_all = FAIL == 0
    print("RESULT:", "OK" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
