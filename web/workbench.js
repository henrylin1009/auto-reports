"use strict";
// 複核台前端:零框架、零 CDN。只跟 /api/* 說話,不自己算業務邏輯。
//
// 四個畫面(2026-07-29 重構,原本五個;同日再加「分析」):
//   #/analysis   分析 —— 前台本體(make_web.py 的產出)用 iframe 掛進來
//   #/matrix     資料 —— 總覽矩陣(期別 × 銀行+代碼),nav 上的預設頁
//   #/doc/DOC    文件頁 —— 一份財報,三類攤開;已抄的核對、沒抄的一顆按鈕
//   #/buckets    分桶 —— 十個桶 × 收進去的名字,拖曳改判;入口是「資料」頁
//                的連結,不在 nav 上(nav 只放 分析/資料 兩個常駐頁)
//
// 「核對 / 抄列 / 裁示」三頁退場:前兩者是同一個畫面的兩個狀態(左數字右頁圖,
// 只差有沒有資料),裁示則被分桶檢視取代(一次看全部,不是一次問一個名字)。
//
// ⚠️ 頁碼一律 0-based(與 facts 的 source_page、locate 的候選頁同制)。
//    畫面上顯示才 +1。不要在別的地方偷偷換算。

const S = { ov: null, buckets: [], cell: null, page: null, rowIdx: 0,
            pending: [], todo: [], basis: null };

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
  S.basis = S.ov.basis;
  document.getElementById("rebuildBtn").onclick = runRebuild;
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
  // 從網址進來(或 hashchange)算一次新的導覽 —— 重拉,免得看到過期的內容。
  else if (r === "doc") viewDoc(decodeURIComponent(parts[1] || ""), { reload: true });
  else if (r === "analysis") viewAnalysis();
  else viewMatrix();
}

// ── 分析:前台本體(make_web.py 的產出)用 iframe 掛進來 ──────────────────
// 不是真融合 —— 分析頁的 JS 跟這裡是兩個世界,互相看不到對方的變數。
// 換到這個好處是分析頁完全不用改,壞處是「點分析頁某格跳到後台去改」做不到,
// 見 docs/plan_ui_unify.md 步驟 5。
function viewAnalysis() {
  nav("analysis");
  const el = $(`<div style="margin:-16px;height:calc(100vh - 42px)">
    <iframe src="/analysis" title="分析頁"
      style="width:100%;height:100%;border:0;display:block"></iframe>
  </div>`);
  document.getElementById("app").replaceChildren(el);
}

const CLS = ["AC", "OCI", "Trading"];
const SBAR = { done: "g", todo: "miss", blocked: "w", na: "miss" };

// ── 資料:期別(列) × 銀行+代碼(欄),一格一份檔 ─────────────────────────
async function viewMatrix() {
  S.ov = await api("overview" + (S.basis ? "?basis=" + encodeURIComponent(S.basis) : ""));
  S.basis = S.ov.basis;
  const { periods, cols, grid, stats, bases, fetch_stats } = S.ov;
  nav("matrix");

  const el = $(`<div>
    <h1>資料 · 2023 起
      <span class="bsw">${bases.map(b =>
        `<button data-b="${esc(b)}" class="${b === S.basis ? "pri" : ""}">${esc(b)}</button>`).join("")}</span>
      <a href="#/buckets" class="tag" style="text-decoration:none;margin-left:8px">分桶檢視</a>
    </h1>
    <div class="stats">
      <div class="stat"><b>${stats.done}</b><span>已抄</span></div>
      <div class="stat"><b>${stats.todo}</b><span>待抄</span></div>
      <div class="stat ${stats.blocked ? "w" : ""}"><b>${stats.blocked}</b><span>卡在分類</span></div>
      <div class="stat"><b>${stats.na}</b><span>無候選頁</span></div>
    </div>
    <div class="auto">
      <button id="fetchgo"${stats && fetch_stats.missing ? "" : " disabled"}>抓最新(${fetch_stats.missing} 期)</button>
      <button id="fetchlogbtn">抓檔紀錄</button>
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
      空白代表那期沒有這份檔 —— 是沒有檔,不是沒抄。
      口徑從**封面**判(個體/合併),不從檔名推:檔名裡的 AI 編號在抓檔時已被統一改寫,
      不再帶有意義。</p>
  </div>`);

  // 口徑切換。**跨行比較只用個體**(2026-07-29 裁示),合併另外一組 ——
  // 兩者期別不同(個體只有 02/04,合併有四季),分開畫才不會滿是空欄。
  el.querySelectorAll(".bsw button").forEach(b => {
    b.onclick = () => { S.basis = b.dataset.b; viewMatrix(); };
  });

  el.querySelector("#fetchlogbtn").onclick = showFetchLog;

  const fg = el.querySelector("#fetchgo");
  if (fg) fg.onclick = () => {
    const targets = Object.values(grid)
      .filter(g => g.fetch === "missing").map(g => ({ period: g.period, code: g.code }));
    if (!targets.length) return;
    if (!confirm(`抓 ${targets.length} 期,抓到的接著自動抄列。\n\n`
      + `TWSE 對連續請求會擋,這會慢慢跑。`)) return;
    runFetch(targets, true);
  };

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
      else if (!g.doc) td.appendChild(fetchCell(g, stats));
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
        btn.onclick = () => { S.page = null; S.rowIdx = 0; location.hash = `#/doc/${encodeURIComponent(g.doc)}`; };
        td.appendChild(btn);
      }
      tr.appendChild(td);
    }
    tb.appendChild(tr);
  }
  document.getElementById("app").replaceChildren(el);
}

