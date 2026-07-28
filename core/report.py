# -*- coding: utf-8 -*-
"""C4:`verdict + decisions → 本機報表產物`(`docs/plan_local_first.md` §4.2)。

    core.report.build_report(cells, ...)  → (report_dict, manifest_dict)
    core.report.write(out_dir, ...)        → out/report/{index.html,report.json,manifest.json}

**local-first 的核心裁示(§5.1):not confirmed 是顯示狀態,不是隱藏條件。**
舊發布模型(`build.py`)只在 v3 六道檢查全過**且**分類全通得過時才覆寫數字,
其餘沿用凍結快照(v2)。這裡不這麼做——**只要算術三段恆等式成立,數字就
出現在報表裡**,不因為 Decision 還停在 PROVISIONAL/UNCLASSIFIED 就消失;
狀態改用 `core/publish_gate.py` 的 `coarse_status` 標成看得見的記號。

真正不出現的只有兩種情況,而且都要在 manifest 裡列出理由(第 9 條:
任何跳過都要看得見):
    - holdout(保留集永不進報表)
    - 算術三段恆等式不成立(該格/該口徑在文件裡不存在,或六道檢查沒過)

`cell_of`/`to_yi` 是從 `bridge_v3.py` 搬過來的(§4.3 退場順序:這兩個函式
搬完 `bridge_v3.py` 才能刪,C4 就是搬的時間點)。
"""
import datetime
import glob
import hashlib
import json
import os
import subprocess

import facts as facts_mod
import holdout as holdout_mod
from config import BANKS, WIDE_BUCKETS
from core import decision_store, publish_gate
from core import reconcile as reconcile_mod

OUT_DIR = "out/report"
BASIS_NAMES = {"wide": "帳面", "wide_cost": "成本"}


# ── 搬自 bridge_v3.py(§4.3:搬完才能刪 bridge_v3.py)───────────────────

def to_yi(v):
    """仟元 → 億(1 億 = 100,000 仟元),與既有 wide 一致。"""
    return None if v is None else round(v / 100000)


def cell_of(key):
    """`202404_5843_AI3|OCI` → (`2024H2|兆豐`, `OCI`) 或 None(非個體報表)。"""
    doc, cls = key.split("|")
    yr, per, code, kind = doc[:4], doc[4:6], doc[7:11], doc[12:]
    if kind != "AI3" or code not in BANKS or per not in ("02", "04"):
        return None
    return f"{yr}{'H1' if per == '02' else 'H2'}|{BANKS[code]}", cls


# ── sha256 —— manifest 的可追溯清單要用 ─────────────────────────────────

def _sha_glob(pattern):
    h = hashlib.sha256()
    for p in sorted(glob.glob(pattern)):
        h.update(p.encode())
        h.update(open(p, "rb").read())
    return h.hexdigest()


def _git_rev():
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return rev or None
    except Exception:
        return None


def _decision_id(dec):
    """報表數字要追得回的 id——用 record_fp:row_fp(occurrence 的穩定身分,
    B0 §2.2 定案),**不是另發明一套 id**(D7)。"""
    occ = dec.get("occurrence") or {}
    return f"{occ.get('record_fp')}:{occ.get('row_fp')}"


# ── 建 report ────────────────────────────────────────────────────────────

def build_report(cells, decisions_dir=None, taxonomy_dir="taxonomy"):
    """→ (report, manifest)。`cells` 是 `facts.load()` 的完整輸出
    (含 holdout——本函式自己切,呼叫端不用先切)。"""
    train, leak = holdout_mod.split(cells)
    verdict, audit = reconcile_mod.verify_all(train)

    report = {"帳面": {}, "成本": {}}
    excluded = [{"cell_key": k, "reason": "holdout(保留集永不進報表)"} for k in sorted(leak)]
    coverage = {}  # "basis|bank_period|cls|bucket" → [decision_id, ...]

    for key, v in sorted(verdict.items()):
        got = cell_of(key)
        if got is None:
            continue  # AI1 合併報表,v3 尚無網站格映射,不在本報表範圍
        cell, cls = got
        recs = train[key]
        status = publish_gate.coarse_status(key, recs, decisions_dir, taxonomy_dir)
        decs = publish_gate._decisions_for_cell(key, recs, decisions_dir, taxonomy_dir)
        dec_ids = [_decision_id(d) for d in decs]

        for src_key, basis_cn in BASIS_NAMES.items():
            table = report[basis_cn].setdefault(cell, {})
            book = v.get(src_key)
            if book is None:
                reason = (audit[key].get("basis_gap") or {}).get(basis_cn)
                if reason is None and not v.get("pass"):
                    failed = [k2 for k2, v2 in audit[key]["checks"].items() if v2]
                    reason = f"六道檢查未通過:{'; '.join(failed)}" if failed else "未知原因"
                table[cls] = {"buckets": None, "reason": reason or "該口徑不成立",
                              "status": status, "decision_ids": dec_ids}
                continue
            buckets_yi = {b: to_yi(book.get(b)) for b in WIDE_BUCKETS}
            table[cls] = {"buckets": buckets_yi, "reason": None,
                          "status": status, "decision_ids": dec_ids}
            for b, amt in buckets_yi.items():
                if not amt:
                    continue  # 0 沒有數字需要溯源,不算孤兒,也不需要進 coverage
                # ⚠️ 不能用 "|" 當分隔——`cell` 本身長得像 "2024H2|兆豐",
                # 用 "|" join 會撞出歧義。用 unit separator(\x1f)避開資料裡會出現的字元。
                coverage["\x1f".join((basis_cn, cell, cls, b))] = list(dec_ids)

    archived = sum(1 for k in train if cell_of(k))
    publishable = sum(1 for k in train if cell_of(k)
                      and publish_gate.coarse_status(k, train[k], decisions_dir,
                                                     taxonomy_dir)["publishable"])

    manifest = {
        "run_id": datetime.datetime.now().strftime("%Y%m%dT%H%M%S"),
        "generated_at": datetime.datetime.now().isoformat(),
        "app_version": {"git": _git_rev()},
        "inputs": {
            "facts_sha256": _sha_glob("facts/*.json"),
            "taxonomy_sha256": _sha_glob(f"{taxonomy_dir}/*.json"),
            "decisions_sha256": _sha_glob(f"{decisions_dir or 'decisions'}/*.json"),
            "holdout_sha256": _sha_glob("holdout.py"),
        },
        "coverage": {
            "total_numbers": len(coverage),
            "orphans": [k for k, ids in coverage.items() if not ids],
        },
        "summary": {"archived": archived, "publishable": publishable},
        "excluded": excluded,
    }
    return report, manifest


