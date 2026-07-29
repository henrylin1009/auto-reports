# -*- coding: utf-8 -*-
"""本機工作台:127.0.0.1 伺服器 + 六個頁面(`docs/plan_local_first.md` §4.1)。

    Dashboard  archived/publishable、review 佇列數、最近一次 Update 摘要
    Update     觸發 core.jobs.run_all(),顯示每步 cached/ran/耗時
    Review     review/queue.jsonl 三種處置(收錄/退回/人工擴頁)
    Results    out/report/ 的報表(連到 core.report 產的自足頁,或內嵌同一份資料)
    Trace      給一個 record_fp:row_fp,查出是哪條 Decision、引用什麼證據
    Data       facts/ 的原始清單(唯讀)

**只用標準庫 `http.server`**——這台機器的 venv 沒裝 Flask/Bottle,而且這正好
呼應不變量 6(本機不需上傳):不必額外裝套件就能跑。

⚠️ **只綁 127.0.0.1,寫死,不接受參數改成 0.0.0.0。** 這是本機工具,
不是要給區網其他機器連的伺服器。
"""
import html
import http.server
import json
import os
import socketserver
import urllib.parse

import facts as facts_mod
from core import (decision_store, ingest, jobs, publish_gate,
                  queue as queue_mod, report as report_mod, review)

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_STYLE = """
body{font-family:-apple-system,sans-serif;margin:0;background:#0b0d10;color:#e5e7eb}
nav{display:flex;gap:0;background:#14171b;border-bottom:1px solid #2a2d33}
nav a{padding:.7rem 1.1rem;color:#9ca3af;text-decoration:none;font-size:.9rem}
nav a.active{color:#e5e7eb;background:#1f2329;border-bottom:2px solid #60a5fa}
main{padding:1.5rem;max-width:1100px}
table{border-collapse:collapse;margin:1rem 0;width:100%}
th,td{border:1px solid #2a2d33;padding:.4rem .6rem;font-size:.85rem;text-align:left}
th{background:#14171b}
button,input[type=submit]{background:#2563eb;color:#fff;border:none;padding:.4rem .8rem;
  border-radius:4px;cursor:pointer;font-size:.85rem}
button.reject{background:#4b5563}
input[type=text]{background:#14171b;border:1px solid #2a2d33;color:#e5e7eb;padding:.3rem;
  border-radius:4px}
.stat{display:inline-block;margin-right:2rem;font-size:1.4rem}
.stat small{display:block;font-size:.75rem;color:#9ca3af;font-weight:normal}
.warn{color:#facc15}.ok{color:#4ade80}.muted{color:#666}
pre{background:#14171b;padding:1rem;overflow-x:auto;border-radius:4px;font-size:.8rem}
"""

_PAGES = [("/", "Dashboard"), ("/update", "Update"), ("/review", "Review"),
         ("/results", "Results"), ("/trace", "Trace"), ("/data", "Data")]


def _nav(active):
    links = "".join(
        f'<a href="{href}"{" class=active" if href == active else ""}>{name}</a>'
        for href, name in _PAGES)
    return f"<nav>{links}</nav>"


def _page(active, title, body):
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{title} · 工作台</title><style>{_STYLE}</style></head>
<body>{_nav(active)}<main>{body}</main></body></html>"""


def _e(s):
    return html.escape(str(s))


# ── Dashboard ────────────────────────────────────────────────────────────

def page_dashboard():
    cells = facts_mod.load()
    status = publish_gate.status_all(cells)
    # **不准只數 review/queue.jsonl**——那個檔在真實 workspace 裡根本不存在,
    # 卡住的格子全在 work/blocked/。只讀一邊就會報出「待審 0」的假綠燈。
    todo = queue_mod.pending()
    n_blocked = sum(1 for e in todo if e["source"] == "blocked")
    n_review = len(todo) - n_blocked
    resolved_count = len(decision_store.load_review(decision_store.RESOLVED_LOG))
    body = f"""
<h1>Dashboard</h1>
<div class="stat">{status['archived']}<small>已存檔</small></div>
<div class="stat">{status['publishable']}<small>可發布</small></div>
<div class="stat">{len(todo)}<small>待人裁示(合流)</small></div>
<div class="stat">{n_blocked}<small>其中卡在分類表缺口</small></div>
<div class="stat">{n_review}<small>其中 review 佇列</small></div>
<div class="stat">{resolved_count}<small>已處置(歷史)</small></div>
<p class="muted">「已存檔」與「可發布」的差不是退步——not confirmed 的格子
照樣進報表,只是標成待審。見 <a href="/results" style="color:#60a5fa">Results</a>。</p>
<p><a href="/update" style="color:#60a5fa">執行更新 →</a></p>
"""
    return _page("/", "Dashboard", body)


# ── Update ───────────────────────────────────────────────────────────────

def page_update(run_result=None):
    body = "<h1>Update</h1><form method=post action=/update><button>執行更新</button></form>"
    if run_result:
        rows = "".join(
            f"<tr><td>{_e(s['name'])}</td>"
            f"<td>{'快取命中' if s['cached'] else '重跑'}</td>"
            f"<td>{s['rc']}</td><td>{s['seconds']}s</td></tr>"
            for s in run_result["steps"])
        body += f"""
