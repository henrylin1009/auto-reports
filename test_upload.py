#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2-1 驗收(`docs/plan_v6_一台機器.md`):`POST /api/upload`。

**跑真的 server,不是叫 handler 的內部方法。** 上傳這條路的風險全在
HTTP 邊界(raw bytes vs JSON body、Content-Length、multipart 沒有用到但
routing 順序容易錯),那些東西單元測 `_handle_upload()` 測不到 ——
之前手動用 curl 對著真的 8766 preview server 驗證過一輪,這支是把那輪
驗證釘成可以重跑的回歸,同時保證每次都清乾淨(不留垃圾在 pdf_cache/facts.db)。

⚠️ **doc id 用 `999999_測試銀行_個體` 這種明顯是假資料的名字**,不會撞到任何
真實文件,而且一眼看得出是測試殘留(萬一清理失敗,人工也秒懂該刪什麼)。

執行: python3 test_upload.py     exit 0 = 全綠
"""
import http.client
import json
import os
import socket
import threading
import time
import urllib.parse

import server as srv
import db as db_mod

PASS = FAIL = 0
TEST_DOC = "999999_測試銀行_個體"
PDF_BYTES = b"%PDF-1.4\n%test upload fixture\n%%EOF"


def ok(label, detail=""):
    global PASS
    PASS += 1
    print(f"  OK  {label}" + (f"  —— {detail}" if detail else ""))


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {label}: {detail}")


def check(label, cond, detail=""):
    (ok if cond else fail)(label, detail)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _cleanup():
    p = os.path.join("pdf_cache", f"{TEST_DOC}.pdf")
    if os.path.exists(p):
        os.remove(p)
    for other in ("999999_另一家_合併",):
        q = os.path.join("pdf_cache", f"{other}.pdf")
        if os.path.exists(q):
            os.remove(q)
    if db_mod.exists():
        conn = db_mod.connect()
        conn.execute("DELETE FROM documents WHERE doc LIKE '999999_%'")
        conn.commit()
        conn.close()


def _post(conn, path, body, content_type):
    # doc id 現在含中文(銀行名),而 HTTP 請求行必須是 ASCII —— 要百分比編碼。
    # 瀏覽器那邊本來就會編(`web/workbench.js` 用 `encodeURIComponent`),
    # 這裡是把測試對齊真實客戶端的行為,不是為了讓測試過而放寬伺服器。
    path = urllib.parse.quote(path, safe="/?=&")
    conn.request("POST", path, body=body, headers={"Content-Type": content_type})
    r = conn.getresponse()
    data = json.loads(r.read())
    return r.status, data


def main():
    _cleanup()
    port = _free_port()
    httpd = srv.ThreadingHTTPServer((srv.HOST, port), srv.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)

        print("\nU1 上傳一份新文件")
        status, r = _post(conn, f"/api/upload?doc={TEST_DOC}", PDF_BYTES, "application/pdf")
        check("HTTP 200", status == 200, f"實際 {status}")
        check("dup=False, new=True", r.get("dup") is False and r.get("new") is True, r)
        check("檔案真的落地", os.path.exists(f"pdf_cache/{TEST_DOC}.pdf"))
        check("documents 表登記了",
              db_mod.find_document_by_sha256(
                  __import__("hashlib").sha256(PDF_BYTES).hexdigest()) == TEST_DOC)

        print("\nU2 同內容、不同 doc id → 去重,不重複存檔")
        status, r = _post(conn, "/api/upload?doc=999999_另一家_合併", PDF_BYTES, "application/pdf")
        check("回報 dup=True", r.get("dup") is True, r)
        check("回報既有的 doc", r.get("doc") == TEST_DOC, r)
        check("沒有存出第二份檔案",
              not os.path.exists("pdf_cache/999999_另一家_合併.pdf"))

        print("\nU3 doc 參數不符合命名慣例 → 拒絕(不猜、不硬湊)")
        status, r = _post(conn, "/api/upload?doc=not_a_valid_name", PDF_BYTES, "application/pdf")
        check("HTTP 400", status == 400, f"實際 {status}")
        check("錯誤訊息講清楚是命名問題", "命名慣例" in (r.get("error") or ""), r)

        print("\nU4 內容不是 PDF → 拒絕")
        status, r = _post(conn, f"/api/upload?doc={TEST_DOC}", b"not a pdf at all",
                          "application/pdf")
        check("HTTP 400", status == 400, f"實際 {status}")
        check("錯誤訊息講清楚不是 PDF", "PDF" in (r.get("error") or ""), r)
        # U4 用了跟 U1 一樣的 doc id 但內容不是 PDF —— 必須被擋在寫檔之前,
        # 不能覆蓋掉 U1 已經合法存好的那份。這是這條測試存在的理由:
        # 光看「有沒有拒絕」不夠,要連「拒絕了就真的沒有副作用」一起驗。
        check("U1 存好的檔案沒有被 U4 的壞內容覆蓋",
              open(f"pdf_cache/{TEST_DOC}.pdf", "rb").read() == PDF_BYTES)

        print("\nU5 空 body → 拒絕")
        status, r = _post(conn, f"/api/upload?doc={TEST_DOC}", b"", "application/pdf")
        check("HTTP 400", status == 400, f"實際 {status}")

        conn.close()
    finally:
        httpd.shutdown()
        _cleanup()
        check("清理完成:pdf_cache/ 沒有殘留測試檔",
              not os.path.exists(f"pdf_cache/{TEST_DOC}.pdf"))
        check("清理完成:documents 表沒有殘留",
              db_mod.find_document_by_sha256(
                  __import__("hashlib").sha256(PDF_BYTES).hexdigest()) is None)

    print(f"\nPASS {PASS}  FAIL {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
