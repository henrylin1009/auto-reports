"use strict";
// 複核台前端:零框架、零 CDN。只跟 /api/* 說話,不自己算業務邏輯。
//
// 四個畫面,對應 docs/plan_ui_redesign.md 的 S1-S3 加上核對:
//   #/matrix        總覽矩陣(期別 × 銀行+代碼)
//   #/review/KEY    核對 —— 已抄好的格:左邊數字、右邊來源頁圖
//   #/dispose       裁示 —— 分桶對不到的科目名
//   #/fill/KEY      抄列 —— 還沒抄的格:左邊填 JSON、右邊頁圖
//
// ⚠️ 頁碼一律 0-based(與 facts 的 source_page、locate 的候選頁同制)。
//    畫面上顯示才 +1。不要在別的地方偷偷換算。

const S = { ov: null, buckets: [], cell: null, page: null, rowIdx: 0,
            pending: [], todo: [] };

const $ = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n) => n == null ? "—" : Number(n).toLocaleString("en-US");
const api = (p) => fetch("/api/" + p).then(r => r.json());
const post = (p, b) => fetch("/api/" + p, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(b)
}).then(r => r.json());

async function boot() {
  [S.ov, S.buckets] = await Promise.all([api("overview"), api("buckets")]);
  addEventListener("hashchange", route);
  addEventListener("keydown", onKey);
  route();
}

function nav(r) {
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.r === r));
  const st = S.ov.stats;
  document.getElementById("navstat").textContent =
    `已抄 ${st.done} · 待抄 ${st.todo} · 卡住 ${st.blocked}`;
}