<h2>run_id: {_e(run_result['run_id'])}</h2>
<table><tr><th>步驟</th><th>狀態</th><th>rc</th><th>耗時</th></tr>{rows}</table>
<p>{json.dumps(run_result['summary'], ensure_ascii=False)}</p>
"""
    return _page("/update", "Update", body)


# ── Review ───────────────────────────────────────────────────────────────

def page_review(message=None):
    entries = decision_store.load_review()
    msg_html = f'<p class="ok">{_e(message)}</p>' if message else ""
    rows = []
    for e in entries:
        dec = e["decision"]
        occ = dec.get("occurrence") or {}
        occ_id = f"{occ.get('record_fp')}:{occ.get('row_fp')}"
        norm_guess = dec["name"]
        rows.append(f"""
<tr>
  <td>{_e(e['cell_key'])}</td>
  <td>{_e(dec['name'])}</td>
  <td>{_e(dec.get('group') or '')}</td>
  <td>{_e(dec['state'])}</td>
  <td>{_e(dec.get('mapping') or '(無候選)')}</td>
  <td>
    <form method=post action="/review/confirm" style="display:inline">
      <input type=hidden name=cell_key value="{_e(e['cell_key'])}">
      <input type=hidden name=occ_id value="{_e(occ_id)}">
      <input type=text name=norm_name value="{_e(norm_guess)}" size=10>
      <input type=text name=mapping placeholder="桶名" size=8>
      <input type=text name=reason placeholder="理由" size=14>
      <button type=submit>收錄</button>
    </form>
    <form method=post action="/review/reject" style="display:inline">
      <input type=hidden name=cell_key value="{_e(e['cell_key'])}">
      <input type=hidden name=occ_id value="{_e(occ_id)}">
      <input type=text name=reason placeholder="理由" size=10>
      <button type=submit class=reject>退回</button>
    </form>
  </td>
</tr>""")
    table = ("<table><tr><th>格</th><th>名稱</th><th>段落</th><th>狀態</th>"
            "<th>候選桶</th><th>處置</th></tr>" + "".join(rows) + "</table>") \
        if rows else "<p class=muted>待審佇列是空的。</p>"
    body = f"<h1>Review</h1>{msg_html}<p>{len(entries)} 筆待審</p>{table}"
    return _page("/review", "Review", body)


def _find_review_entry(cell_key, occ_id):
    for e in decision_store.load_review():
        occ = (e["decision"].get("occurrence") or {})
        if e["cell_key"] == cell_key and f"{occ.get('record_fp')}:{occ.get('row_fp')}" == occ_id:
            return e, occ
    return None, None


# ── Results(連到 core.report 的產物)──────────────────────────────────

def page_results():
    if not os.path.exists("out/report/report.json"):
        return _page("/results", "Results",
                    "<h1>Results</h1><p class=warn>還沒有報表。"
                    "去 <a href='/update' style='color:#60a5fa'>Update</a> 跑一次。</p>")
    manifest = json.load(open("out/report/manifest.json", encoding="utf-8"))
    body = f"""<h1>Results</h1>
<p>archived={manifest['summary']['archived']} publishable={manifest['summary']['publishable']}
  孤兒數字={len(manifest['coverage']['orphans'])} run_id={_e(manifest['run_id'])}</p>
<p><a href="/out/report/index.html" style="color:#60a5fa">開啟完整報表(離線自足頁)→</a></p>
"""
    return _page("/results", "Results", body)


# ── Trace ────────────────────────────────────────────────────────────────

def page_trace(occ_id=None):
    body = """<h1>Trace</h1>
<form method=get action=/trace>
<input type=text name=id placeholder="record_fp:row_fp" size=40>
<button>查</button></form>"""
    if occ_id:
        found = None
        for key, decs in decision_store.load().items():
            for d in decs:
                occ = d.get("occurrence") or {}
                if f"{occ.get('record_fp')}:{occ.get('row_fp')}" == occ_id:
                    found = (key, d)
                    break
            if found:
                break
        if found:
            key, d = found
            refs = "".join(f"<li>[{_e(r['kind'])}] {_e(r['detail'])}</li>"
                           for r in d.get("references", []))
            body += f"""
<h2>{_e(key)} · {_e(d['name'])}</h2>
<p>state={_e(d['state'])} mapping={_e(d.get('mapping'))}
  taxonomy_ref={_e(d.get('taxonomy_ref'))}</p>
