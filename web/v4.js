// v4 複核台 —— 零框架,獨立於 workbench.js。
// 只做兩個畫面:複核佇列(RED+GREY,人只看這個列表) / 比較表(概覽 + witness 徽章)。
// GREEN/RATIFIED 的格子從不出現在佇列裡 —— 這是 v4 存在的理由(docs/plan_v4_dump.md §六)。

const $ = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; };
const num = (n) => n == null ? "—" : n.toLocaleString();
const esc = (s) => (s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const api = (p) => fetch("/api/v4/" + p).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
const post = (p, b) => fetch("/api/v4/" + p, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(b) })
  .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j; });
// 發布走的是共用端點(不掛 /api/v4/ 前綴)—— 跟 workbench.js 的 runRebuild
// 是同一支 build.py --write + make_web.py,兩個頁面本來就不准同時跑。
const rootApi = (p) => fetch("/api/" + p).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
const rootPost = (p, b) => fetch("/api/" + p, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(b || {}) })
  .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j; });

async function route() {
  document.querySelectorAll("nav a[data-r]").forEach(a => a.classList.remove("on"));
  const h = location.hash.replace(/^#\//, "") || "queue";
  const [page, ...rest] = h.split("/");
  const cur = document.querySelector(`nav a[data-r="${page === "cell" ? "matrix" : page}"]`);
  if (cur) cur.classList.add("on");
  try {
    if (page === "cell") await viewCell(decodeURIComponent(rest[0]), rest[1]);
    else if (page === "matrix") await viewMatrix();
    else if (page === "run") await viewRun();
    else await viewQueue();
  } catch (e) {
    document.getElementById("app").replaceChildren($(`<div class="card">
      <b style="color:var(--danger)">載入失敗</b><div class="hint">${esc(e.message)}</div></div>`));
  }
}
window.addEventListener("hashchange", route);
route();

// ── 發布狀態列 + 重建鈕 —— plan_v5_統一.md P4-1,跟 workbench.js 共用同一顆
// 後端按鈕(/api/rebuild),這裡是 v4 這側原本完全沒有的入口。
document.getElementById("rebuildBtn").onclick = async () => {
  const btn = document.getElementById("rebuildBtn");
  const stat = document.getElementById("rebuildstat");
  if (!confirm("重建會用 facts/ + v4 帳本現有資料重跑 build.py --write + make_web.py,"
    + "直接覆蓋本機的 data.json 與 site/。\n\n"
    + "不會 push、不會發布到 GitHub Pages —— 那一步仍要你自己 git push。\n\n"
    + "確定要重建嗎?")) return;
  const r = await rootPost("rebuild").catch(e => ({ started: false, why: e.message }));
  if (!r.started) { stat.textContent = r.why; return; }
  btn.disabled = true; btn.textContent = "重建中…";
  stat.textContent = "跑 build.py + make_web.py…";
  const t = setInterval(async () => {
    const s = await rootApi("autofill/status").catch(() => null);
    if (!s) return;
    if (s.lines.length) stat.textContent = s.lines[s.lines.length - 1].slice(0, 50);
    if (s.running) return;
    clearInterval(t);
    btn.disabled = false; btn.textContent = "⟳ 重建";
    stat.textContent = s.error
      ? "重建失敗 —— 詳見伺服器終端機。"
      : "重建完成 · " + new Date().toLocaleTimeString("zh-TW", { hour12: false });
  }, 1500);
};

(async () => {
  const stat = document.getElementById("rebuildstat");
  try {
    const s = await rootApi("publish_status");
    if (s.stale) {
      stat.textContent = `⚠ ${s.newer_than_data.join("、")} 比網站新,按重建才會發布`;
      stat.style.color = "var(--danger)";
    }
  } catch (e) { /* 提示而已,不擋主流程 */ }
})();

// ─────────────────────────── 複核佇列 ───────────────────────────

async function viewQueue() {
  const q = await api("queue");
  const el = $(`<div>
    <h1>複核佇列</h1>
    <div class="stats">
      <div class="stat red"><b>${q.red.length}</b><span>RED · 硬閘門不過,擋著不發布</span></div>
      <div class="stat"><b style="color:var(--warn)">${(q.hint||[]).length}</b><span>提示未過 · 會發布,請對圖看一眼</span></div>
      <div class="stat grey"><b>${q.grey.length}</b><span>GREY · 沒有資料</span></div>
    </div>
    ${q.red.length ? `<h2 style="font-size:13px;margin:16px 0 8px">RED —— 按最大差額排序</h2>
      <table class="q" data-red></table>` : ""}
    ${(q.hint||[]).length ? `<h2 style="font-size:13px;margin:16px 0 4px">提示未過 —— 已發布,人工複核</h2>
      <p class="hint" style="margin:0 0 8px">抄錯數字／引錯頁／對不上 BS 這幾類,人翻到原始頁一眼就看得出來,
      所以不擋發布(2026-08-03 裁示)。但**一定要有人看過** —— 這份清單就是那份工作清單。</p>
      <table class="q" data-hint></table>` : ""}
    ${q.grey.length ? `<h2 style="font-size:13px;margin:16px 0 8px">GREY —— 沒有 book,無從驗起</h2>
      <table class="q" data-grey></table>` : ""}
    ${!q.red.length && !q.grey.length && !(q.hint||[]).length ? `<p class="muted">目前沒有需要處理的格子。
      (還沒有資料就會是空的 —— 先用 <code>python3 -m v4.reader &lt;doc&gt;</code> 跑幾份。)</p>` : ""}
  </div>`);
  const mkTable = (rows) => {
    const t = $(`<table class="q"><thead><tr>
      <th>銀行</th><th>期別</th><th>類別</th><th>狀態</th><th>最大差額</th><th>是哪道 witness</th>
    </tr></thead><tbody></tbody></table>`);
    const tb = t.querySelector("tbody");
    rows.forEach(r => {
      const wnames = Object.entries(r.witnesses)
        .filter(([,w]) => w.status !== "OK")
        .map(([k,w]) => `${k}:${w.status}`).join(" · ");
      const tr = $(`<tr class="row">
        <td>${esc(r.bank)}</td><td>${esc(r.period)}</td><td>${esc(r.cls)}</td>
        <td><span class="badge ${r.status}">${r.status}</span></td>
        <td class="diff">${r.max_diff ? num(r.max_diff) : "—"}</td>
        <td class="muted">${esc(wnames)}</td>
      </tr>`);
      tr.onclick = () => location.hash = `#/cell/${encodeURIComponent(r.doc)}/${r.cls}`;
      tb.appendChild(tr);
    });
    return t;
  };
  if (q.red.length) el.querySelector("[data-red]").replaceWith(mkTable(q.red));
  if ((q.hint||[]).length) el.querySelector("[data-hint]").replaceWith(mkTable(q.hint));
  if (q.grey.length) el.querySelector("[data-grey]").replaceWith(mkTable(q.grey));
  document.getElementById("app").replaceChildren(el);
}

// ─────────────────────────── 比較表(概覽) ───────────────────────────

async function viewMatrix() {
  const docs = await api("overview");
  const CLS = ["Trading", "OCI", "AC"];
  const el = $(`<div><h1>比較表</h1><div class="scroll"></div></div>`);
  const wrap = el.querySelector(".scroll");
  const t = $(`<table class="q"><thead><tr>
    <th>文件</th><th>銀行</th><th>期別</th>${CLS.map(c => `<th>${c}</th>`).join("")}
  </tr></thead><tbody></tbody></table>`);
  const tb = t.querySelector("tbody");
  docs.forEach(d => {
    const tr = $(`<tr><td class="muted" style="font-size:11px">${esc(d.doc)}</td>
      <td>${esc(d.bank)}</td><td>${esc(d.period)}</td></tr>`);
    CLS.forEach(cls => {
      const c = d.cells[cls];
      const td = $(`<td></td>`);
      if (c) {
        const badge = $(`<span class="badge ${c.status}" style="cursor:pointer">${c.status}</span>`);
        badge.onclick = () => location.hash = `#/cell/${encodeURIComponent(d.doc)}/${cls}`;
        td.appendChild(badge);
        if (c.book?.total != null) td.appendChild($(`<div class="muted" style="font-size:11px;margin-top:2px">${num(c.book.total)}</div>`));
      } else {
        td.appendChild($(`<span class="muted">—</span>`));
      }
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  wrap.appendChild(t);
  document.getElementById("app").replaceChildren(el);
}

// ─────────────────────────── 單格複核 ───────────────────────────

async function viewCell(doc, cls) {
  const c = await api(`cell?doc=${encodeURIComponent(doc)}&cls=${cls}`);
  if (!c) { document.getElementById("app").replaceChildren($(`<p>找不到這格。</p>`)); return; }
  const book = c.book || {};
  const rows = book.rows || [];
  const page = book.page;

  const el = $(`<div>
    <div class="back"><a href="#/queue" class="muted">← 回複核佇列</a></div>
    <h1>${esc(doc)} · ${esc(cls)}
      <span class="badge ${c.status}" style="margin-left:8px">${c.status}</span>
    </h1>
    <div class="two">
      <div>
        <div class="card">
          <b>逐列(book,p.${page ?? "?"})</b>
          <div class="rows2" data-rows></div>
          <div class="hint">
            printed_subtotal ${num(book.printed_subtotal)} ·
            bs_anchor ${num(book.bs_anchor)} ·
            逐列加總 ${num(rows.reduce((s,r) => s + (r.amount||0), 0))}
          </div>
          ${c.basis === "成本" ? `<div class="hint" style="color:var(--warn)">
            ⚠ 逐項是<b>成本</b>口徑(有評價調整列)——評價調整是一整筆、不分桶,
            所以「逐桶帳面」在這份文件裡不存在。這七桶會發布成 <b>wide_cost</b>,
            帳面(wide)誠實留 null,不是漏抓。
          </div>` : ""}
        </div>
        <div class="card" style="margin-top:12px">
          <b>Witness(程式重算,非模型自報)</b>
          <div class="wl" data-witnesses></div>
          ${c.status !== "RATIFIED" ? `<button class="pri" data-ratify>✓ Ratify(凍結這格)</button>` : `
            <div class="hint">已於 ${esc(c.ratified_at)} 由 ${esc(c.ratified_by)} ratify。</div>
            <button data-requeue>撤銷 ratify</button>`}
        </div>
        ${c.cost ? `<div class="card" style="margin-top:12px">
          <b>成本口徑</b>
          <div class="hint">${esc(c.cost_note || "")}</div>
          ${c.cost.total != null ? `<div class="rows2">${(c.cost.rows||[]).map(r =>
            `<div class="r2"><span class="nm">${esc(r.name)}</span><span class="vl">${num(r.amount)}</span></div>`).join("")}</div>`
            : `<div class="muted">null(此份無取得成本欄)</div>`}
        </div>` : ""}
      </div>
      <div class="card">
        <b>來源頁 p.${page ?? "?"}</b>
        <div class="pgwrap" style="margin-top:8px">
          <img class="pg" src="/page.png?doc=${encodeURIComponent(doc)}&page=${(page||1)-1}">
        </div>
      </div>
    </div>
  </div>`);

  el.querySelector("[data-rows]").replaceChildren(...rows.map(r =>
    $(`<div class="r2"><span class="nm">${esc(r.name)}</span><span class="vl">${num(r.amount)}</span></div>`)));

  // 硬閘門與提示要一眼分得出來 —— 不然「這格 RED 是因為什麼」跟「這格會發布
  // 但有一道沒過」在畫面上長得一樣,那正是降級之後最容易誤讀的地方。
  const HARD = ["check_bucket_complete", "check_basis"];
  const wl = el.querySelector("[data-witnesses]");
  Object.entries(c.witnesses || {}).forEach(([name, w]) => {
    const hard = HARD.includes(name);
    wl.appendChild($(`<div class="w ${w.status}">
      <span class="name">${esc(name)}</span>
      <span class="st">${esc(w.status)}</span>
      <span class="muted" style="font-size:10px">${hard ? "硬閘門" : "提示"}</span>
      ${w.diff ? `<span class="diff">diff ${num(w.diff)}</span>` : ""}
      ${w.note ? `<span class="muted" style="font-size:11px;margin-left:4px">${esc(w.note)}</span>` : ""}
    </div>`));
  });

  const rb = el.querySelector("[data-ratify]");
  if (rb) rb.onclick = async () => {
    try { await post("ratify", {doc, cls}); route(); }
    catch (e) { alert(e.message); }
  };
  const rq = el.querySelector("[data-requeue]");
  if (rq) rq.onclick = async () => {
    if (!confirm("撤銷 ratify?這格會回到複核佇列重新分流。")) return;
    await post("requeue", {doc, cls}); route();
  };

  document.getElementById("app").replaceChildren(el);
}

// ─────────────────────────── 讀取管理頁 ───────────────────────────

let _runModel = "claude"; // 全域選擇的模型
let _pollTimer = null;

async function viewRun() {
  const docs = await api("run");
  const done = docs.filter(d => d.done).length;
  const el = $(`<div>
    <h1>讀取管理</h1>
    <div class="hint" style="margin-bottom:12px">選擇模型後按「跑」,背景呼叫 LLM 讀取整份 PDF → 存 v4/raw/{doc}.json</div>

    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
      <span style="font-size:13px;color:var(--dim)">模型</span>
      <span class="mdsel">
        <button data-m="claude" class="on">Claude</button>
        <button data-m="deepseek">DeepSeek</button>
      </span>
      <span class="muted" style="font-size:12px">Claude = 本機 CLI &nbsp;·&nbsp; DeepSeek = API(~$0.02/份)</span>
      <span style="margin-left:auto;font-size:12px;color:var(--mute)">
        已讀 <b style="color:var(--fg)">${done}</b> / ${docs.length} 份
      </span>
    </div>

    <div data-log class="tr" style="display:none;min-height:60px;max-height:200px;overflow:auto;margin-bottom:12px"></div>

    <table class="q" style="width:100%">
      <thead><tr>
        <th>文件</th><th>狀態</th><th>上次模型</th><th></th>
      </tr></thead>
      <tbody data-tbody></tbody>
    </table>
  </div>`);

  // 模型切換
  el.querySelectorAll(".mdsel button").forEach(btn => btn.onclick = () => {
    el.querySelectorAll(".mdsel button").forEach(b => b.classList.remove("on"));
    btn.classList.add("on");
    _runModel = btn.dataset.m;
  });
  // 還原上次選擇
  el.querySelectorAll(".mdsel button").forEach(b => {
    b.classList.toggle("on", b.dataset.m === _runModel);
  });

  const logEl = el.querySelector("[data-log]");
  const tbody = el.querySelector("[data-tbody]");

  function startLog() {
    logEl.style.display = "";
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      const s = await api("../autofill/status").catch(() => null);
      if (!s) return;
      logEl.textContent = s.lines.join("\n") || "(等待輸出…)";
      logEl.scrollTop = logEl.scrollHeight;
      if (!s.running) {
        clearInterval(_pollTimer);
        _pollTimer = null;
        // 重新整理表格
        const fresh = await api("run").catch(() => null);
        if (fresh) rebuildRows(fresh);
      }
    }, 800);
  }

  function rebuildRows(list) {
    tbody.innerHTML = "";
    list.forEach(d => {
      const tr = $(`<tr>
        <td class="muted" style="font-size:11px">${esc(d.doc)}</td>
        <td>${d.done
          ? `<span class="badge GREEN">已讀</span>`
          : `<span class="badge GREY">未讀</span>`}</td>
        <td class="muted" style="font-size:12px">${d.done ? (d.model || "—") : "—"}</td>
        <td style="text-align:right">
          <button class="run-btn${d.done ? "" : " pri"}" data-doc="${esc(d.doc)}">
            ${d.done ? "重跑" : "跑"}
          </button>
        </td>
      </tr>`);
      tbody.appendChild(tr);
    });
    // 綁按鈕
    tbody.querySelectorAll(".run-btn").forEach(btn => btn.onclick = async () => {
      const doc = btn.dataset.doc;
      const force = btn.textContent.trim() === "重跑";
      btn.disabled = true;
      btn.textContent = "跑中…";
      try {
        const r = await post("run", { doc, model: _runModel, force });
        if (!r.started) { alert(r.why || "啟動失敗"); btn.disabled = false; btn.textContent = force ? "重跑" : "跑"; return; }
        startLog();
      } catch(e) {
        alert(e.message);
        btn.disabled = false;
        btn.textContent = force ? "重跑" : "跑";
      }
    });
  }

  rebuildRows(docs);
  document.getElementById("app").replaceChildren(el);
}