# ── 落地 ─────────────────────────────────────────────────────────────────

def _render_html(report, manifest):
    """自足的單頁 HTML——CSS/JS 全內嵌,離線可看,不打任何外部請求。"""
    payload = json.dumps({"report": report, "manifest": manifest}, ensure_ascii=False)
    return """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>本機報表</title>
<style>
body{font-family:-apple-system,sans-serif;margin:2rem;background:#0b0d10;color:#e5e7eb}
table{border-collapse:collapse;margin-bottom:2rem;width:100%}
th,td{border:1px solid #333;padding:.4rem .6rem;text-align:right;font-size:.85rem}
th{background:#1a1d22;text-align:left}
td:first-child,th:first-child{text-align:left}
.status-ok{color:#4ade80}.status-warn{color:#facc15}.status-null{color:#666;font-style:italic}
h1{font-size:1.2rem}h2{font-size:1rem;color:#93c5fd}
.meta{color:#888;font-size:.8rem;margin-bottom:1rem}
</style></head><body>
<h1>本機報表</h1>
<div class="meta" id="meta"></div>
<div id="app"></div>
<script id="data" type="application/json">""" + payload + """</script>
<script>
const data = JSON.parse(document.getElementById('data').textContent);
const {report, manifest} = data;
document.getElementById('meta').textContent =
  `run_id=${manifest.run_id} · git=${manifest.app_version.git} · ` +
  `archived=${manifest.summary.archived} publishable=${manifest.summary.publishable} · ` +
  `孤兒數字=${manifest.coverage.orphans.length}`;
const app = document.getElementById('app');
for (const basis of Object.keys(report)) {
  const h = document.createElement('h2');
  h.textContent = basis;
  app.appendChild(h);
  const table = document.createElement('table');
  const buckets = ["GB","公司債","金融債","資產基礎","貨幣市場","其他","股票"];
  table.innerHTML = '<tr><th>格</th><th>類別</th>' +
    buckets.map(b => `<th>${b}</th>`).join('') + '<th>狀態</th></tr>';
  for (const cell of Object.keys(report[basis]).sort()) {
    for (const cls of Object.keys(report[basis][cell])) {
      const entry = report[basis][cell][cls];
      const tr = document.createElement('tr');
      let cells = `<td>${cell}</td><td>${cls}</td>`;
      if (entry.buckets === null) {
        cells += buckets.map(() => '<td class="status-null">—</td>').join('');
        cells += `<td class="status-null">${entry.reason || ''}</td>`;
      } else {
        cells += buckets.map(b => `<td>${entry.buckets[b] ?? ''}</td>`).join('');
        const cls2 = entry.status.publishable ? 'status-ok' : 'status-warn';
        const label = entry.status.publishable ? '可發布' :
          `not confirmed (${entry.status.decisions.confirmed}/${entry.status.decisions.total})`;
        cells += `<td class="${cls2}">${label}</td>`;
      }
      tr.innerHTML = cells;
      table.appendChild(tr);
    }
  }
  app.appendChild(table);
}
</script>
</body></html>"""


def write(out_dir=None, decisions_dir=None, taxonomy_dir="taxonomy"):
    """讀真實 `facts.load()`,寫 `out/report/{report,manifest}.json` + `index.html`。
    **唯一寫 out/report/ 的入口**(§0.2 鐵則 7 的 C4 版本:一個入口)。"""
    out_dir = out_dir or OUT_DIR
    cells = facts_mod.load()
    report, manifest = build_report(cells, decisions_dir, taxonomy_dir)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(
        _render_html(report, manifest))
    return report, manifest


if __name__ == "__main__":
    r, m = write()
    print(f"寫入 {OUT_DIR}/:archived={m['summary']['archived']} "
          f"publishable={m['summary']['publishable']} "
          f"孤兒數字={len(m['coverage']['orphans'])}")