// 抓檔紀錄面板 —— **不必再開終端機或問我**,每一筆都是實際問過 TWSE 的答案。
const FETCH_STATUS_LABEL = { ok: "抓到了", absent: "無申報", failed: "失敗" };
async function showFetchLog() {
  const rows = await api("fetchlog");
  const body = rows.length
    ? rows.map(r => `<div class="fl-row fl-${r.status}">
        <span class="fl-k">${esc(r.key)}</span>
        <span class="fl-s">${FETCH_STATUS_LABEL[r.status] || r.status}</span>
        <span class="fl-t">${esc(r.at || "")}</span>
        ${r.why ? `<span class="fl-w">${esc(r.why)}</span>` : ""}
      </div>`).join("")
    : `<p class="muted">還沒抓過任何一期。</p>`;
  const el = $(`<div class="card" id="fetchlogpanel">
    <div class="bar" style="margin:0 0 8px">
      <b>抓檔紀錄</b><span class="muted">${rows.length} 筆,新到舊</span>
      <button style="margin-left:auto" id="fetchlogclose">關閉</button>
    </div>
    <div style="max-height:320px;overflow:auto">${body}</div>
  </div>`);
  el.querySelector("#fetchlogclose").onclick = () => el.remove();
  document.getElementById("fetchlogpanel")?.remove();
  document.querySelector(".auto").insertAdjacentElement("afterend", el);
}

// 沒有檔的格子。**三種「沒有」要分開** —— 混成一個「—」的話,
// 「還沒抓」和「這期根本沒申報」長得一模一樣,使用者只能猜。
//
// `absent` **仍然可以按**(2026-07-29 使用者裁示):TWSE 清單今天沒有不代表
// 以後不會有 —— 銀行晚一點才申報是常態,不是例外。原本設計成不可按、
// 靠某個「該多久重問一次」的規則自動放行,但那個規則要猜多久才合理沒有
// 客觀答案;讓使用者自己決定「現在想不想再問一次」,比系統代猜可靠。
const FETCH_LABEL = { missing: "抓這期", absent: "查無,再試", failed: "重試" };

function fetchCell(g, stats) {
  const st = g.fetch;
  const b = $(`<button class="cell ${st === "failed" ? "bad" : "miss"}">
    <span class="k">${FETCH_LABEL[st] || st}</span>
    <span class="s">${esc(g.period)}</span></button>`);
  if (st === "absent") b.title = `${g.period} ${g.code}:上次問 TWSE 是「沒有」,按下去會重問一次`;
  b.disabled = !S.ov.can_fetch;
  if (!S.ov.can_fetch) b.title = "只支援抓個體財報,合併要另外處理";
  b.onclick = () => runFetch([{ period: g.period, code: g.code }], true);
  return b;
}

// 抓檔與抄列共用同一個背景工作槽(server.start_autofill),所以進度也共用同一支輪詢。
async function runFetch(targets, thenFill) {
  const r = await post("fetch", { targets, then_fill: !!thenFill });
  if (!r.started) { alert(r.why); return; }
  const log = document.getElementById("autolog");
  const hint = document.getElementById("autohint");
  if (hint) hint.textContent = `抓 ${targets.length} 期中…抓到的會接著自動抄列。`;
  const t = setInterval(async () => {
    const s = await api("autofill/status");
    if (log) { log.hidden = !s.lines.length; log.textContent = s.lines.join("\n"); log.scrollTop = log.scrollHeight; }
    if (s.running) return;
    clearInterval(t);
    viewMatrix();
  }, 1500);
}

