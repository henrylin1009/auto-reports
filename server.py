# -*- coding: utf-8 -*-
"""複核台的本機網站。零框架、零 CDN,只有標準庫 + 既有模組。

    python3 server.py          → http://127.0.0.1:8765

畫面在 `web/workbench.html` + `web/workbench.js`(手刻 HTML/CSS/JS)。
⚠️ 放 `web/` 不放 `site/`:`site/` 是 `make_web.py` 的**產出**目錄,在 .gitignore 裡,
手寫的原始碼擺進去會靜靜地不進版控。
這支只做兩件事:發靜態檔、把 `core.webdata` 的回傳值轉成 JSON。
**業務邏輯一律不寫在這裡** —— 取數在 `core/webdata.py`,寫入走既有出口
(`fill.cmd_submit` / `webdata.confirm_bucket` / `webdata.requeue`)。

為什麼不是 Streamlit:試過,版面是框架決定的,改不動。手刻的代價是這一層
約 150 行膠水,換到的是版面完全自己控制。
"""
import io
import json
import os
import sys
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fill
from core import webdata

HOST = "127.0.0.1"
PORT = 8765
SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

#: 頁面圖快取。render 一頁約 0.3s,同一頁會被反覆看,不快取會很鈍。
_PNG = {}


def render_png(doc, page):
    """PDF 的一頁 → PNG bytes。`page` 是 0-based,與 facts 的 source_page 同制。"""
    hit = _PNG.get((doc, page))
    if hit:
        return hit
    import pypdfium2 as pdf
    d = pdf.PdfDocument(f"pdf_cache/{doc}.pdf")
    img = d[page].render(scale=1.6).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = buf.getvalue()
    _PNG[(doc, page)] = out
    return out


def submit(doc, cls, pages, data):
    """走 `fill.cmd_submit`,`transcribe.verify()` 六道檢查照跑。
    **不准為了 UI 方便新增任何接受分支** —— 網站與 CLI 必須是同一道閘門。"""
    os.makedirs(fill.WORK_DIR, exist_ok=True)
    json.dump({"doc": doc, "cls": cls, "level": 0, "pages": pages, "retries": 0},
              open(fill.PENDING, "w", encoding="utf-8"))
    cur = os.path.join(fill.WORK_DIR, "current_web.json")
    json.dump(data, open(cur, "w", encoding="utf-8"), ensure_ascii=False)

    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fill.cmd_submit(cur)
    except SystemExit:
        pass
    out = buf.getvalue()
    status = ("PASS" if out.startswith("PASS")
              else "BLOCKED" if out.startswith("BLOCKED") else "FAIL")
    return {"status": status, "output": out}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def log_message(self, *a):
        pass                                  # 預設每個請求印一行,洗版

    # ---------------------------------------------------------------- 工具 --
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _q(self):
        return dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.path).query))

    # ------------------------------------------------------------------ GET --
    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        if not (route.startswith("/api/") or route == "/page.png"):
            if route == "/":
                self.path = "/workbench.html"
            return super().do_GET()
        try:
            self._get(route)
        except Exception:
            traceback.print_exc()
            self._json({"error": traceback.format_exc()}, 500)

    def _get(self, route):
        q = self._q()
        if route == "/page.png":
            png = render_png(q["doc"], int(q["page"]))
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
        elif route == "/api/overview":
            self._json(webdata.overview())
        elif route == "/api/buckets":
            import config
            self._json(config.BUCKETS)
        elif route == "/api/cell":
            self._json(webdata.cell_detail(q["key"]))
        elif route == "/api/pending":
            self._json(webdata.pending_entries())
        elif route == "/api/todo":
            self._json(webdata.todo_cells())
        elif route == "/api/fill":
            self._json(webdata.fill_context(q["doc"], q["cls"]))
        else:
            self._json({"error": "no such endpoint"}, 404)

    # ----------------------------------------------------------------- POST --
    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            b = self._body()
            if route == "/api/dispose":
                self._json(webdata.confirm_bucket(
                    b["name"], b["bucket"], b.get("reason") or ""))
            elif route == "/api/requeue":
                self._json(webdata.requeue(b["cell_key"]))
            elif route == "/api/submit":
                self._json(submit(b["doc"], b["cls"], b["pages"], b["records"]))
            else:
                self._json({"error": "no such endpoint"}, 404)
        except Exception:
            traceback.print_exc()
            self._json({"error": traceback.format_exc()}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"複核台 → http://{HOST}:{port}    (Ctrl-C 停)")
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