function route() {
  const parts = location.hash.replace(/^#\//, "").split("/");
  const r = parts[0] || "matrix";
  nav(r);
  if (r === "buckets") viewBuckets();
  else if (r === "review") viewReview(decodeURIComponent(parts[1] || ""));
  else if (r === "dispose") viewDispose();
  else if (r === "fill") viewFill(decodeURIComponent(parts[1] || ""));
  else viewMatrix();
}

const CLS = ["AC", "OCI", "Trading"];
const SBAR = { done: "g", todo: "miss", blocked: "w", na: "miss" };

// ── 總覽:期別(列) × 銀行+代碼(欄),一格一份檔 ─────────────────────────
async function viewMatrix() {
  S.ov = await api("overview");
  const { periods, cols, grid, stats } = S.ov;
  nav("matrix");

  const el = $(`<div>
    <h1>總覽 · 2023 起</h1>
    <div class="stats">
      <div class="stat"><b>${stats.done}</b><span>已抄</span></div>
      <div class="stat"><b>${stats.todo}</b><span>待抄</span></div>
      <div class="stat ${stats.blocked ? "w" : ""}"><b>${stats.blocked}</b><span>卡在分類</span></div>
      <div class="stat"><b>${stats.na}</b><span>無候選頁</span></div>
    </div>
    <div class="auto">
      <button class="pri" id="autogo">自動抄列</button>
      <select id="autolim">
        <option value="3">先跑 3 格</option>
        <option value="10">跑 10 格</option>
        <option value="">跑完全部待抄(${stats.todo} 格)</option>
      </select>
      <span class="hint" id="autohint">用 Gemini 抄，六道檢查照跑；對不上的會自動擴頁重試，
        仍過不了就進「卡住」不會寫進事實庫。</span>
    </div>
    <pre class="autolog" id="autolog" hidden></pre>
    <div class="scroll"><table class="mx"><tbody></tbody></table></div>
    <p class="hint">一格 = 一份財報檔的三個類別(AC / OCI / Trading)。
      大字是抄到幾類,細條依序是三類的狀態(綠=已抄、黃=卡在分類、灰=還沒抄)。
      空白代表那期沒有這份檔 —— 是沒有檔,不是沒抄。</p>
  </div>`);

  wireAutofill(el);

  const tb = el.querySelector("tbody");
  tb.appendChild($(`<tr><th></th>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr>`));

  for (const p of periods) {
    const kind = p.slice(4) === "04" ? "年報" : p.slice(4) === "02" ? "半年報" : "季報";
    const tr = $(`<tr><th>${p.slice(0, 4)} · ${kind}</th></tr>`);
    for (const c of cols) {
      const g = grid[`${p}|${c}`];
      const td = $("<td></td>");
      if (!g) td.appendChild($(`<div class="cell none"><span class="k">—</span></div>`));
      else {
        const st = CLS.map(x => g.classes[x]);
        const done = st.filter(x => x === "done").length;
        const live = st.filter(x => x !== "na").length;
        const blocked = st.includes("blocked");
        const btn = $(`<button class="cell ${blocked ? "pend" : done === live ? "ok" : ""}">
          <span class="k">${done}/${live} 類${blocked ? ' <span class="s warn">⚠</span>' : ""}</span>
          <span class="bars">${CLS.map((x, i) =>
            `<i class="${SBAR[st[i]]}" title="${x}:${st[i]}"></i>`).join("")}</span>
        </button>`);
        btn.onclick = () => openCell(g.doc, g.classes);
        td.appendChild(btn);
      }
      tr.appendChild(td);
    }
    tb.appendChild(tr);
  }
  document.getElementById("app").replaceChildren(el);
}

// ── 分桶檢視:十個桶 × 收進去的名字 ────────────────────────────────────
// 看的是 Decision(這一列實際落在哪),不是 buckets.SYN(規則)。
// 顏色 = 狀態:白=CONFIRMED、黃=PROVISIONAL(機械/LLM 提案,沒人確認過)、
// 紅=UNCLASSIFIED(提不出桶)。拖一張卡到別欄就是改它的桶。
async function viewBuckets() {
  const v = await api("bucketview");
  nav("buckets");
  const t = v.tally;
  const el = $(`<div>
    <h1>分桶 · 每個桶收了哪些科目名</h1>
    <div class="stats">
      <div class="stat"><b>${t.confirmed}</b><span>已確認</span></div>
      <div class="stat ${t.provisional ? "w" : ""}"><b>${t.provisional}</b><span>提案待確認</span></div>
      <div class="stat ${t.unclassified ? "w" : ""}"><b>${t.unclassified}</b><span>還沒有桶</span></div>
    </div>
    <div class="bkcols"></div>
    <p class="hint">一張卡 = 一個科目名在一個桶裡（×N 是出現在幾列）。
      黃卡是提案、還沒人確認；紅卡是提不出桶。拖到別欄可以改桶。
      <b>同名不同桶是正常的</b> —— 同一份附註裡「其他」可能一個在有價證券段、一個在衍生段。</p>
  </div>`);

  const wrap = el.querySelector(".bkcols");
  const mkChip = (g) => {
    const cls = g.state === "PROVISIONAL" ? "prov" : g.state === "UNCLASSIFIED" ? "uncl" : "";
    const c = $(`<div class="chip ${cls}" draggable="true">${esc(g.name)}<b>×${g.n}</b></div>`);
    c.title = `${g.state}\n出現在 ${g.cells.length} 格:\n` + g.cells.join("\n");
    c.ondragstart = (e) => {
      e.dataTransfer.setData("text/plain", JSON.stringify({ name: g.name, from: g.bucket }));
      c.classList.add("drag");
    };
    c.ondragend = () => c.classList.remove("drag");
    return c;
  };

  const mkCol = (title, list, loose) => {
    const col = $(`<div class="bkcol ${loose ? "loose" : ""}">
      <h3>${esc(title)}<span>${list.length}</span></h3></div>`);
    list.forEach(g => col.appendChild(mkChip(g)));
    col.ondragover = (e) => { e.preventDefault(); col.classList.add("over"); };
    col.ondragleave = () => col.classList.remove("over");
    col.ondrop = async (e) => {
      e.preventDefault(); col.classList.remove("over");
      if (loose) return;                       // 不准拖回「還沒有桶」——那不是一個桶
      const d = JSON.parse(e.dataTransfer.getData("text/plain"));
      if (d.from === title) return;
      await moveBucket(d.name, d.from, title);
    };
    return col;
  };

  if (v.unclassified.length) wrap.appendChild(mkCol("還沒有桶", v.unclassified, true));
  for (const b of v.buckets) wrap.appendChild(mkCol(b, v.cols[b] || false));
  document.getElementById("app").replaceChildren(el);
}

// 拖曳落地 —— 選項 C:預設只改「這個名字目前所有出現處的 Decision」,
// 要不要立成全域規則(buckets.SYN)是**另一個動作**,因為那會影響所有文件。
async function moveBucket(name, from, to) {
  const global = confirm(
    `把「${name}」從「${from || "還沒有桶"}」改成「${to}」\n\n` +
    `確定 = 同時立成全域規則(寫進 buckets.SYN,影響所有文件)\n` +
    `取消 = 只改現有這些列的分類紀錄`);
  const r = await post("rebucket", { name, to, global });
  if (r.error) { alert(r.error); return; }
  viewBuckets();
}

// ── 自動抄列:按鈕 + 輪詢進度 ──────────────────────────────────────────
// 後端一次只准跑一個(server._JOB),這裡不自己再管一份狀態 —— 兩份狀態遲早會不一致。
// 跑完自動重畫總覽,因為 stats 已經變了。
function wireAutofill(el) {
  const btn = el.querySelector("#autogo");
  const log = el.querySelector("#autolog");
  const hint = el.querySelector("#autohint");
  let timer = null;

  const paint = (s) => {
    log.hidden = !s.lines.length;
    log.textContent = s.lines.join("\n");
    log.scrollTop = log.scrollHeight;
    btn.disabled = s.running;
    btn.textContent = s.running ? "抄列中…" : "自動抄列";
  };

  const poll = async () => {
    const s = await api("autofill/status");
    paint(s);
    if (s.running) return;
    clearInterval(timer); timer = null;
    hint.textContent = s.error ? "出錯了，詳見下方訊息。"
                               : "跑完了。重畫總覽…";
    if (!s.error) setTimeout(viewMatrix, 1200);
  };

  btn.onclick = async () => {
    const v = el.querySelector("#autolim").value;
    const r = await post("autofill", { limit: v ? Number(v) : null });
    if (!r.started) { hint.textContent = r.why; return; }
    btn.disabled = true; btn.textContent = "抄列中…";
    hint.textContent = "跑起來了。Gemini 每格約 3 秒，擴頁重試會多幾輪。";
    timer = setInterval(poll, 1500);
  };

  // 跑完會重畫總覽,重畫就把紀錄洗掉了 —— 但那正是你要看「剛剛發生什麼」的時候。
  // 後端的 lines 還在,所以有紀錄就畫出來,不是只有 running 才畫。
  api("autofill/status").then(s => {
    if (s.lines.length) paint(s);
    if (s.running) timer = setInterval(poll, 1500);
  });
}

// 點一格 → 去它最該去的地方:有卡住先裁示,其次待抄,再其次核對。
function openCell(doc, classes) {
  for (const c of CLS) if (classes[c] === "blocked") return location.hash = "#/dispose";
  for (const c of CLS) if (classes[c] === "todo") return location.hash = `#/fill/${encodeURIComponent(doc + "|" + c)}`;
  for (const c of CLS) if (classes[c] === "done") return location.hash = `#/review/${encodeURIComponent(doc + "|" + c)}`;
}

// ── 核對:左邊已抄好的數字、右邊來源頁圖 ────────────────────────────────
async function viewReview(key) {
  if (!key) {
    const ov = S.ov;
    const first = Object.values(ov.grid).find(g => CLS.some(c => g.classes[c] === "done"));
    if (!first) return document.getElementById("app").replaceChildren(
      $(`<p class="muted">還沒有抄好的格子。</p>`));
    key = first.doc + "|" + CLS.find(c => first.classes[c] === "done");
    return location.hash = `#/review/${encodeURIComponent(key)}`;
  }

  const d = await api("cell?key=" + encodeURIComponent(key));
  if (!d) return document.getElementById("app").replaceChildren(
    $(`<p class="muted">這格還沒抄。</p>`));
  S.cell = d;
  const page = S.page != null && d.pages.includes(S.page) ? S.page : d.pages[0];
  S.page = page;

  const done = [];
  Object.values(S.ov.grid).forEach(g => CLS.forEach(c => {
    if (g.classes[c] === "done") done.push(g.doc + "|" + c);
  }));
  done.sort();

  const el = $(`<div>
    <div class="bar">
      <h1 style="margin:0">核對</h1>
      <select id="pick">${done.map(k =>
        `<option value="${esc(k)}"${k === key ? " selected" : ""}>${esc(k)}</option>`).join("")}</select>
      <span class="tag">錨 ${num(d.anchor)} 仟元</span>
      <span class="tag">${d.pages.length} 頁證據</span>
    </div>
    <div class="two">
      <div class="card" style="max-height:660px;overflow:auto"><div class="rows" id="rows"></div></div>
      <div>
        <div class="card">
          <div class="bar" style="margin:0 0 8px">
            <span class="muted">來源頁</span>
            <span id="pgs" style="display:flex;gap:4px;flex-wrap:wrap"></span>
          </div>
          <div class="pgwrap"><img class="pg" src="/page.png?doc=${encodeURIComponent(d.doc)}&page=${page}" alt=""></div>
          <div class="hint">頁層級核對,不畫框。點左邊任一列,右邊翻到那列的來源頁。
            <kbd>j</kbd>/<kbd>k</kbd> 上下換列。</div>
        </div>
      </div>
    </div>
  </div>`);

  const rows = el.querySelector("#rows");
  const flat = [];
  d.records.forEach(rec => {
    rows.appendChild($(`<div class="sec">${esc(rec.source_kind)} · p.${rec.source_page + 1}
      <span class="bk">${esc(rec.total_col)} = ${num(rec.printed_total)}</span></div>`));
    let lastG = null;
    rec.rows.forEach(r => {
      if (r.group && r.group !== lastG) {
        rows.appendChild($(`<div class="blk">${esc(r.group)}</div>`));
        lastG = r.group;
      }
      const n = flat.length;
      flat.push({ ...r, page: rec.source_page });
      const div = $(`<div class="row ${n === S.rowIdx ? "cur" : ""} ${r.bucket ? "" : "p"}">
        <span class="nm">${esc(r.name)}</span>
        <span class="vl">${num(r.value)}</span>
        <span class="bk">${r.bucket ? esc(r.bucket) : "未收錄"}</span></div>`);
      div.onclick = () => { S.rowIdx = n; S.page = rec.source_page; viewReview(key); };
      rows.appendChild(div);
    });
  });
  S._flat = flat;

  const pgs = el.querySelector("#pgs");
  d.pages.forEach(p => {
    const b = $(`<button style="padding:2px 8px${p === page ? ";border-color:var(--accent);color:var(--accent)" : ""}">p.${p + 1}</button>`);
    b.onclick = () => { S.page = p; viewReview(key); };
    pgs.appendChild(b);
  });
  el.querySelector("#pick").onchange = e => {
    S.page = null; S.rowIdx = 0; location.hash = `#/review/${encodeURIComponent(e.target.value)}`;
  };

  document.getElementById("app").replaceChildren(el);
  const c = rows.querySelector(".row.cur");
  if (c) c.scrollIntoView({ block: "nearest" });
}

// ── 裁示:分桶對不到的科目名 ────────────────────────────────────────────
async function viewDispose() {
  S.pending = await api("pending");
  const app = document.getElementById("app");
  if (!S.pending.length) {
    return app.replaceChildren($(`<div><h1>裁示</h1><p class="muted">沒有待裁示的科目名。</p></div>`));
  }
  const byCell = {};
  S.pending.forEach(e => (byCell[e.cell_key] = byCell[e.cell_key] || []).push(e));

  const el = $(`<div><h1>裁示 · 分桶對不到</h1>
    <p class="hint">桶只能從 config.BUCKETS 這 10 個選,沒有自由輸入 ——
      打錯字會變成一個永遠對不到的新桶。送出後寫進 buckets.SYN,
      仍要 <code>git diff</code> 審過再 commit。</p>
    <div id="cells"></div></div>`);
  const box = el.querySelector("#cells");

  Object.entries(byCell).forEach(([cellKey, entries]) => {
    const card = $(`<div class="card" style="margin-bottom:14px">
      <div class="bar" style="margin-bottom:10px">
        <h2>${esc(cellKey)}</h2><span class="tag">${entries.length} 個名字</span>
        <button id="rq" style="margin-left:auto">全部裁完了 → 放回待抄</button>
      </div><div id="list"></div></div>`);
    const list = card.querySelector("#list");

    entries.forEach(e => {
      const item = $(`<div style="padding:10px 0;border-top:1px solid var(--line)">
        <div class="bar" style="margin-bottom:6px">
          <b style="font-size:14px">${esc(e.name)}</b>
          <span class="tag">${e.suggested ? "提案 " + esc(e.suggested) : "無提案"}</span>
          <span class="muted">${esc(e.why)}</span>
        </div><div class="bks"></div></div>`);
      const bks = item.querySelector(".bks");
      S.buckets.forEach((b, i) => {
        const on = b === e.suggested;
        const btn = $(`<button${on ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>
          <b>${i < 9 ? i + 1 : "·"}</b>${esc(b)}</button>`);
        btn.onclick = async () => {
          if (!confirm(`把「${e.name}」歸到「${b}」?\n\n會寫進 buckets.py 的 SYN。`)) return;
          const r = await post("dispose", { name: e.name, bucket: b, reason: e.why });
          if (r.error) return alert("失敗:\n" + r.error);
          viewDispose();
        };
        bks.appendChild(btn);
      });
      list.appendChild(item);
    });

    card.querySelector("#rq").onclick = async () => {
      if (!confirm(`把 ${cellKey} 放回待抄佇列?`)) return;
      await post("requeue", { cell_key: cellKey });
      S.ov = await api("overview");
      location.hash = "#/matrix";
    };
    box.appendChild(card);
  });
  document.getElementById("app").replaceChildren(el);
}

// ── 抄列:左邊填 JSON、右邊頁圖 ─────────────────────────────────────────
async function viewFill(key) {
  S.todo = await api("todo");
  if (!S.todo.length) return document.getElementById("app").replaceChildren(
    $(`<div><h1>抄列</h1><p class="muted">2023+ 範圍內沒有待抄的格子了。</p></div>`));
  if (!key || !S.todo.some(t => t.key === key)) key = S.todo[0].key;

  const [doc, cls] = key.split("|");
  const f = await api(`fill?doc=${encodeURIComponent(doc)}&cls=${encodeURIComponent(cls)}`);
  const page = S.page != null && f.pages.includes(S.page) ? S.page : f.pages[0];
  S.page = page;

  const el = $(`<div>
    <div class="bar">
      <h1 style="margin:0">抄列</h1>
      <select id="pick">${S.todo.map(t =>
        `<option value="${esc(t.key)}"${t.key === key ? " selected" : ""}>${esc(t.key)}</option>`).join("")}</select>
      <span class="tag">錨 ${num(f.anchor)} 仟元</span>
      <span class="tag">${S.todo.length} 格待抄</span>
      <button id="rules" style="margin-left:auto">抄列規矩</button>
    </div>
    <pre id="rulebox" class="tr" style="display:none;max-height:300px;overflow:auto"></pre>
    <div class="two">
      <div class="card">
        <div class="bar" style="margin:0 0 8px">
          <span class="muted">來源頁</span>
          <span id="pgs" style="display:flex;gap:4px;flex-wrap:wrap"></span>
        </div>
        <div class="pgwrap" style="max-height:600px">
          <img class="pg" src="/page.png?doc=${encodeURIComponent(doc)}&page=${page}" alt="">
        </div>
      </div>
      <div class="card">
        <div class="muted" style="margin-bottom:6px">records JSON(格式同左邊規矩;
          source_page 是 0-based)</div>
        <textarea id="ed" spellcheck="false"></textarea>
        <div class="bar" style="margin:10px 0 0">
          <button class="pri" id="go">送出(六道檢查照跑)</button>
          <span class="muted">驗收不過會退回,不會寫進 facts/</span>
        </div>
        <pre id="out" class="tr" style="display:none;max-height:260px;overflow:auto"></pre>
      </div>
    </div>
  </div>`);

  el.querySelector("#rulebox").textContent = f.rules;
  el.querySelector("#rules").onclick = () => {
    const b = el.querySelector("#rulebox");
    b.style.display = b.style.display === "none" ? "block" : "none";
  };
  el.querySelector("#ed").value = JSON.stringify(f.template, null, 1);

  const pgs = el.querySelector("#pgs");
  f.pages.forEach(p => {
    const b = $(`<button style="padding:2px 8px${p === page ? ";border-color:var(--accent);color:var(--accent)" : ""}">p.${p + 1}</button>`);
    b.onclick = () => { S.page = p; viewFill(key); };
    pgs.appendChild(b);
  });
  el.querySelector("#pick").onchange = e => {
    S.page = null; location.hash = `#/fill/${encodeURIComponent(e.target.value)}`;
  };

  el.querySelector("#go").onclick = async () => {
    const out = el.querySelector("#out");
    let data;
    try { data = JSON.parse(el.querySelector("#ed").value); }
    catch (ex) { out.style.display = "block"; out.textContent = "JSON 格式錯:" + ex.message; return; }
    out.style.display = "block"; out.textContent = "送出中…";
    const r = await post("submit", { doc, cls, pages: f.pages, records: data });
    out.textContent = r.output || r.error || JSON.stringify(r);
    if (r.status === "PASS") {
      S.ov = await api("overview");
      S.page = null;
      setTimeout(() => { location.hash = "#/fill/"; viewFill(null); }, 900);
    }
  };
  document.getElementById("app").replaceChildren(el);
}

// ── 鍵盤 ────────────────────────────────────────────────────────────────
function onKey(e) {
  if (e.metaKey || e.ctrlKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const h = location.hash;
  if (h.startsWith("#/review")) {
    const f = S._flat || [];
    if (e.key === "j" && S.rowIdx < f.length - 1) { S.rowIdx++; S.page = f[S.rowIdx].page; viewReview(S.cell.key); }
    else if (e.key === "k" && S.rowIdx > 0) { S.rowIdx--; S.page = f[S.rowIdx].page; viewReview(S.cell.key); }
  }
}

boot();