// ── 重建:facts/ → data.json → site/,讓分析頁看到後台剛改的東西 ─────────
// 跟抄列共用同一個後端工作槽(server._JOB),所以進度輪詢也走同一支
// /api/autofill/status —— 不是偷懶,是兩者本來就不准同時跑(都會動 facts/)。
async function runRebuild() {
  const btn = document.getElementById("rebuildBtn");
  const stat = document.getElementById("rebuildstat");
  if (!confirm("重建會用 facts/ 現有資料重跑 build.py --write + make_web.py,"
    + "直接覆蓋本機的 data.json 與 site/。\n\n"
    + "不會 push、不會發布到 GitHub Pages —— 那一步仍要你自己 git push。\n\n"
    + "確定要重建嗎?")) return;
  const r = await post("rebuild", {});
  if (!r.started) { stat.textContent = r.why; return; }
  btn.disabled = true; btn.textContent = "重建中…";
  stat.textContent = "跑 build.py + make_web.py…";
  const t = setInterval(async () => {
    const s = await api("autofill/status");
    if (s.lines.length) stat.textContent = s.lines[s.lines.length - 1].slice(0, 50);
    if (s.running) return;
    clearInterval(t);
    btn.disabled = false; btn.textContent = "⟳ 重建";
    if (s.error) { stat.textContent = "重建失敗 —— 詳見伺服器終端機。"; return; }
    stat.textContent = "重建完成 · " + new Date().toLocaleTimeString("zh-TW", { hour12: false });
    // 如果目前正看著分析頁,重新整理 iframe,不必自己按重新整理才看得到新數字。
    const ifr = document.querySelector("#app iframe");
    if (ifr) ifr.src = ifr.src;
  }, 1500);
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
    <h1>分桶 · 每個桶收了哪些科目名
      <a href="#/matrix" class="tag" style="text-decoration:none;margin-left:8px">← 資料</a>
    </h1>
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
// 跑完自動重畫資料頁,因為 stats 已經變了。
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
                               : "跑完了。重畫資料頁…";
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

  // 跑完會重畫資料頁,重畫就把紀錄洗掉了 —— 但那正是你要看「剛剛發生什麼」的時候。
  // 後端的 lines 還在,所以有紀錄就畫出來,不是只有 running 才畫。
  api("autofill/status").then(s => {
    if (s.lines.length) paint(s);
    if (s.running) timer = setInterval(poll, 1500);
  });
}

// ── 文件頁:一份財報,三類攤開 ──────────────────────────────────────────
// 取代舊的「核對 / 抄列 / 裁示」三頁(2026-07-29 裁示)。工作單位是**一份文件**,
// 不是一個 doc|cls 格子 —— 你是在處理這份財報,三類本來就要一起看。
//
// 版面:左邊三類堆疊(已抄=逐列、沒抄=一顆按鈕),右邊一張共用頁圖。
// 點左邊任一列,右邊翻到那列的來源頁 —— 三類共用同一個檢視器,因為它們的
// 來源頁常常就在鄰近幾頁。
//
// ⚠️ `reload` 預設 **false**:點一列、翻一頁都只是換「看哪裡」,資料沒變,
//    不必重打 /api/doc。那支要 1.8s(後端得抽完整份 PDF 的文字),每點一列
//    重來一次的話,畫面就是每次點都卡兩秒 —— 這正是使用者回報的症狀。
//    **只有資料真的可能變了才傳 reload:true**(抄完一格、送出成功、換文件)。
async function viewDoc(doc, { reload = false } = {}) {
  if (!doc) return location.hash = "#/matrix";
  if (reload || !S.doc || S.doc.doc !== doc) {
    S.doc = await api("doc?doc=" + encodeURIComponent(doc));
  }
  const d = S.doc;
  nav("doc");

  const page = S.page != null && d.pages.includes(S.page) ? S.page : d.pages[0];
  S.page = page;

  const el = $(`<div>
    <div class="bar">
      <h1 style="margin:0">${esc(doc)}</h1>
      <a href="#/matrix" class="tag" style="text-decoration:none">← 資料</a>
      <span class="tag" id="jobtag" hidden></span>
    </div>
    <div class="two">
      <div id="cls" style="display:flex;flex-direction:column;gap:12px"></div>
      <div>
        <div class="card">
          <div class="bar" style="margin:0 0 8px">
            <span class="muted">來源頁</span>
            <span id="pgs" style="display:flex;gap:4px;flex-wrap:wrap"></span>
          </div>
          <div class="pgwrap"><img class="pg" src="/page.png?doc=${encodeURIComponent(doc)}&page=${page}" alt=""></div>
          <div class="hint">頁層級核對,不畫框。點左邊任一列,右邊翻到那列的來源頁。</div>
        </div>
      </div>
    </div>
  </div>`);

  const host = el.querySelector("#cls");
  const flat = [];
  for (const cls of CLS) {
    const v = d.classes[cls];
    if (v.status === "na") continue;
    host.appendChild(v.cell ? clsDone(doc, cls, v.cell, flat) : clsTodo(doc, cls, v.fill));
  }
  S._flat = flat;

  const pgs = el.querySelector("#pgs");
  d.pages.forEach(p => {
    const b = $(`<button style="padding:2px 8px${p === page ? ";border-color:var(--accent);color:var(--accent)" : ""}">p.${p + 1}</button>`);
    b.onclick = () => { S.page = p; viewDoc(doc); };
    pgs.appendChild(b);
  });

  document.getElementById("app").replaceChildren(el);
  const c = host.querySelector(".row.cur");
  if (c) c.scrollIntoView({ block: "nearest" });
}