<h3>references</h3><ul>{refs or '<li class=muted>無(見 taxonomy rule 上的 reference)</li>'}</ul>
<pre>{_e(json.dumps(d, ensure_ascii=False, indent=1))}</pre>
"""
        else:
            body += f"<p class=warn>找不到 {_e(occ_id)}</p>"
    return _page("/trace", "Trace", body)


# ── Data(唯讀)───────────────────────────────────────────────────────────

def page_data():
    cells = facts_mod.load()
    rows = "".join(f"<tr><td>{_e(k)}</td><td>{sum(len(r['rows']) for r in v)}</td></tr>"
                   for k, v in sorted(cells.items()))
    body = f"""<h1>Data</h1><p class=muted>唯讀:facts/ 的原始清單。</p>
<table><tr><th>格</th><th>列數</th></tr>{rows}</table>"""
    return _page("/data", "Data", body)


# ── HTTP handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 安靜點,不必每個 request 都印到 stderr

    def _send(self, status, body, content_type="text/html; charset=utf-8"):
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                self._send(200, page_dashboard())
            elif path == "/update":
                self._send(200, page_update())
            elif path == "/review":
                self._send(200, page_review())
            elif path == "/results":
                self._send(200, page_results())
            elif path == "/trace":
                self._send(200, page_trace(qs.get("id", [None])[0]))
            elif path == "/data":
                self._send(200, page_data())
            elif path.startswith("/out/"):
                self._serve_static(path)
            else:
                self._send(404, _page(None, "404", "<h1>404</h1>"))
        except Exception as e:
            self._send(500, _page(None, "錯誤", f"<h1>錯誤</h1><pre>{_e(e)}</pre>"))

    def _serve_static(self, path):
        # 只准讀 out/ 底下,防止 ../ 逃出去讀任意檔案。
        rel = os.path.normpath(path.lstrip("/"))
        if rel.startswith("..") or not rel.startswith("out" + os.sep) and rel != "out":
            self._send(403, "forbidden")
            return
        if not os.path.exists(rel):
            self._send(404, "not found")
            return
        content_type = ("text/html; charset=utf-8" if rel.endswith(".html") else
                        "application/json; charset=utf-8" if rel.endswith(".json") else
                        "application/octet-stream")
        self._send(200, open(rel, "rb").read(), content_type)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body)
        f = {k: v[0] for k, v in form.items()}
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/update":
                result = jobs.run_all(".")
                self._send(200, page_update(result))
            elif path == "/review/confirm":
                self._dispose_confirm(f)
            elif path == "/review/reject":
                self._dispose_reject(f)
            elif path == "/review/expand":
                self._dispose_expand(f)
            else:
                self._send(404, "not found")
        except Exception as e:
            self._send(500, _page(None, "錯誤", f"<h1>錯誤</h1><pre>{_e(e)}</pre>"))

    def _dispose_confirm(self, f):
        import buckets
        import datetime
        e, occ = _find_review_entry(f["cell_key"], f["occ_id"])
        if e is None:
            self._send(200, page_review("找不到這筆(可能已被處置)"))
            return
        norm = buckets.norm(f.get("norm_name") or e["decision"]["name"])
        mapping = f.get("mapping") or ""
        reason = f.get("reason") or "(未填理由)"
        if not mapping.strip():
            self._send(200, page_review("收錄需要指定桶名,已取消"))
            return
        try:
            review.dispose_confirm(
                f["cell_key"], occ, "name", norm, mapping,
                approved_by=os.environ.get("USER", "workbench"),
                approved_at=datetime.datetime.now().isoformat(timespec="seconds"),
                reason=reason)
        except ValueError as err:
            # 最常見的原因:這個名字剛好對到 taxonomy 裡已存在但 mapping 不同
            # 的 rule(new_rule() 的安全檢查)——顯示原因,不准靜靜吞掉。
            self._send(200, page_review(f"收錄失敗,已取消:{err}"))
            return
        self._send(200, page_review(f"已收錄「{e['decision']['name']}」→「{mapping}」"))

    def _dispose_reject(self, f):
        import datetime
        e, occ = _find_review_entry(f["cell_key"], f["occ_id"])
        if e is None:
            self._send(200, page_review("找不到這筆(可能已被處置)"))
            return
        review.dispose_reject(
            f["cell_key"], occ,
            approved_by=os.environ.get("USER", "workbench"),
            approved_at=datetime.datetime.now().isoformat(timespec="seconds"),
            reason=f.get("reason") or "(未填理由)")
        self._send(200, page_review(f"已退回「{e['decision']['name']}」"))

    def _dispose_expand(self, f):
        # 人工擴頁需要 loc(locate.locate 的結果)——工作台先留 API,
        # 實際串接等 workbench 有 PDF 檢視面板時再接,現在先回錯誤說明。
        self._send(200, page_review("人工擴頁目前要在終端機用 core.review.dispose_manual_expand"
                                     " 手動呼叫(需要 locate.locate 的結果),工作台面板尚未串接。"))


def serve(port=DEFAULT_PORT):
    """啟動伺服器,**只綁 127.0.0.1**。"""
    with socketserver.TCPServer((HOST, port), Handler) as httpd:
        print(f"工作台:http://{HOST}:{port}/ (Ctrl+C 結束)")
        httpd.serve_forever()


if __name__ == "__main__":
    import sys
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT)
