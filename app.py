#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**唯一入口**(R4,`docs/plan_v6_一台機器.md`)。

    python3 app.py              起工作台,自動開瀏覽器(雙擊 `啟動.command` 一樣效果)
    python3 app.py serve        同上,不猜 port 用預設 8765
    python3 app.py build --diff 由 facts/ 重算,只印差異不寫檔
    python3 app.py build --write 由 facts/ 重算,寫 data.json
    python3 app.py migrate      facts/*.json → facts.db(R1 三張表)
    python3 app.py export       facts.db → facts/*.json(重新匯出快照)
    python3 app.py fetch        抓最新財報(需要台灣網路,TWSE 擋雲端 IP)

⚠️ **範圍是「日常會用到的操作」,不是全部 26 支帶 `__main__` 的腳本收編。**
手術式地把每一支的功能塞進子命令,對著大多數已經死掉或只在特定研究情境
用一次的腳本(`analyze_oci_div.py`、`compare_v3_v4.py`、`score_golden.py`…)
是製造工作,不是讓工具更好用。**這支收的是使用者真的會敲的四件事**:
開網頁、重建發布、換儲存後端、抓新資料。其餘腳本仍然可以個別
`python3 xxx.py` 執行(開發 / 研究情境),只是不重複收進這裡的選單。

`server.py`/`build.py`/`db.py`/`resolve.py` 各自的邏輯**一行都沒搬過來**——
這支只是分派,真正的實作留在原地,方便直接用那些檔案除錯。
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


def cmd_serve(args):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import server

    port = args.port or server.PORT
    url = f"http://{server.HOST}:{port}"

    if not args.no_browser:
        def _open():
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    print(f"工作台 → {url}    (Ctrl-C 停)")
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer((server.HOST, port), server.Handler).serve_forever()


def cmd_build(args):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import build
    argv = []
    if args.write:
        argv.append("--write")
    elif args.diff:
        argv.append("--diff")
    raise SystemExit(build.main(argv))


def cmd_migrate(args):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import db
    try:
        r = db.migrate_from_json(force=args.force)
    except RuntimeError as e:
        print(f"✗ {e}")
        raise SystemExit(1)
    print(f"匯入 {r['cells']} 格 → {r['db']}")


def cmd_export(args):
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import db
    docs = db.export_json()
    print(f"匯出 {len(docs)} 份文件到 facts/")


def cmd_fetch(args):
    # 走 subprocess,不 import resolve.py 的內部函式 —— 那支的 CLI 邏輯直接寫在
    # `if __name__=="__main__":` 底下,沒有包成 main(),import 會直接執行整段。
    py = sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "resolve.py")], cwd=ROOT)
    raise SystemExit(r.returncode)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="app.py", description="銀行債券投資分析工具 —— 唯一入口")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("serve", help="起工作台(預設動作)")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true", help="不自動開瀏覽器")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("build", help="由 facts/ 重算發布資料")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--diff", action="store_true", help="只印差異,不寫檔(預設)")
    g.add_argument("--write", action="store_true", help="寫 data.json")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("migrate", help="facts/*.json → facts.db")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("export", help="facts.db → facts/*.json")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("fetch", help="抓最新財報(需要台灣網路)")
    p.set_defaults(fn=cmd_fetch)

    a = ap.parse_args(argv)
    if not a.cmd:
        # 不帶子命令 = 雙擊執行的行為:直接開工作台。
        a.cmd, a.fn = "serve", cmd_serve
        a.port, a.no_browser = None, False
    a.fn(a)


if __name__ == "__main__":
    main()