// 已抄的一類:逐列 + 桶。未收錄的列標紅,因為那是要你處理的東西。
function clsDone(doc, cls, cell, flat) {
  const bad = cell.records.reduce((n, r) => n + r.rows.filter(x => !x.bucket).length, 0);
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(cell.anchor)}</span>
      ${bad ? `<span class="tag w">${bad} 列未收錄</span>` : `<span class="tag">已抄</span>`}
      <button class="dan" style="margin-left:auto" data-re>重抄</button>
    </div>
    <div class="rows" style="max-height:340px;overflow:auto"></div>
  </div>`);
  const rows = card.querySelector(".rows");
  cell.records.forEach(rec => {
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
      div.onclick = () => { S.rowIdx = n; S.page = rec.source_page; viewDoc(doc); };
      rows.appendChild(div);
    });
  });
  card.querySelector("[data-re]").onclick = async () => {
    if (!confirm(`重抄 ${doc} ${cls}?\n現有內容會被覆蓋(舊版存進歷史)。`)) return;
    await runCell(doc, cls);
  };
  return card;
}

// 還沒抄的一類:一顆按鈕,不必跳到另一頁。手動貼 JSON 收在摺疊裡 ——
// 自動抄列是常態,手動是例外,版面要照這個比例。
function clsTodo(doc, cls, f) {
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(f.anchor)}</span>
      <span class="tag">${f.pages.length} 個候選頁</span>
      <button class="pri" style="margin-left:auto" data-go>抄這格</button>
    </div>
    <p class="hint" style="margin:0">用 Gemini 抄,六道檢查照跑;對不上會自動擴頁重試。</p>
    <details style="margin-top:8px">
      <summary class="muted" style="cursor:pointer;font-size:12px">手動貼 JSON</summary>
      <textarea data-ed spellcheck="false" style="margin-top:6px"></textarea>
      <div class="bar" style="margin:8px 0 0">
        <button data-sub>送出(六道檢查照跑)</button>
        <span class="muted">驗收不過會退回,不會寫進 facts/</span>
      </div>
      <pre data-out class="tr" style="display:none;max-height:220px;overflow:auto"></pre>
    </details>
  </div>`);
  card.querySelector("[data-go]").onclick = () => runCell(doc, cls);
  card.querySelector("[data-ed]").value = JSON.stringify(f.template, null, 1);
  card.querySelector("[data-sub]").onclick = async () => {
    const out = card.querySelector("[data-out]");
    let body;
    try { body = JSON.parse(card.querySelector("[data-ed]").value); }
    catch (err) { out.style.display = "block"; out.textContent = "JSON 解析失敗:" + err.message; return; }
    const r = await post("submit", { doc, cls, pages: f.pages, records: body.records });
    out.style.display = "block"; out.textContent = r.output || r.error || "";
    if (r.status === "PASS") setTimeout(() => viewDoc(doc, { reload: true }), 900);
  };
  return card;
}

// 抄單格 —— 跟資料頁那顆按鈕走同一個後端工作,所以一次只准跑一個。
async function runCell(doc, cls) {
  const r = await post("autofill", { cell: `${doc}|${cls}` });
  const tag = document.getElementById("jobtag");
  if (!r.started) { alert(r.why); return; }
  if (tag) { tag.hidden = false; tag.textContent = `抄列中… ${cls}`; }
  const t = setInterval(async () => {
    const s = await api("autofill/status");
    if (tag) tag.textContent = "抄列中… " + (s.lines[s.lines.length - 1] || "").slice(0, 60);
    if (s.running) return;
    clearInterval(t);
    S.page = null; S.rowIdx = 0;
    viewDoc(doc, { reload: true });        // 剛抄完,facts/ 變了,一定要重拉
  }, 1500);
}

// ── 鍵盤 ────────────────────────────────────────────────────────────────
function onKey(e) {
  if (e.metaKey || e.ctrlKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const h = location.hash;
  if (h.startsWith("#/doc")) {
    const f = S._flat || [];
    const doc = S.doc && S.doc.doc;
    if (e.key === "j" && S.rowIdx < f.length - 1) { S.rowIdx++; S.page = f[S.rowIdx].page; viewDoc(doc); }
    else if (e.key === "k" && S.rowIdx > 0) { S.rowIdx--; S.page = f[S.rowIdx].page; viewDoc(doc); }
  }
}

boot();
