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
import mimetypes
import os
import subprocess
import sys
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docid
import fill
import locate
from core import webdata

HOST = "127.0.0.1"
PORT = 8765
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "web")
#: 分析頁(make_web.py 的產出,GitHub Pages 那份)。跟 SITE 是不同目錄 ——
#: site/ 在 .gitignore 裡,是建置產物,不能跟手寫原始碼混在一起發。
ANALYSIS_DIR = os.path.join(ROOT, "site")
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")

# 載入 .env(主要為 DEEPSEEK_API_KEY)——用純標準庫,不加 python-dotenv 相依。
_ENV_PATH = os.path.join(ROOT, ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

#: 頁面圖快取。render 一頁約 0.3s,同一頁會被反覆看,不快取會很鈍。
_PNG = {}

# ── 自動抄列的背景工作 ────────────────────────────────────────────────
# **一次只准跑一個**。兩份 `fill_auto` 同時跑會同時改 facts/ 與 work/pending.json,
# 誰贏看時序 —— 這裡用 `_JOB["running"]` 擋掉,不是為了介面好看。
# 業務邏輯仍然不在這層:這裡只負責「開執行緒、收 stdout、回進度」。
_JOB = {"running": False, "lines": [], "done": None, "error": None, "cancel": False}


def cancel_job():
    """只設旗標,不殺執行緒 —— fill_auto/_fetch_run 在每輪迴圈開頭自己看旗標
    停下來,才不會停在寫 facts/ 寫到一半那個當口。"""
    if not _JOB["running"]:
        return {"cancelled": False, "why": "現在沒有在跑的工作"}
    _JOB["cancel"] = True
    return {"cancelled": True}


def _fetch_run(targets, then_fill, reader):
    """抓一批檔,抓到的接著抄。**抓完一定重建 index** —— 新 PDF 不進 index,
    矩陣就還是看不到它,使用者會以為抓失敗了。"""
    import contextlib

    import fill
    import fill_auto
    from core import acquire

    ok = []
    for n, t in enumerate(targets, 1):
        if _JOB["cancel"]:
            print(f"\n使用者取消 —— 停在 {n - 1}/{len(targets)}。")
            break
        print(f"[{n}/{len(targets)}] 抓 {t['period']} {t['code']} ...", end=" ")
        r = acquire.fetch_one(t["period"], t["code"])
        print(r["status"] + ("" if r["status"] == "ok" else f"({r.get('why', '')})"))
        if r["status"] == "ok":
            ok.append(acquire.doc_name(t["period"], t["code"]))

    if ok:
        print(f"\n抓到 {len(ok)} 份,重建索引…")
        fill._build_index()
        if then_fill:
            print("接著抄列:")
            for doc in ok:
                for cls in ("Trading", "OCI", "AC"):
                    fill_auto.run_key(f"{doc}|{cls}", reader)
    print(f"\n完成:{len(ok)}/{len(targets)} 抓到。")


def _job_run(limit, reader, cell=None, fetch=None, then_fill=False):
    import contextlib

    import fill_auto

    buf = io.StringIO()

    class _Tee(io.TextIOBase):
        """邊收邊給前端看 —— 全部跑完才吐一次的話,幾十分鐘畫面是死的。"""
        def write(self, s):
            buf.write(s)
            for line in s.splitlines():
                if line.strip():
                    _JOB["lines"].append(line)
            return len(s)

    try:
        with contextlib.redirect_stdout(_Tee()):
            if fetch:
                _fetch_run(fetch, then_fill, reader)
            elif cell:
                # v4 讀取與分流:完全走純 LLM (Claude/DeepSeek) + 純 Witness 驗證
                doc_key, cls_key = cell.split("|", 1)
                model_used = reader if reader in ("claude", "deepseek") else "claude"
                from v4 import ledger as v4_ledger
                from v4 import reader as v4_reader
                print(f"[v4] 開始讀取 {doc_key} (模型: {model_used})...")
                ok, info = v4_reader.run_doc(doc_key, model=model_used, force=True)
                print(f"[v4] 讀取結果: {'OK' if ok else 'FAIL'} - {info}")
                if ok:
                    print(f"[v4] {doc_key} Witness 驗證與分流計算完成。")
                    # GREEN 的格直接歸檔進 `facts/`(A-1 的接縫)。
                    # **不再呼叫 `ledger.ratify()`** —— 那支 R0-3 已退場,
                    # 而且「機器自動入帳」本來就不該叫 ratify:ratify 的語意是
                    # 「人看過原始頁了」,機器沒有資格蓋那個章(`_src` 只給人工出口)。
                    res = v4_ledger.file_green(docs=[doc_key])
                    for k in res.get("filed", []):
                        print(f"[v4] {k} Witness 判定 GREEN → 已歸檔進 facts/")
                    for k, why in res.get("skipped", []):
                        print(f"[v4] {k} 未歸檔:{why}")
            else:
                fill_auto.run_queue(reader, limit, stop_check=lambda: _JOB["cancel"])
        _JOB["done"] = True
    except Exception:
        _JOB["error"] = traceback.format_exc()
        _JOB["lines"].append("ERROR " + traceback.format_exc().splitlines()[-1])
    finally:
        _JOB["running"] = False


def start_autofill(limit=None, reader="claude", cell=None,
                   fetch=None, then_fill=False):
    """抓檔與抄列**共用同一個背景工作槽**。不是偷懶:兩者都會動 pdf_cache/index/
    facts,同時跑就是誰贏看時序 —— 一個槽就是一道天然的互斥。"""
    import threading
    if _JOB["running"]:
        return {"started": False, "why": "已經有一個在跑了"}
    _JOB.update(running=True, lines=[], done=None, error=None, cancel=False)
    threading.Thread(target=_job_run, args=(limit, reader, cell, fetch, then_fill),
                     daemon=True).start()
    return {"started": True}


# ── 重建:facts/ → data.json → site/(前台看的東西) ────────────────────
# 跟抄列**共用同一個 `_JOB` 槽**(見上)——build.py 會讀 facts/,跟抄列同時跑
# 會讀到寫一半的東西。這裡不是另開一套鎖,是借同一道天然互斥。

def _run_step(cmd, label):
    _JOB["lines"].append(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line:
            _JOB["lines"].append(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"{label} 失敗(exit {proc.returncode})")


def _job_rebuild():
    try:
        _run_step([VENV_PY, "build.py", "--write"], "build.py")
        # make_web.py 一定要用 .venv 的 python —— 系統 python3 沒裝 matplotlib,
        # 用錯的話不是報錯,是靜靜地不動 site/(見 docs/web_redesign_plan.md)。
        _run_step([VENV_PY, "make_web.py"], "make_web.py")
        _JOB["lines"].append("重建完成。")
        _JOB["done"] = True
    except Exception:
        _JOB["error"] = traceback.format_exc()
        _JOB["lines"].append("ERROR " + traceback.format_exc().splitlines()[-1])
    finally:
        _JOB["running"] = False


def start_rebuild():
    import threading
    if _JOB["running"]:
        return {"started": False, "why": "已經有一個在跑了(抄列或重建)"}
    _JOB.update(running=True, lines=[], done=None, error=None, cancel=False)
    threading.Thread(target=_job_rebuild, daemon=True).start()
    return {"started": True}


class PageError(ValueError):
    """`render_png` 認得出來的錯——訊息直接給使用者看。跟裸的 pdfium 例外分開,
    是為了讓 `/page.png` 能回 4xx 帶原因,而不是三種完全不同的成因
    (頁碼超範圍 / PDF 不存在 / pdfium 本身出事)在畫面上長得一模一樣
    (都是一張裂圖,見 plan_web_usable.md §0)。"""


def render_png(doc, page):
    """PDF 的一頁 → PNG bytes。`page` 是 0-based,與 facts 的 source_page 同制。"""
    hit = _PNG.get((doc, page))
    if hit:
        return hit
    path = f"pdf_cache/{doc}.pdf"
    if not os.path.exists(path):
        raise PageError(f"找不到這份 PDF:{doc}.pdf 不在 pdf_cache/ 裡。")
    import pypdfium2 as pdf
    # 跟 locate.locate() 共用同一把鎖(見 locate.py):pdfium 不是 thread-safe,
    # 這支常常跟 /api/doc 同時被前端打(文件頁一開就兩個一起發),不鎖會讓
    # process 直接崩潰,不是丟例外。
    with locate.PDFIUM_LOCK:
        d = pdf.PdfDocument(path)
        n = len(d)
        if not (0 <= page < n):
            raise PageError(f"頁碼超出範圍——{doc}.pdf 共 {n} 頁(page={page})。")
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

    def end_headers(self):
        # `web/` 底下是還在改的前端(workbench.js/html),沒有這行瀏覽器會
        # 用啟發式快取(RFC 7234 §4.2.2)把舊版 JS 留著,改完程式碼、重新整理
        # 都還是跑舊的——實測抓到:改完 workbench.js 加 sticky 版面,重新整理
        # 十幾次都還是舊行為,`fetch()` 直接比對才發現瀏覽器根本沒有重新要過檔案。
        # 這支是本機工作台,不是要給外部用戶端快取的靜態站,不需要任何快取。
        self.send_header("Cache-Control", "no-store")
        self.send_header("Clear-Site-Data", '"cache"')
        super().end_headers()

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

    def _handle_upload(self):
        """R2-1:拖一份 PDF 進來。回傳 `{doc, dup, new}`。

        **doc id 沿用現有命名慣例**(`{YYYYMM}_{銀行名}_{個體|合併}.pdf`,
        `resolve.py` 抓檔用的同一套)——這個 repo 現在唯一會讀
        `pdf_cache/{doc}.pdf` 的下游(`v4/reader.run_doc`、`locate.locate`、
        `report.cell_of`)全部假設這個形狀。`?doc=` 由前端從檔名去掉副檔名
        帶來;不符合形狀就直接拒絕,不猜測、不硬湊。

        ⚠️ **檔名上的口徑只是標籤,封面才是權威。** 存檔之後立刻用
        `locate.basis_of()` 讀封面比對,不一致就**拒收並刪掉剛寫的檔** ——
        那通常代表拖錯檔(例如把合併報表命名成個體),讓它進去會在
        發布網格上錯位一整格,而且沒有任何下游檢查看得到。
        """
        q = self._q()
        doc = (q.get("doc") or "").strip()
        if not docid.is_valid(doc):
            raise PageError(
                f"doc 參數 {doc!r} 不符合命名慣例 YYYYMM_銀行名_個體或合併"
                f"(例:202502_富邦_個體)。")

        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise PageError("沒有檔案內容(Content-Length 是 0)。")
        if n > 200 * 1024 * 1024:
            raise PageError(f"檔案太大({n} bytes,上限 200MB)——這不像一份財報。")
        raw = self.rfile.read(n)
        if raw[:5] != b"%PDF-":
            raise PageError("這不是 PDF(檔頭不是 %PDF-)。")

        import hashlib
        import db as db_mod
        sha = hashlib.sha256(raw).hexdigest()

        existing = db_mod.find_document_by_sha256(sha)
        if existing:
            return {"doc": existing, "dup": True, "new": False,
                    "note": f"內容跟已登記的 {existing} 完全相同,沒有重複存檔。"}

        pdf_path = os.path.join(ROOT, "pdf_cache", f"{doc}.pdf")
        is_overwrite = os.path.exists(pdf_path)
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        with open(pdf_path, "wb") as f:
            f.write(raw)

        # 封面 vs 檔名標籤。**封面是權威**(`docid.py` 檔頭)。不一致就把剛
        # 寫進去的檔刪掉再拒收 —— 留著會變成一份「名字說個體、內容是合併」
        # 的檔,而下游一律信封面,於是它在網格上永遠對不到任何一格,
        # 看起來就只是「這期沒抄」。
        # **讀不到 ≠ 不一致**(鐵律 9)。PDF 打不開、或封面是掃描影像判不出
        # 口徑時,我們無法「證明」檔名標錯了 —— 這種情況照收,讓後面的
        # reader 在看得見的地方失敗,而不是在這裡用一個猜測擋掉真的檔。
        try:
            cover = locate.locate(pdf_path).basis
        except Exception:                                    # noqa: BLE001
            cover = None
        mismatch = docid.verify_basis(doc, cover)
        if mismatch:
            os.remove(pdf_path)
            raise PageError(mismatch)

        db_mod.register_document(doc, sha)
        return {"doc": doc, "dup": False, "new": not is_overwrite,
                "note": f"已存成 pdf_cache/{doc}.pdf" + ("(覆蓋舊檔)" if is_overwrite else "")}

    def _q(self):
        return dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.path).query))

    # ------------------------------------------------------------------ GET --
    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        if route == "/analysis":
            # 導進工作台的殼,**不是**直接發分析頁(2026-08-10 改)。
            # 舊做法讓網址落在 /site/index.html —— 那頁自己有一條 <header>,
            # 於是「從工作台點分析」看到兩條導覽列疊著、「直接開 /analysis」
            # 又看到一條完全不同樣式的,四個頁面像四個網站。
            # 現在分析頁只在殼裡出現(工作台 #/analysis 用 iframe 掛),
            # iframe 內的 appnav.js 會自己不畫(見該檔開頭的 window.self 判斷)。
            # `/site/index.html` 仍可直接取用 —— iframe 就是走那個路徑,
            # 而 GitHub Pages 發布的也是同一份、單檔可攜。
            self.send_response(302)
            self.send_header("Location", "/workbench.html#/analysis")
            self.end_headers()
            return
        if route == "/generic.html":
            # R3:通用視覺化層現算現吐,不落地成檔案——`data.json` 一改,
            # 這頁就跟著變,不會有「忘記重跑」的落地檔跟真資料不同步問題。
            try:
                import schema as schema_mod
                import viz_generic
                s = schema_mod.load(os.path.join(ROOT, "schema.yaml"))
                d = schema_mod.load_data(os.path.join(ROOT, "data.json"))
                table = {"wide": d.get("wide") or {}, "wide_cost": d.get("wide_cost") or {}}
                html = viz_generic.render(s, d.get("periods") or [], table)
            except Exception:
                self._json({"error": traceback.format_exc().splitlines()[-1]}, 500)
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route.startswith("/site/"):
            return self._serve_analysis_file(route[len("/site/"):])
        if not (route.startswith("/api/") or route == "/page.png"):
            if route == "/":
                self.path = "/workbench.html"
            return super().do_GET()
        try:
            self._get(route)
        except PageError as e:
            # 認得出來的錯(頁碼超範圍 / PDF 不見)——回 4xx 帶乾淨訊息,不要
            # traceback:前端要能把這句話直接印在裂圖旁邊(見 workbench.js)。
            self._json({"error": str(e)}, 404)
        except Exception:
            traceback.print_exc()
            self._json({"error": traceback.format_exc()}, 500)

    def _serve_analysis_file(self, rel):
        """發 site/ 底下的檔(分析頁 + 它的圖/xlsx)。跟 SimpleHTTPRequestHandler
        的 directory=SITE 是分開的一套,因為 site/ 不是 web/ 的子目錄。"""
        rel = urllib.parse.unquote(rel) or "index.html"
        path = os.path.normpath(os.path.join(ANALYSIS_DIR, rel))
        if not path.startswith(ANALYSIS_DIR) or not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _get(self, route):
        q = self._q()
        if route == "/page.png":
            try:
                page = int(q["page"])
            except (KeyError, ValueError):
                raise PageError(f"頁碼格式不對:{q.get('page')!r}(要是整數)。")
            png = render_png(q["doc"], page)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
        elif route == "/api/overview":
            self._json(webdata.overview(q.get("basis")))
        elif route == "/api/buckets":
            import config
            self._json(config.BUCKETS)
        elif route == "/api/cell":
            self._json(webdata.cell_detail(q["key"]))
        elif route == "/api/pending":
            self._json(webdata.pending_entries())
        elif route == "/api/queue":
            self._json(webdata.queue_view())
        elif route == "/api/todo":
            self._json(webdata.todo_cells())
        elif route == "/api/fill":
            self._json(webdata.fill_context(q["doc"], q["cls"]))
        elif route == "/api/doc":
            self._json(webdata.doc_detail(q["doc"]))
        elif route == "/api/sim":
            # 定位空間(web/sim.html)。取數一律在 sim/,這裡只轉 JSON。
            from sim import axes as sim_axes
            self._json(sim_axes.payload())
        elif route == "/api/bucketview":
            self._json(webdata.bucket_view())
        elif route == "/api/fetchlog":
            self._json(webdata.fetch_log())
        elif route == "/api/pagetext":
            self._json(webdata.pagetext(q["doc"], q.get("q", "")))
        elif route == "/api/autofill/status":
            self._json({"running": _JOB["running"], "lines": _JOB["lines"],
                        "done": _JOB["done"], "error": _JOB["error"],
                        "cancel": _JOB["cancel"]})
        elif route == "/api/publish_status":
            self._json(webdata.publish_status())
        elif route == "/api/v4/overview":
            from v4 import ledger
            self._json(ledger.load_all())
        elif route == "/api/v4/queue":
            from v4 import ledger
            self._json(ledger.review_queue())
        elif route == "/api/v4/cell":
            from v4 import ledger
            cells = ledger.classify(q["doc"])
            if cells is None:
                raise PageError(f"{q['doc']} 還沒有 v4 讀取結果(v4/raw/ 找不到)。")
            self._json(cells.get(q["cls"]))
        elif route == "/api/v4/run":
            # 列出 pdf_cache/ 裡可讀的份,並帶上是否已讀過(v4/raw/ 有沒有對應 .json)
            import glob
            pdf_dir = os.path.join(ROOT, "pdf_cache")
            raw_dir = os.path.join(ROOT, "v4", "raw")
            docs = []
            for p in sorted(glob.glob(os.path.join(pdf_dir, "*.pdf"))):
                doc = os.path.basename(p)[:-4]
                done = os.path.exists(os.path.join(raw_dir, f"{doc}.json"))
                # 讀達成的已有模型資訊
                model_used = None
                if done:
                    try:
                        import json as _j
                        with open(os.path.join(raw_dir, f"{doc}.json"), encoding="utf-8") as _f:
                            model_used = _j.load(_f).get("model")
                    except Exception:
                        pass
                docs.append({"doc": doc, "done": done, "model": model_used})
            self._json(docs)
        else:
            self._json({"error": "no such endpoint"}, 404)

    # ----------------------------------------------------------------- POST --
    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        if route == "/api/upload":
            # **在 `_body()` 之前特判**——上傳的是 PDF 的原始 bytes,不是 JSON,
            # 走 `_body()` 會直接 json.loads() 炸掉。doc id 走 query string
            # (`?doc=...`),body 全部是檔案內容。
            try:
                self._json(self._handle_upload())
            except PageError as e:
                self._json({"error": str(e)}, 400)
            except Exception:
                self._json({"error": traceback.format_exc().splitlines()[-1]}, 500)
            return
        try:
            b = self._body()
            if route == "/api/dispose":
                self._json(webdata.confirm_bucket(
                    b["name"], b["bucket"], b.get("reason") or ""))
            elif route == "/api/requeue":
                self._json(webdata.requeue(b["cell_key"]))
            elif route == "/api/rebucket":
                self._json(webdata.rebucket(b["name"], b["to"],
                                            bool(b.get("global"))))
            elif route == "/api/fetch":
                self._json(start_autofill(reader=b.get("reader") or "claude",
                                          fetch=b["targets"],
                                          then_fill=bool(b.get("then_fill"))))
            elif route == "/api/autofill":
                self._json(start_autofill(b.get("limit"),
                                          b.get("reader") or "claude",
                                          b.get("cell")))
            elif route == "/api/rebuild":
                self._json(start_rebuild())
            elif route == "/api/autofill/cancel":
                self._json(cancel_job())
            elif route == "/api/submit":
                self._json(submit(b["doc"], b["cls"], b["pages"], b["records"]))
            elif route == "/api/row":
                self._json(webdata.edit_row(
                    b["doc"], b["cls"], b["record_index"], b.get("row_index"),
                    b.get("row"), b["why"]))
            elif route == "/api/ratify":
                self._json(webdata.ratify(b["doc"], b["cls"], b["records"], b.get("why")))
            elif route == "/api/cellmeta":
                self._json(webdata.set_cellmeta(
                    b["doc"], b["cls"], b["field"], b["value"], b["why"]))
            elif route == "/api/cellmeta/clear":
                self._json(webdata.clear_cellmeta(b["doc"], b["cls"], b["field"]))
            elif route == "/api/v4/ratify":
                # **只有一個 ratify**(R0-3):`webdata.ratify` 寫 `facts/`、蓋 `_src`、
                # append-only。v4 這邊只負責把 raw 轉成 records,不自己存一份。
                from v4 import ledger
                recs = ledger.records_of(b["doc"], b["cls"])
                if not recs:
                    raise PageError(f"{b['doc']}|{b['cls']} 沒有可歸檔的資料"
                                    f"(v4/raw 讀不到這一格)。")
                self._json(webdata.ratify(b["doc"], b["cls"], recs,
                                          why=b.get("reason"),
                                          by=b.get("by") or "user"))
            elif route == "/api/v4/requeue":
                # 撤銷改走既有的單一出口(清掉 work/ 的標記檔),不再動 v4/ledger。
                self._json(webdata.requeue(f"{b['doc']}|{b['cls']}"))
            elif route == "/api/v4/run":
                # 背景跑 reader。共用 _JOB 槽(同一時間只能跑一個之工)。
                doc_run = b.get("doc", "")
                model_run = b.get("model", "claude")
                force_run = bool(b.get("force", False))
                if not doc_run:
                    raise PageError("缺少 doc 參數")
                if model_run not in ("claude", "deepseek"):
                    raise PageError(f"model 只能是 'claude' 或 'deepseek',收到: {model_run!r}")
                if _JOB["running"]:
                    self._json({"started": False, "why": "已經有一個也在跑了"})
                    return
                import threading
                def _run_reader_job():
                    import traceback as _tb
                    from v4 import reader as _rdr
                    _JOB["lines"].append(f"[v4.reader] 開始讀 {doc_run}(模型:{model_run}, force:{force_run})")
                    try:
                        ok, info = _rdr.run_doc(doc_run, model=model_run, force=force_run)
                        _JOB["lines"].append(f"[v4.reader] {'OK' if ok else 'FAIL'}  {info}")
                        _JOB["done"] = ok
                    except Exception:
                        _JOB["error"] = _tb.format_exc()
                        _JOB["lines"].append("ERROR " + _tb.format_exc().splitlines()[-1])
                    finally:
                        _JOB["running"] = False
                _JOB.update(running=True, lines=[], done=None, error=None, cancel=False)
                threading.Thread(target=_run_reader_job, daemon=True).start()
                self._json({"started": True, "doc": doc_run, "model": model_run})
            else:
                self._json({"error": "no such endpoint"}, 404)
        except (webdata.EditError, PageError) as e:
            # 使用者可以自己修正的錯(理由沒填、頁碼超範圍)——訊息乾淨,不要
            # traceback,前端才有東西可以直接顯示在紅字條上。
            self._json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            self._json({"error": traceback.format_exc()}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"複核台 → http://{HOST}:{port}    (Ctrl-C 停)")
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
