"use strict";
// 複核台前端:零框架、零 CDN。只跟 /api/* 說話,不自己算業務邏輯。
//
// 四個畫面(2026-07-29 重構,原本五個;同日再加「分析」):
//   #/analysis   分析 —— 前台本體(make_web.py 的產出)用 iframe 掛進來。
//                ⚠️ src 一定要寫 `/site/index.html`,**不能寫 `/analysis`** ——
//                後者自 2026-08-10 起 302 導回本頁 `#/analysis`(讓分析頁永遠在殼裡),
//                iframe 指過去就是工作台自己載自己,無限遞迴。
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

// 「點了沒反應」的根因(2026-07-30 實測):後端 500/400 回的是
// `{"error": "..."}`,但呼叫端從不檢查,例外一路丟到 view 函式裡把畫面
// 定格在「載入中…」。api()/post() 現在**自己**驗 error、自己彈紅字條、
// 自己拋例外——呼叫端不必每支自己補這段。
function showError(msg) {
  document.getElementById("errbar")?.remove();
  const bar = $(`<div id="errbar" style="position:fixed;top:0;left:0;right:0;z-index:999;
    background:var(--danger,#c0392b);color:#fff;padding:8px 16px;font-size:13px;
    display:flex;gap:12px;align-items:center">
    <span style="flex:1;white-space:pre-wrap">${esc(msg)}</span>
    <button style="background:transparent;border:1px solid #fff;color:#fff" data-x>關閉</button>
  </div>`);
  bar.querySelector("[data-x]").onclick = () => bar.remove();
  document.body.prepend(bar);
}
async function _checked(resp) {
  const r = await resp.json();
  if (r && r.error) { showError(r.error); throw new Error(r.error); }
  return r;
}
const api = (p) => fetch("/api/" + p).then(_checked);
const post = (p, b) => fetch("/api/" + p, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(b)
}).then(_checked);

async function boot() {
  [S.ov, S.buckets] = await Promise.all([api("overview"), api("buckets")]);
  S.basis = S.ov.basis;
  // 用 ?. —— 這頁若被嵌在別的殼裡(沒有導覽列、也就沒有重建鈕),
  // 不該讓整個 boot() 在這裡炸掉,後面的 route() 還得跑。
  const rb = document.getElementById("rebuildBtn");
  if (rb) rb.onclick = runRebuild;
  addEventListener("hashchange", route);
  addEventListener("keydown", onKey);
  route();
  refreshPublishStatus();
}

// P4-1「永遠在的發布狀態列」——之前完全沒有這個訊號,實測過一次網站停在
// 07-29、facts/ 已經改到 07-31 卻沒有任何地方講(plan_v5_統一.md §0.8)。
// 只看 mtime,不重跑 build,所以可以放心在 boot() 常駐呼叫一次。
async function refreshPublishStatus() {
  const el = document.getElementById("rebuildstat");
  try {
    const s = await api("publish_status");
    if (s.stale && !el.textContent) {
      el.textContent = `⚠ ${s.newer_than_data.join("、")} 比網站新,按重建才會發布`;
      el.style.color = "var(--danger,#c0392b)";
    }
  } catch (e) { /* 不擋主流程 —— 這只是個提示 */ }
}

// ── 統一的「看證據」出口(plan_schema_derive.md §5/D4)──────────────────────
// 任何要人下判斷的地方都呼叫這支,把證據叫到右邊的共用頁面檢視器來——
// 不是另開一個 modal,是跳到同一份文件、同一個檢視器,跟「點已抄的列會
// 跳去來源頁」是同一套機制,不是兩套。
//
// `page` 是 0-based(跟 `source_page` 同制)。`page == null`(找不到證據頁,
// 例如名字剛好改過、或這格還沒歸檔)時**不假裝有證據**——呼叫端自己決定
// 要不要跳、要不要提示「沒有頁級證據」,這支只負責跳得動的情況。
function showEvidence(doc, page) {
  if (page == null) return false;
  S.page = page;
  const target = "#/doc/" + encodeURIComponent(doc);
  if (location.hash === target) {
    viewDoc(doc);               // 已經在看同一份文件,直接重繪即可
  } else {
    location.hash = target;     // 觸發 hashchange → route() → viewDoc(reload:true)
  }
  return true;
}

// 一個出現處(cell_key/doc/cls/page)畫成一個可點連結,點了跳去證據頁。
// `page == null` 時印成灰字不可點——**明講沒有證據**,不是沉默省略
// (`docs/plan_schema_derive.md` §5 規矩 1)。
function evidenceChip(c) {
  if (c.page == null) {
    const s = $(`<span class="muted" style="margin-right:8px" title="找不到頁級證據——可能已改名或這格還沒歸檔">${esc(c.cell_key)}(無證據頁)</span>`);
    return s;
  }
  const a = $(`<a href="#" style="margin-right:8px">${esc(c.cell_key)} · p.${c.page + 1}</a>`);
  a.onclick = (e) => { e.preventDefault(); showEvidence(c.doc, c.page); };
  return a;
}

function nav(r) {
  // 只挑頁內路由的連結(有 data-r);全站導覽列(.appnav)由 web/appnav.js 自己標記,
  // 這裡碰它會把它剛標好的 .on 拔掉。
  document.querySelectorAll("a[data-r]").forEach(a => a.classList.toggle("on", a.dataset.r === r));
  const st = S.ov.stats;
  // 「卡住」= blocked(分類表缺口)+ rejected(擴頁到上限仍對不上)——
  // 對使用者來說都是「這格需要我去看一眼」,細分留給文件頁的理由文字。
  document.getElementById("navstat").textContent =
    `已抄 ${st.done} · 待抄 ${st.todo} · 卡住 ${st.blocked + (st.rejected || 0)}`;
}

async function route() {
  const parts = location.hash.replace(/^#\//, "").split("/");
  const r = parts[0] || "matrix";
  nav(r);
  try {
    if (r === "buckets") await viewBuckets();
    else if (r === "queue") await viewQueue();
    // v4 讀取/複核的實作仍在 /v4.html(2026-08-03 收成一份,原本兩邊各打一份
    // 同樣的 /api/v4/*)。2026-08-10 起它從一級導覽降成「資料」頁底下的入口
    // (`#/v4`,用 iframe 掛)—— 它跟資料頁做的是同一件事(把文件變成可發布的
    // 數字),只是走另一條管線,並排在最上層會讓人以為是兩個功能領域。
    // 從網址進來(或 hashchange)算一次新的導覽 —— 重拉,免得看到過期的內容。
    else if (r === "doc") await viewDoc(decodeURIComponent(parts[1] || ""), { reload: true });
    else if (r === "analysis") await viewAnalysis();
    else if (r === "v4") viewV4();
    else await viewMatrix();
  } catch (e) {
    // `_checked()` 已經彈過紅字條——這裡只負責把畫面從「載入中…」
    // 解出來,不然使用者看到的症狀就是「點了沒反應」(2026-07-30 實測)。
    document.getElementById("app").replaceChildren($(`<p class="hint">
      這頁載入失敗,詳見上方紅字。<a href="#/matrix">回資料頁</a></p>`));
  }
}

// ── 分析:前台本體(make_web.py 的產出)用 iframe 掛進來 ──────────────────
// 不是真融合 —— 分析頁的 JS 跟這裡是兩個世界,互相看不到對方的變數。
// 換到這個好處是分析頁完全不用改,壞處是「點分析頁某格跳到後台去改」做不到,
// 見 docs/plan_ui_unify.md 步驟 5。
// ── v4 複核:同樣用 iframe 掛(理由同 viewAnalysis)────────────────────────
// iframe 裡的 web/appnav.js 會自己不畫全站導覽列(它判 window.self !== window.top),
// 所以不會出現兩條導覽疊著;v4 自己的三個分頁(佇列/比較表/讀取)是第三層,留著。
function viewV4() {
  nav("v4");
  document.getElementById("app").replaceChildren($(`
    <div style="margin:-16px;height:calc(100vh - 42px)">
      <iframe src="/v4.html" title="v4 複核台"
              style="width:100%;height:100%;border:0;display:block"></iframe>
    </div>`));
}

function viewAnalysis() {
  nav("analysis");
  const el = $(`<div style="margin:-16px;height:calc(100vh - 42px)">
    <iframe src="/site/index.html" title="分析頁"
      style="width:100%;height:100%;border:0;display:block"></iframe>
  </div>`);
  document.getElementById("app").replaceChildren(el);
}

const CLS = ["AC", "OCI", "Trading"];
const SBAR = { done: "g", todo: "miss", blocked: "w", rejected: "r", no_data: "miss", na: "miss" };

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
      <a href="#/queue" class="tag" style="text-decoration:none;margin-left:4px">裁示台</a>
      <a href="#/v4" class="tag" style="text-decoration:none;margin-left:4px">v4 複核</a>
    </h1>
    <div class="stats">
      <div class="stat"><b>${stats.done}</b><span>已抄</span></div>
      <div class="stat"><b>${stats.todo}</b><span>待抄</span></div>
      <div class="stat ${stats.blocked ? "w" : ""}"><b>${stats.blocked}</b><span>卡在分類</span></div>
      <div class="stat ${stats.rejected ? "w" : ""}"><b>${stats.rejected || 0}</b><span>擴頁到上限</span></div>
      <div class="stat"><b>${stats.no_data || 0}</b><span>標記無資料</span></div>
      <div class="stat"><b>${stats.na}</b><span>無候選頁</span></div>
    </div>
    <div class="auto">
      <button id="fetchgo"${stats && fetch_stats.missing ? "" : " disabled"}>抓最新(${fetch_stats.missing} 期)</button>
      <button id="fetchlogbtn">抓檔紀錄</button>
      <button class="pri" id="autogo">自動抄列</button>
      <button id="autostop" hidden>取消</button>
      <select id="autolim">
        <option value="3">先跑 3 格</option>
        <option value="10">跑 10 格</option>
        <option value="">跑完全部待抄(${stats.todo} 格)</option>
      </select>
      <span class="hint" id="autohint">用你自己的 Claude Code 抄（不需 API key），六道檢查照跑；對不上的會自動擴頁重試，
        仍過不了就進「卡住」不會寫進事實庫。</span>
    </div>
    <div id="uploadzone" class="uploadzone">
      <span>拖一份 PDF 到這裡上傳，或
        <label class="uplabel">選檔案<input type="file" accept="application/pdf" id="uploadfile" hidden></label>
      </span>
      <span class="hint">檔名格式要是 <code>YYYYMM_代碼_AI{n}.pdf</code>（例：<code>202502_5836_AI3.pdf</code>）
        ——跟 TWSE 抓下來的檔名同一套；抄一次，除非拖同一份內容否則不會重複存。</span>
      <span class="hint" id="uploadhint"></span>
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
  wireUpload(el);

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
        const blocked = st.includes("blocked") || st.includes("rejected");
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
  // 點卡片(不是拖曳)跳去它第一個出現處的證據頁——拖曳改的是全域規則
  // (buckets.SYN),按下去之前至少要能一鍵看到「這個名字長什麼樣子」
  // (`docs/plan_schema_derive.md` §5,原本這裡只有 tooltip 印一串 cell_key 文字)。
  const mkChip = (g) => {
    const cls = g.state === "PROVISIONAL" ? "prov" : g.state === "UNCLASSIFIED" ? "uncl" : "";
    const withPage = g.cells.find(c => c.page != null);
    const c = $(`<div class="chip ${cls}" draggable="true">${esc(g.name)}<b>×${g.n}</b></div>`);
    c.title = `${g.state}\n出現在 ${g.cells.length} 格`
      + (withPage ? `\n點一下看第一個出現處(${withPage.cell_key} p.${withPage.page + 1})` : "");
    c.onclick = () => { if (withPage) showEvidence(withPage.doc, withPage.page); };
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

// ── 裁示台:待裁示佇列按名字批次(2026-07-30 加,plan_web_complete.md W1)──
// 一張卡 = 一個不重複名字(不是一個出現處)——裁示一次對整個名字生效,
// 138 筆出現處今天只對應 31 張卡。沒建議的排最前面,因為那才是真的要想的。
async function viewQueue() {
  const v = await api("queue");
  nav("queue");
  const el = $(`<div>
    <h1>裁示台 · 待收錄的科目名
      <a href="#/matrix" class="tag" style="text-decoration:none;margin-left:8px">← 資料</a>
    </h1>
    <div class="stats">
      <div class="stat"><b>${v.groups.length}</b><span>待裁示名字</span></div>
      <div class="stat"><b>${v.occurrences}</b><span>共出現處</span></div>
    </div>
    <div class="qlist" style="display:flex;flex-direction:column;gap:12px"></div>
    <p class="hint">收錄一個名字,立刻對它出現過的每一格生效(寫進 buckets.SYN)。
      有黃底建議的是規則猜的,**猜的不等於對的,按下去才算數**。
      收錄後如果讓某格「分類表缺口」的全部名字都解了,那格會自動放回待抄佇列。</p>
  </div>`);
  if (!v.groups.length) {
    el.querySelector(".qlist").appendChild($(`<p class="hint">沒有待裁示的名字。</p>`));
  }
  el.querySelector(".qlist").append(...v.groups.map(g => queueCard(g)));
  document.getElementById("app").replaceChildren(el);
}

function queueCard(g) {
  const card = $(`<div class="card" style="margin:0;padding:14px 18px">
    <div class="bar" style="margin:0 0 6px">
      <b>${esc(g.name)}</b>
      <span class="tag">×${g.n}</span>
      ${g.suggested ? `<span class="chip prov" style="cursor:default">建議:${esc(g.suggested)}</span>` : ""}
    </div>
    ${g.suggested_why ? `<p class="hint" style="margin:0 0 8px">${esc(g.suggested_why)}</p>` : ""}
    <div class="bkts" style="display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px"></div>
    <details>
      <summary class="muted" style="cursor:pointer;font-size:12px">出現在 ${g.cells.length} 格</summary>
      <div class="hint" data-cells style="margin:6px 0 0;display:flex;flex-wrap:wrap"></div>
    </details>
  </div>`);
  card.querySelector("[data-cells]").append(...g.cells.map(evidenceChip));
  const row = card.querySelector(".bkts");
  S.buckets.forEach(b => {
    const btn = $(`<button${b === g.suggested ? ' class="pri"' : ""}>${esc(b)}</button>`);
    btn.onclick = async () => {
      const reason = g.suggested_why || prompt(`「${g.name}」歸「${b}」的理由(會寫進 buckets.py 的註解):`, "") || "複核台裁示";
      const r = await post("dispose", { name: g.name, bucket: b, reason });
      if (r.error) { alert(r.error); return; }
      if (r.unstuck && r.unstuck.length) {
        alert(`已收錄。順帶放行了 ${r.unstuck.length} 格(分類表缺口全部解了):\n` + r.unstuck.join("\n"));
      }
      viewQueue();
    };
    row.appendChild(btn);
  });
  return card;
}

// ── 自動抄列:按鈕 + 輪詢進度 ──────────────────────────────────────────
// 後端一次只准跑一個(server._JOB),這裡不自己再管一份狀態 —— 兩份狀態遲早會不一致。
// 跑完自動重畫資料頁,因為 stats 已經變了。
function wireAutofill(el) {
  const btn = el.querySelector("#autogo");
  const stopBtn = el.querySelector("#autostop");
  const log = el.querySelector("#autolog");
  const hint = el.querySelector("#autohint");
  let timer = null;

  const paint = (s) => {
    log.hidden = !s.lines.length;
    log.textContent = s.lines.join("\n");
    log.scrollTop = log.scrollHeight;
    btn.disabled = s.running;
    btn.textContent = s.running ? "抄列中…" : "自動抄列";
    stopBtn.hidden = !s.running;
    stopBtn.disabled = !!s.cancel;
    stopBtn.textContent = s.cancel ? "取消中…" : "取消";
  };

  const poll = async () => {
    const s = await api("autofill/status");
    paint(s);
    if (s.running) return;
    clearInterval(timer); timer = null;
    hint.textContent = s.error ? "出錯了，詳見下方訊息。"
                     : s.cancel ? "已取消。重畫資料頁…"
                     : "跑完了。重畫資料頁…";
    if (!s.error) setTimeout(viewMatrix, 1200);
  };

  btn.onclick = async () => {
    const v = el.querySelector("#autolim").value;
    const r = await post("autofill", { limit: v ? Number(v) : null });
    if (!r.started) { hint.textContent = r.why; return; }
    btn.disabled = true; btn.textContent = "抄列中…";
    stopBtn.hidden = false; stopBtn.disabled = false; stopBtn.textContent = "取消";
    hint.textContent = "跑起來了。Claude 每格約 1-3 分鐘，擴頁重試會多幾輪。";
    timer = setInterval(poll, 1500);
  };

  stopBtn.onclick = async () => {
    stopBtn.disabled = true; stopBtn.textContent = "取消中…";
    hint.textContent = "取消中 —— 等目前這格跑完就停。";
    await post("autofill/cancel", {});
  };

  // 跑完會重畫資料頁,重畫就把紀錄洗掉了 —— 但那正是你要看「剛剛發生什麼」的時候。
  // 後端的 lines 還在,所以有紀錄就畫出來,不是只有 running 才畫。
  api("autofill/status").then(s => {
    if (s.lines.length) paint(s);
    if (s.running) timer = setInterval(poll, 1500);
  });
}

// ── R2-1/R2-2:拖 PDF 上傳,上傳完自動排進讀取佇列 ──────────────────────
// 上傳走 /api/upload(原始 bytes,不是 JSON —— post() 那支不能用)。
// 上傳成功後直接借 /api/autofill 的 {cell: doc+"|AC"} 分支觸發整份文件的
// v4 讀取 + 分流 + 歸檔(server._job_run 的 elif cell 分支只用 doc 那半,
// 類別隨便填),進度顯示借用跟「自動抄列」同一組 DOM(#autolog/#autohint)
// ——後端 _JOB 同一時間只准跑一個,共用顯示反而是對的:不管現在跑的是
// 手動觸發的自動抄列還是上傳觸發的讀取,畫面上永遠只有一份「現在在跑什麼」。
function wireUpload(el) {
  const zone = el.querySelector("#uploadzone");
  const fileInput = el.querySelector("#uploadfile");
  const hint = el.querySelector("#uploadhint");
  const log = el.querySelector("#autolog");
  const autohint = el.querySelector("#autohint");

  async function ingest(file) {
    if (!file) return;
    if (file.type && file.type !== "application/pdf" && !file.name.endsWith(".pdf")) {
      hint.textContent = `✗ ${file.name} 不是 PDF。`;
      return;
    }
    const doc = file.name.replace(/\.pdf$/i, "");
    hint.textContent = `上傳中…${file.name}`;
    let r;
    try {
      const resp = await fetch(`/api/upload?doc=${encodeURIComponent(doc)}`, {
        method: "POST", headers: { "Content-Type": "application/pdf" }, body: file
      });
      r = await resp.json();
      if (!resp.ok) throw new Error(r.error || `HTTP ${resp.status}`);
    } catch (e) {
      hint.textContent = `✗ 上傳失敗:${e.message}`;
      return;
    }
    if (r.dup) { hint.textContent = `${r.note}`; return; }
    hint.textContent = `✓ ${r.note} —— 排進讀取佇列…`;

    const started = await post("autofill", { cell: `${r.doc}|AC` });
    if (!started.started) {
      hint.textContent = `已存檔,但沒能立刻開始讀取:${started.why}`
        + `（等目前那個跑完,去「文件頁」按「重抄」補跑這份即可）`;
      return;
    }
    autohint.textContent = `正在讀取剛上傳的 ${r.doc}…`;
    const poll = setInterval(async () => {
      const s = await api("autofill/status");
      log.hidden = !s.lines.length;
      log.textContent = s.lines.join("\n");
      log.scrollTop = log.scrollHeight;
      if (s.running) return;
      clearInterval(poll);
      autohint.textContent = s.error
        ? "出錯了，詳見上方訊息。"
        : `${r.doc} 讀取完成。重畫資料頁…`;
      hint.textContent = "";
      if (!s.error) setTimeout(viewMatrix, 1200);
    }, 1500);
  }

  fileInput.onchange = () => ingest(fileInput.files[0]);

  ["dragenter", "dragover"].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", e => ingest(e.dataTransfer.files[0]));
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
  // 換頁 / 點列都只是重畫同一份文件,使用者還盯著同一個位置看——
  // `replaceChildren` 會把捲動位置彈回頂端(2026-07-30 實測回報的症狀),
  // 記下來重畫完再還回去。真的換文件(reload)才讓它回頂端,那才是預期行為。
  const scrollY = window.scrollY;
  if (reload || !S.doc || S.doc.doc !== doc) {
    S.doc = await api("doc?doc=" + encodeURIComponent(doc));
    // 全頁數只在文件真的換了才拉一次——`pagetext` 讀的是 `locate()` 的快取,
    // 便宜,但沒必要每次翻頁都重打。
    S.nPages = (await api("pagetext?doc=" + encodeURIComponent(doc) + "&q=")).n_pages;
  }
  const d = S.doc;
  nav("doc");

  // 只驗證「在這份文件的頁數範圍內」,**不准**只認得 `d.pages`(已知候選頁)——
  // 那樣的話搜尋 / 跳頁找到的頁,一畫面重繪(點列、翻類別)就會被彈回候選頁,
  // search 跟 jump 就變成看得到按不動(2026-07-30 實測抓到,P1 的核心功能)。
  const inRange = S.page != null && S.nPages && S.page >= 0 && S.page < S.nPages;
  const page = inRange ? S.page : (d.pages && d.pages.length ? d.pages[0] : 0);
  S.page = page;

  const el = $(`<div>
    <div class="bar">
      <h1 style="margin:0">${esc(doc)}</h1>
      <a href="#/matrix" class="tag" style="text-decoration:none">← 資料</a>
      <span class="tag" id="jobtag" hidden></span>
    </div>
    <div class="two">
      <div id="cls" style="display:flex;flex-direction:column;gap:12px"></div>
      <div class="side">
        <div class="card">
          <div class="bar" style="margin:0 0 8px">
            <span class="muted">來源頁</span>
            <span id="pgs" style="display:flex;gap:4px;flex-wrap:wrap"></span>
          </div>
          <div class="bar" style="margin:0 0 8px;gap:6px">
            <button id="pgprev" ${page <= 0 ? "disabled" : ""}>← 上一頁</button>
            <button id="pgnext" ${S.nPages && page >= S.nPages - 1 ? "disabled" : ""}>下一頁 →</button>
            <input id="pgjump" type="number" min="1" max="${S.nPages || 1}" style="width:64px"
              placeholder="p.?" value="${page + 1}">
            <button id="pgjumpgo">跳頁</button>
            <span class="muted">共 ${S.nPages || "?"} 頁</span>
          </div>
          <div class="bar" style="margin:0 0 8px;gap:6px">
            <input id="pgsearch" style="flex:1;min-width:0" placeholder="搜尋這份 PDF(例如貼錨值 12,216,100)">
            <button id="pgsearchgo">搜尋</button>
          </div>
          <div id="pgsearchres" class="hint" hidden></div>
          <div class="pgwrap">
            <img class="pg" id="pgimg" src="/page.png?doc=${encodeURIComponent(doc)}&page=${page}" alt="">
            <p class="hint" id="pgerr" style="color:var(--danger)" hidden></p>
          </div>
          <div class="hint">頁層級核對,不畫框。點左邊任一列,右邊翻到那列的來源頁。</div>
        </div>
      </div>
    </div>
  </div>`);

  const img = el.querySelector("#pgimg");
  const pgerr = el.querySelector("#pgerr");
  img.onerror = async () => {
    // `/page.png` 出錯時 `<img>` 只會顯示裂圖 icon——三種完全不同的成因
    // (頁碼超範圍 / PDF 不見 / pdfium 出事)長得一模一樣。這裡多打一次同一個
    // URL 把 JSON 錯誤訊息撈出來,印在圖片下面(見 plan_web_usable.md P2)。
    img.hidden = true;
    try {
      const r = await fetch(img.src);
      const j = await r.json().catch(() => null);
      pgerr.textContent = (j && j.error) || `這頁畫不出來(HTTP ${r.status})。`;
    } catch { pgerr.textContent = "這頁畫不出來(網路錯誤)。"; }
    pgerr.hidden = false;
  };
  img.onload = () => { pgerr.hidden = true; img.hidden = false; };

  el.querySelector("#pgprev").onclick = () => { S.page = page - 1; viewDoc(doc); };
  el.querySelector("#pgnext").onclick = () => { S.page = page + 1; viewDoc(doc); };
  const jumpTo = () => {
    const v = Number(el.querySelector("#pgjump").value) - 1;
    if (!Number.isInteger(v) || v < 0 || (S.nPages && v >= S.nPages)) {
      alert(`頁碼要是 1 到 ${S.nPages || "?"} 之間的整數。`); return;
    }
    S.page = v; viewDoc(doc);
  };
  el.querySelector("#pgjumpgo").onclick = jumpTo;
  el.querySelector("#pgjump").onkeydown = (e) => { if (e.key === "Enter") jumpTo(); };

  const doSearch = async () => {
    const q = el.querySelector("#pgsearch").value.trim();
    const res = el.querySelector("#pgsearchres");
    if (!q) { res.hidden = true; return; }
    const r = await api(`pagetext?doc=${encodeURIComponent(doc)}&q=${encodeURIComponent(q)}`);
    res.hidden = false;
    res.innerHTML = r.hits.length
      ? `找到 ${r.hits.length} 頁:` + r.hits.map(h =>
          `<a href="#" data-p="${h.page}" style="margin-right:8px">p.${h.page + 1}</a>`).join("")
      : "沒找到。";
    res.querySelectorAll("[data-p]").forEach(a => a.onclick = (e) => {
      e.preventDefault(); S.page = Number(a.dataset.p); viewDoc(doc);
    });
  };
  el.querySelector("#pgsearchgo").onclick = doSearch;
  el.querySelector("#pgsearch").onkeydown = (e) => { if (e.key === "Enter") doSearch(); };

  const host = el.querySelector("#cls");
  const flat = [];
  for (const cls of CLS) {
    const v = d.classes[cls];
    // 真的沒有錨(≤2022 掃描影像那批,§6③ 待裁示)今天沒有任何工具幫得上忙,
    // 跳過不畫;錨有但候選頁是空的(v.status 仍是 "na" 但 v.anchor 不是 null)
    // 要畫出來,不然「指定候選頁」永遠沒有入口可以按。
    if (v.status === "na" && v.anchor == null) continue;
    host.appendChild(
      v.status === "no_data" ? clsNoData(doc, cls, v)
      : v.cell ? clsDone(doc, cls, v.cell, flat)
      : clsTodo(doc, cls, v.fill, v.status, v.reason, v.anchor, v.submitted, v.v4_cell));
  }
  S._flat = flat;

  const pgs = el.querySelector("#pgs");
  d.pages.forEach(p => {
    const b = $(`<button style="padding:2px 8px${p === page ? ";border-color:var(--accent);color:var(--accent)" : ""}">p.${p + 1}</button>`);
    b.onclick = () => { S.page = p; viewDoc(doc); };
    pgs.appendChild(b);
  });

  document.getElementById("app").replaceChildren(el);
  if (reload) {
    const c = host.querySelector(".row.cur");
    if (c) c.scrollIntoView({ block: "nearest" });
  } else {
    window.scrollTo(0, scrollY);
  }
}

// 重抄前的確認框——**要說實話**。舊文案寫「舊版存進歷史」,但 `fill.py`
// 直到 P3 才真的存(`work/history/`),之前那句話是不實的。如果這格有人工列
// (`row._src`,W2 加的手改能力),把名字列出來——不然人不知道自己要丟掉的
// 是機器抄的還是自己剛改過的(plan_web_usable.md P3)。
function confirmOverwrite(doc, cls, cell) {
  const manual = cell.records.flatMap(r => r.rows).filter(r => r.manual).map(r => r.name);
  const warn = manual.length
    ? `\n\n⚠️ 這裡面有 ${manual.length} 列是人工改過的:\n` + manual.map(n => `· ${n}`).join("\n")
    : "";
  return confirm(`重抄 ${doc} ${cls}?\n現有內容會被覆蓋(舊版存進 work/history/,` +
    `未 commit 前可以救回)。${warn}`);
}

// 已抄的一類:逐列 + 桶。未收錄的列標紅,因為那是要你處理的東西。
function clsDone(doc, cls, cell, flat) {
  const bad = cell.records.reduce((n, r) => n + r.rows.filter(x => !x.bucket).length, 0);
  const checks = cell.checks || { ok: true, problems: {} };
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(cell.anchor)}</span>
      <div style="margin-left:auto;display:flex;align-items:center;gap:6px">
        <button data-pageopt style="font-size:12px;padding:2px 8px" title="指定特定頁碼（選填，留空則全自動掃描全份 PDF）">⚙️ 指定頁碼</button>
        <select data-model style="font-size:12px;padding:2px 6px">
          <option value="claude">Claude CLI</option>
          <option value="deepseek">DeepSeek API</option>
        </select>
        <button class="dan" data-re>重抄</button>
      </div>
    </div>
    ${!checks.ok ? `<p class="hint" style="margin:0 0 8px;color:var(--warn)">
        檢查未全過:
        ${Object.entries(checks.problems).map(([k, v]) => esc(`${k}:${v}`)).join(' · ')}</p>` : ""}
    <div class="tabs" data-tabs></div>
    <div data-panels></div>
  </div>`);
  const tabs = card.querySelector("[data-tabs]");
  const panels = card.querySelector("[data-panels]");
  // 一份 record = 一張明細表 = 一頁。分頁顯示,不再上下疊(2026-07-30 使用者
  // 實測:三份疊成一長條,分不出自己在看哪一張表)。
  let active = 0;
  cell.records.forEach((rec, ri) => {
    const panel = $(`<div${ri ? ' style="display:none"' : ""}></div>`);
    const sec = $(`<div class="sec">${esc(rec.source_kind)} · p.${rec.source_page + 1}
      <span class="bk">${esc(rec.total_col)} = ${num(rec.printed_total)}</span>
      <span class="i" data-addrow style="margin-left:6px">+ 新增列</span></div>`);
    sec.querySelector("[data-addrow]").onclick = () => addRowForm(doc, cls, rec, sec);
    panel.appendChild(sec);
    const rows = $(`<div class="rows" style="max-height:340px;overflow:auto"></div>`);
    let lastG = null;
    rec.rows.forEach(r => {
      if (r.group && r.group !== lastG) {
        rows.appendChild($(`<div class="blk">${esc(r.group)}</div>`));
        lastG = r.group;
      }
      const n = flat.length;
      // 鍵盤上下鍵走的是跨 record 的一條扁平列表;現在的游標落在哪一份,
      // 就預設開哪一頁,不然按了方向鍵會看到「什麼都沒動」。
      if (n === S.rowIdx) active = ri;
      flat.push({ ...r, page: rec.source_page });
      rows.appendChild(rowView(doc, cls, rec, r, n));
    });
    panel.appendChild(rows);
    panels.appendChild(panel);

    const t = $(`<button>${esc(rec.source_kind)} · p.${rec.source_page + 1}
      <span class="tag" style="margin-left:4px">${rec.rows.length} 列</span></button>`);
    t.onclick = () => {
      [...panels.children].forEach((p, i) => p.style.display = i === ri ? "" : "none");
      [...tabs.children].forEach((b, i) => b.classList.toggle("on", i === ri));
      showEvidence(doc, rec.source_page);
    };
    tabs.appendChild(t);
  });
  if (cell.records.length < 2) tabs.style.display = "none";
  if (tabs.children[active]) {
    [...panels.children].forEach((p, i) => p.style.display = i === active ? "" : "none");
    tabs.children[active].classList.add("on");
  }
  card.querySelector("[data-re]").onclick = async () => {
    if (!confirmOverwrite(doc, cls, cell)) return;
    const m = card.querySelector("[data-model]").value;
    await runCell(doc, cls, m);
  };
  const optBtn = card.querySelector("[data-pageopt]");
  if (optBtn) {
    optBtn.onclick = async () => {
      const pageStr = prompt(`指定 ${cls} 抄錄頁碼(選填,留空則全自動掃描全份 PDF):\n目前正瀏覽 p.${(S.page || 0) + 1}`, "");
      if (pageStr == null) return;
      const val = pageStr.trim();
      if (!val) {
        await post("cellmeta/clear", { doc, cls, field: "pages" });
        alert("已重置為全自動掃描全份 PDF");
      } else {
        const pages = val.split(",").map(x => Number(x.trim()) - 1).filter(x => Number.isInteger(x) && x >= 0);
        if (!pages.length) { alert("頁碼格式不對"); return; }
        await post("cellmeta", { doc, cls, field: "pages", value: pages, why: "人工指定頁碼" });
        alert(`已指定頁碼: p.${pages.map(p => p + 1).join(",")}`);
      }
    };
  }
  return card;
}

// 「用目前頁重抄」(plan_web_usable.md P1)——取代「指定候選頁」原本要求先
// 打頁碼的 `prompt()`:人已經在右邊翻到那一頁了,頁碼就是 `S.page`,
// 不必再打一次字。只問理由(跟這支 app 其他裁示同一個模式)。
async function usePageOverride(doc, cls, cell) {
  if (cell && !confirmOverwrite(doc, cls, cell)) return;
  const why = prompt(`用「p.${S.page + 1}」當 ${cls} 的來源頁重抄,理由(必填):`, "");
  if (!why || !why.trim()) { alert("沒填理由,取消。"); return; }
  const r = await post("cellmeta", { doc, cls, field: "pages", value: [S.page], why });
  if (r.error) { alert(r.error); return; }
  await runCell(doc, cls);
}

// 一列的顯示態:點列本體照舊跳來源頁,✎/× 是編輯/刪除(2026-07-30 加,
// plan_web_complete.md W2)。人工列(帶 `_src`)標一個小記號,不是為了美觀——
// 是要讓人一眼看出「這格不是機器抄的,是有人看過原始頁面改的」。
function rowView(doc, cls, rec, r, n) {
  const div = $(`<div class="row ${n === S.rowIdx ? "cur" : ""} ${r.bucket ? "" : "p"}">
    <span class="nm">${r.manual ? '<span title="人工改過" style="margin-right:4px">✎</span>' : ""}${esc(r.name)}</span>
    <span class="vl">${num(r.value)}</span>
    <span class="bk">${r.bucket ? esc(r.bucket) : "未收錄"}</span>
    <span class="i" data-e title="編輯">✎</span>
    <span class="i" data-d title="刪除">×</span>
  </div>`);
  div.onclick = (e) => {
    if (e.target.closest("[data-e],[data-d]")) return;
    S.rowIdx = n; S.page = rec.source_page; viewDoc(doc);
  };
  div.querySelector("[data-e]").onclick = (e) => {
    e.stopPropagation();
    div.replaceWith(rowEditForm(doc, cls, rec, r));
  };
  div.querySelector("[data-d]").onclick = async (e) => {
    e.stopPropagation();
    if (!confirm(`刪除「${r.name}」這一列?`)) return;
    const why = prompt("理由(必填,會記進稽核):", "");
    if (!why || !why.trim()) { alert("沒填理由,取消刪除。"); return; }
    const res = await post("row", { doc, cls, record_index: rec.record_index,
                                    row_index: r.row_index, row: null, why });
    if (res.error) { alert(res.error); return; }
    viewDoc(doc, { reload: true });
  };
  return div;
}

// 編輯表單:只給這份 record 已知的欄位(rec.cols),留白 = 這欄不適用
// (照抄 fill.RULES「缺的欄不放 key」的規矩,不是隨便留白)。
function rowEditForm(doc, cls, rec, r) {
  const cols = rec.cols.length ? rec.cols : Object.keys(r.cols || {});
  const el = $(`<div class="row" style="flex-direction:column;align-items:stretch;gap:6px;cursor:default;background:var(--panel2)">
    <div class="bar" style="margin:0;gap:6px">
      <input data-name value="${esc(r.name)}" style="flex:1;min-width:0" placeholder="名字">
      <input data-group value="${esc(r.group || "")}" style="width:110px" placeholder="分段(選填)">
    </div>
    <div class="bar" style="margin:0;gap:6px;flex-wrap:wrap">
      ${cols.map(c => `<label style="font-size:11px;color:var(--mute);display:flex;flex-direction:column;gap:2px">
        ${esc(c)}<input data-col="${esc(c)}" value="${r.cols && r.cols[c] != null ? r.cols[c] : ""}" style="width:110px"></label>`).join("")}
    </div>
    <input data-why placeholder="改的理由(必填)">
    <div class="bar" style="margin:0">
      <button data-save class="pri">存</button>
      <button data-cancel>取消</button>
    </div>
  </div>`);
  // 取消:整頁重畫(不打 API,S.doc 還在快取裡,便宜)——比自己重建那個
  // .row 節點簡單,而且不會漏掉 flat/S.rowIdx 的簿記。
  el.querySelector("[data-cancel]").onclick = () => viewDoc(doc);
  el.querySelector("[data-save]").onclick = async () => {
    const name = el.querySelector("[data-name]").value.trim();
    const group = el.querySelector("[data-group]").value.trim();
    const why = el.querySelector("[data-why]").value.trim();
    if (!name) { alert("名字不能空白。"); return; }
    if (!why) { alert("一定要填理由。"); return; }
    const colsOut = {};
    for (const inp of el.querySelectorAll("[data-col]")) {
      const raw = inp.value.trim().replace(/,/g, "");
      if (!raw) continue;
      const v = Number(raw);
      if (!Number.isInteger(v)) { alert(`「${inp.dataset.col}」不是整數:${inp.value}`); throw new Error("abort"); }
      colsOut[inp.dataset.col] = v;
    }
    const row = { name, cols: colsOut };
    if (group) row.group = group;
    const res = await post("row", { doc, cls, record_index: rec.record_index,
                                    row_index: r.row_index, row, why });
    if (res.error) { alert(res.error); return; }
    viewDoc(doc, { reload: true });
  };
  return el;
}

// 新增列表單:掛在該 record 的 section header 下面,存了之後整頁重畫。
function addRowForm(doc, cls, rec, afterEl) {
  const cols = rec.cols;
  const el = $(`<div class="row" style="flex-direction:column;align-items:stretch;gap:6px;cursor:default;background:var(--panel2)">
    <div class="bar" style="margin:0;gap:6px">
      <input data-name style="flex:1;min-width:0" placeholder="名字">
      <input data-group style="width:110px" placeholder="分段(選填)">
    </div>
    <div class="bar" style="margin:0;gap:6px;flex-wrap:wrap">
      ${cols.map(c => `<label style="font-size:11px;color:var(--mute);display:flex;flex-direction:column;gap:2px">
        ${esc(c)}<input data-col="${esc(c)}" style="width:110px"></label>`).join("")}
    </div>
    <input data-why placeholder="補這一列的理由(必填)">
    <div class="bar" style="margin:0">
      <button data-save class="pri">存</button>
      <button data-cancel>取消</button>
    </div>
  </div>`);
  el.querySelector("[data-cancel]").onclick = () => el.remove();
  el.querySelector("[data-save]").onclick = async () => {
    const name = el.querySelector("[data-name]").value.trim();
    const group = el.querySelector("[data-group]").value.trim();
    const why = el.querySelector("[data-why]").value.trim();
    if (!name) { alert("名字不能空白。"); return; }
    if (!why) { alert("一定要填理由。"); return; }
    const colsOut = {};
    for (const inp of el.querySelectorAll("[data-col]")) {
      const raw = inp.value.trim().replace(/,/g, "");
      if (!raw) continue;
      const v = Number(raw);
      if (!Number.isInteger(v)) { alert(`「${inp.dataset.col}」不是整數:${inp.value}`); throw new Error("abort"); }
      colsOut[inp.dataset.col] = v;
    }
    const row = { name, cols: colsOut };
    if (group) row.group = group;
    const res = await post("row", { doc, cls, record_index: rec.record_index,
                                    row_index: null, row, why });
    if (res.error) { alert(res.error); return; }
    viewDoc(doc, { reload: true });
  };
  afterEl.after(el);
}

// ── 格層級的人工裁示(2026-07-30 加,plan_web_complete.md W3)──────────────
// 「指定候選頁」解兩種卡住:①錨有、grep 找不到候選頁(今天 2 格)
// ②候選頁都在,但模型抄到彙總層不是明細層(今天 ~15 筆)。
// 「標記無資料」跟「還沒抄」是兩件事,必須分得開——這是人翻過原始頁面
// 確認的最終判斷,不是排隊等抄。
async function setPagesOverride(doc, cls) {
  const raw = prompt("要指定哪幾頁?(頁碼從 1 開始,逗號分隔,例如 39,40)", "");
  if (raw == null) return false;
  const pages = raw.split(",").map(s => s.trim()).filter(Boolean).map(Number);
  if (!pages.length || pages.some(p => !Number.isInteger(p) || p < 1)) {
    alert("頁碼格式不對(要是逗號分隔的正整數),取消。");
    return false;
  }
  const why = prompt("理由(必填):", "");
  if (!why || !why.trim()) { alert("沒填理由,取消。"); return false; }
  const r = await post("cellmeta", { doc, cls, field: "pages",
                                     value: pages.map(p => p - 1), why });
  if (r.error) { alert(r.error); return false; }
  return true;
}

async function markNoData(doc, cls) {
  if (!confirm(`標記「${cls}」這一類在「${doc}」裡真的沒有這項揭露?\n\n請先確認已經翻過原始財報附註。`)) return;
  const why = prompt("理由(必填,例如:翻過全份財報附註,沒有這張表):", "");
  if (!why || !why.trim()) { alert("沒填理由,取消。"); return; }
  const r = await post("cellmeta", { doc, cls, field: "no_data", value: true, why });
  if (r.error) { alert(r.error); return; }
  viewDoc(doc, { reload: true });
}

// 已標記無資料的一類:給一眼看得懂的稽核紀錄 + 取消標記(裁示錯了可以撤銷,
// 不強制填理由——撤銷不是新判斷,是承認上一個判斷是錯的)。
function clsNoData(doc, cls, v) {
  const m = v.meta || {};
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">已標記無資料</span>
      <button style="margin-left:auto" data-undo>取消標記</button>
    </div>
    <p class="hint" style="margin:0">${esc(m.by || "")} · ${esc(m.at || "")} · ${esc(m.why || "")}</p>
  </div>`);
  card.querySelector("[data-undo]").onclick = async () => {
    const r = await post("cellmeta/clear", { doc, cls, field: "no_data" });
    if (!r.cleared) { alert("沒有標記可以清 —— 可能已經被別處理掉了。"); return; }
    viewDoc(doc, { reload: true });
  };
  return card;
}

// 還沒抄的一類:一顆按鈕,不必跳到另一頁。手動貼 JSON 收在摺疊裡 ——
// 自動抄列是常態,手動是例外,版面要照這個比例。
//
// `status` 是 todo / blocked / rejected / na 之一(2026-07-30 加)。後三者
// **曾經跟 todo 長得一模一樣**——網頁上看不出這格其實抄過、擴頁到上限、
// 卡在哪,只能重新手動貼一次。現在把 `reason` 印出來,並給一顆「退回重抄」
// (呼叫 /api/requeue 清掉標記檔,再照常跑自動抄列)。
function clsTodo(doc, cls, f, status, reason, anchor, submitted, v4_cell) {
  const stuck = status === "blocked" || status === "rejected";
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(anchor || (f ? f.anchor : null))}</span>
      <div style="margin-left:auto;display:flex;align-items:center;gap:6px">
        <button data-pageopt style="font-size:12px;padding:2px 8px" title="指定特定頁碼（選填，留空則全自動掃描全份 PDF）">⚙️ 指定頁碼</button>
        <select data-model style="font-size:12px;padding:2px 6px">
          <option value="claude">Claude CLI</option>
          <option value="deepseek">DeepSeek API</option>
        </select>
        <button class="pri" data-go>抄這格</button>
      </div>
    </div>
    ${v4_cell ? `<div class="wcard" style="margin:8px 0">
        <h3>
          <span class="badge ${v4_cell.status}">${v4_cell.status}</span>
          <span style="margin-left:8px;font-weight:400;font-size:12px;color:var(--mute)">v4 驗證與讀取結果 (小計: ${num((v4_cell.book || {}).total)})</span>
        </h3>
        <div data-v4ws></div>
        <div data-v4rows style="margin:8px 0;max-height:220px;overflow:auto;border-top:1px solid var(--line);padding-top:6px"></div>
        <div class="bar" style="margin:8px 0 0;gap:8px">
          <button class="pri" data-v4ratify>我看過原始頁，照這樣歸檔</button>
          <input data-v4reason placeholder="理由(選填)" style="flex:1;min-width:0">
        </div>
      </div>` : ""}
    <div class="bar" style="margin:8px 0;gap:10px">
      <span class="i" data-nodata>標記無資料</span>
    </div>
    <p class="hint" style="margin:0">選擇模型後按「抄這格」，自動讀取全份 PDF 並進行四道 Witness 機械驗證。</p>
    <details style="margin-top:8px">
      <summary class="muted" style="cursor:pointer;font-size:12px">手動貼 JSON</summary>
      <textarea data-ed spellcheck="false" style="margin-top:6px"></textarea>
      <div class="bar" style="margin:8px 0 0">
        <button data-sub>送出(驗證照跑)</button>
      </div>
      <pre data-out class="tr" style="display:none;max-height:220px;overflow:auto"></pre>
    </details>
  </div>`);

  if (v4_cell) {
    const wsWrap = card.querySelector("[data-v4ws]");
    Object.entries(v4_cell.witnesses || {}).forEach(([name, w]) => {
      wsWrap.appendChild($(`<div class="w ${w.status}">
        <span class="name">${esc(name)}</span>
        <span class="st">${esc(w.status)}</span>
        ${w.diff != null ? `<span class="diff">diff ${num(w.diff)}</span>` : ""}
      </div>`));
    });

    const rowsWrap = card.querySelector("[data-v4rows]");
    const book = v4_cell.book || {};
    const page1Based = book.page;
    if ((book.rows || []).length) {
      book.rows.forEach(r => {
        const rowEl = $(`<div class="row">
          <span class="nm">${esc(r.name)}</span>
          <span class="vl">${num(r.amount)}</span>
        </div>`);
        if (page1Based) {
          rowEl.onclick = () => showEvidence(doc, page1Based - 1);
        }
        rowsWrap.appendChild(rowEl);
      });
    } else {
      rowsWrap.appendChild($(`<p class="hint" style="margin:0">無明細數據。</p>`));
    }

    card.querySelector("[data-v4ratify]").onclick = async () => {
      const reason = card.querySelector("[data-v4reason]").value.trim() || "v4 頁面人工確認歸檔";
      try {
        await post("v4/ratify", { doc, cls, reason });
        viewDoc(doc, { reload: true });
      } catch(e) { /* error handled by _checked */ }
    };
  }
  card.querySelector("[data-go]").onclick = async () => {
    if (stuck) await post("requeue", { cell_key: `${doc}|${cls}` });
    const m = card.querySelector("[data-model]").value;
    runCell(doc, cls, m);
  };
  const reqBtn = card.querySelector("[data-req]");
  if (reqBtn) reqBtn.onclick = async () => {
    const r = await post("requeue", { cell_key: `${doc}|${cls}` });
    if (!r.removed) { alert("沒有標記檔可以清 —— 可能已經被別處理掉了。"); return; }
    viewDoc(doc, { reload: true });
  };
  const optBtn = card.querySelector("[data-pageopt]");
  if (optBtn) {
    optBtn.onclick = async () => {
      const pageStr = prompt(`指定 ${cls} 抄錄頁碼(選填,留空則全自動掃描全份 PDF):\n目前正瀏覽 p.${(S.page || 0) + 1}`, "");
      if (pageStr == null) return;
      const val = pageStr.trim();
      if (!val) {
        await post("cellmeta/clear", { doc, cls, field: "pages" });
        alert("已重置為全自動掃描全份 PDF");
      } else {
        const pages = val.split(",").map(x => Number(x.trim()) - 1).filter(x => Number.isInteger(x) && x >= 0);
        if (!pages.length) { alert("頁碼格式不對"); return; }
        await post("cellmeta", { doc, cls, field: "pages", value: pages, why: "人工指定頁碼" });
        alert(`已指定頁碼: p.${pages.map(p => p + 1).join(",")}`);
      }
    };
  }
  card.querySelector("[data-nodata]").onclick = () => markNoData(doc, cls);
  // 手動貼 JSON 的預設內容:有被拒收的東西就**貼那個**,不是空模板。
  // 拒收的資料本來就抄好了,要修的往往只是 total_col 一個欄位(實測 25 個
  // REJECT 裡有 6 個是這型),從空白重打一次是白費工。
  card.querySelector("[data-ed]").value =
    JSON.stringify(submitted || f.template, null, 1);
  card.querySelector("[data-sub]").onclick = async () => {
    const out = card.querySelector("[data-out]");
    let body;
    try { body = JSON.parse(card.querySelector("[data-ed]").value); }
    catch (err) { out.style.display = "block"; out.textContent = "JSON 解析失敗:" + err.message; return; }
    const r = await post("submit", { doc, cls, pages: f.pages, records: body.records });
    out.style.display = "block"; out.textContent = r.output || r.error || "";
    if (r.status === "PASS") setTimeout(() => viewDoc(doc, { reload: true }), 900);
  };
  const rejEl = card.querySelector("[data-rej]");
  if (submitted && rejEl) rejEl.appendChild(rejectedPanel(doc, cls, submitted, card));
  return card;
}

// 被拒收那一格的資料**看得到、改得動、裁示得了**(plan_web_usable.md P4)。
//
// 在這之前,rejected 的格子在網頁上是死路:模型抄出來的 rows 躺在
// work/rejected/ 裡,畫面只給一行紅字理由。指定頁沒用(頁是對的)、
// 標記無資料是錯的(有資料)、退回重抄會撞同一道閘門、手動貼 JSON 走
// submit() 也是同一道閘門。**唯一缺的是「我看過原始頁,事實就是這樣」
// 這句話的出口**(plan_web_complete.md §1 的根因)。
function rejectedPanel(doc, cls, submitted, card) {
  const recs = submitted.records || [];
  const wrap = $(`<details style="margin:0 0 8px" open>
    <summary class="muted" style="cursor:pointer;font-size:12px">
      模型抄出來的內容(${recs.reduce((n, r) => n + (r.rows || []).length, 0)} 列)——可以改,也可以直接裁示放行</summary>
    <div class="tabs" data-tabs style="margin-top:6px"></div>
    <div data-body style="margin-top:6px"></div>
    <div class="bar" style="margin:8px 0 0;gap:8px">
      <button class="pri" data-ratify>我看過原始頁,照這樣歸檔</button>
      <span class="muted">六道照跑、結果照記,但不擋歸檔;每一列會蓋上人工來源記號</span>
    </div>
  </details>`);
  const body = wrap.querySelector("[data-body]");
  const tabs = wrap.querySelector("[data-tabs]");

  recs.forEach((rec, ri) => {
    // 同 clsDone:多份 record 改分頁,一次只看一張表。
    const panel = $(`<div${ri ? ' style="display:none"' : ""}></div>`);
    body.appendChild(panel);
    const tab = $(`<button${ri ? "" : ' class="on"'}>${esc(rec.source_kind || "表")} ·
      p.${(rec.source_page ?? 0) + 1}
      <span class="tag" style="margin-left:4px">${(rec.rows || []).length} 列</span></button>`);
    tab.onclick = () => {
      [...body.children].forEach((p, i) => p.style.display = i === ri ? "" : "none");
      [...tabs.children].forEach((b, i) => b.classList.toggle("on", i === ri));
      showEvidence(doc, rec.source_page);
    };
    tabs.appendChild(tab);
    // total_col 是可推導的:「哪一欄的列和 == 錨」在 185 份 record 上唯一且全對
    // (plan_web_complete.md 附錄)。所以這裡把每一欄的列和都算出來擺在旁邊,
    // 挑錯欄的那型一眼就看得出來該選哪個——不必自己按計算機。
    const cols = [...new Set(rec.rows.flatMap(r => Object.keys(r.cols || {})))];
    const sums = {};
    cols.forEach(c => { sums[c] = rec.rows.reduce((n, r) => n + ((r.cols || {})[c] || 0), 0); });
    const sec = $(`<div class="sec">${esc(rec.source_kind || "")} ·
      <a href="#" data-jump>p.${(rec.source_page ?? 0) + 1}</a>
      <span class="bk">合計欄 = ${esc(rec.total_col || "(未填)")}</span></div>`);
    // 點頁碼本身就能跳去右邊看那一頁——這是「判斷點 = 證據點」最直接的入口
    // (`docs/plan_schema_derive.md` §5),不必等到點欄位按鈕才連帶跳頁。
    sec.querySelector("[data-jump]").onclick = (e) => { e.preventDefault(); showEvidence(doc, rec.source_page); };
    panel.appendChild(sec);

    // 使用者實測抓到兩個問題:①「錨」只在卡片標題印一次一個小 tag,
    // 判斷「選哪一欄」的當下要往上找才知道目標數字是什麼——這裡直接把
    // BS 寫的合計數字重講一次,擺在挑欄這個判斷的正上方,不必回頭找。
    // ②「選中且對得上」的按鈕原本是 class="pri"(紫底白字)疊加內嵌樣式
    // color:var(--ok)(綠字)——inline style 蓋掉了 class 的白字,變成
    // 紫底綠字,對比度差到看不清楚。改法:選中永遠紫底白字(可讀),
    // 「對得上錨」改用打勾符號 + 未選中時才用綠色外框標示,兩種狀態不疊字色。
    const pick = $(`<div style="margin:4px 0 6px">
      <div style="font-size:12px;margin-bottom:4px">
        資產負債表(BS)這科目的合計 = <b>${num(f_anchor(card))}</b>
      </div>
      <div class="bar" style="margin:0 0 6px;gap:6px;flex-wrap:wrap">
        <span class="muted" style="font-size:11px">下面哪一欄的列和等於這個數字,選哪一欄當合計欄:</span>
      </div>
      <div class="bar" data-colbtns style="margin:0;gap:6px;flex-wrap:wrap"></div>
    </div>`);
    const colBtns = pick.querySelector("[data-colbtns]");
    cols.forEach(c => {
      const hit = sums[c] === f_anchor(card);
      const selected = c === rec.total_col;
      const b = $(`<button style="font-size:11px${!selected && hit ? ";border-color:var(--ok);color:var(--ok)" : ""}"
        ${selected ? 'class="pri"' : ""}>${esc(c)} = ${num(sums[c])}${hit ? " ✓" : ""}</button>`);
      // 選欄是一個判斷(哪一欄是本期)——選下去的同時把右邊的檢視器跳到
      // 這份 record 的來源頁,不是只改左邊的文字(2026-07-30 使用者實測抓到:
      // 原本選了欄,右邊的圖完全不會動,等於證據跟判斷分開在兩個世界)。
      b.onclick = () => {
        rec.total_col = c;
        rec.printed_total = sums[c];
        card.querySelector("[data-ed]").value = JSON.stringify(submitted, null, 1);
        showEvidence(doc, rec.source_page);
      };
      colBtns.appendChild(b);
    });
    panel.appendChild(pick);

    const list = $(`<div class="rows" style="max-height:260px;overflow:auto"></div>`);
    rec.rows.forEach((r, i) => {
      const v = (r.cols || {})[rec.total_col];
      const div = $(`<div class="row ${v == null ? "p" : ""}">
        <span class="nm">${esc(r.name)}</span>
        <span class="vl">${v == null ? "(此欄無值)" : num(v)}</span>
        <span class="i" data-e title="編輯">✎</span>
        <span class="i" data-d title="刪除">×</span>
      </div>`);
      // 點列本體(不是 ✎/×)也跳頁——跟已抄的列(`rowView`)同一個手感,
      // 不必先展開 details 裡的按鈕才找得到證據。
      div.onclick = (e) => {
        if (e.target.closest("[data-e],[data-d]")) return;
        showEvidence(doc, rec.source_page);
      };
      div.querySelector("[data-e]").onclick = (e) => {
        e.stopPropagation();
        const nv = prompt(`「${r.name}」在「${rec.total_col}」欄的值(留空 = 這欄沒有值):`,
                          v == null ? "" : String(v));
        if (nv === null) return;
        const t = nv.trim().replace(/,/g, "");
        if (!t) delete (r.cols || {})[rec.total_col];
        else if (Number.isInteger(Number(t))) r.cols[rec.total_col] = Number(t);
        else { alert(`不是整數:${nv}`); return; }
        card.querySelector("[data-ed]").value = JSON.stringify(submitted, null, 1);
        showEvidence(doc, rec.source_page);
      };
      div.querySelector("[data-d]").onclick = (e) => {
        e.stopPropagation();
        if (!confirm(`從這次歸檔中刪掉「${r.name}」這一列?`)) return;
        rec.rows.splice(i, 1);
        card.querySelector("[data-ed]").value = JSON.stringify(submitted, null, 1);
        showEvidence(doc, rec.source_page);
      };
      list.appendChild(div);
    });
    panel.appendChild(list);
  });

  if (recs.length < 2) tabs.style.display = "none";

  wrap.querySelector("[data-ratify]").onclick = async () => {
    // 「我看過原始頁,照這樣歸檔」是最重的裁示——按下去之前先把證據跳到
    // 眼前(§8② 使用者裁示:跳但不擋,不加強迫確認的對話框,那種閘門只會
    // 被訓練成無意識點掉)。多份 record 就跳第一份,其餘每份自己的 p.N
    // 連結都在上面點得到。
    //
    // 不再強制填理由(2026-07-30 使用者裁示,推翻原本 why 必填的決定)——
    // 這格拒收的內容(挑了哪一欄、改了哪一列)本身就是稽核軌跡,逼著每次
    // 打一行字反而會變成隨便填一句應付。後端仍然蓋 `_src.by`/`_src.at`
    // 標記「有人動過」,不強制 `why`。
    if (recs[0]) showEvidence(doc, recs[0].source_page);
    const r = await post("ratify", { doc, cls, records: recs });
    if (r.error) { alert(r.error); return; }
    if (!r.checks.ok) {
      alert("已歸檔。六道仍有不過的項目(已記錄,卡片上會標黃):\n"
        + Object.entries(r.checks.problems).map(([k, v]) => `${k}:${v}`).join("\n"));
    }
    viewDoc(doc, { reload: true });
  };
  return wrap;
}

// 從卡片標題那顆「錨 N」的 tag 讀回錨值——`rejectedPanel` 需要它來標「哪一欄
// 的列和等於錨」,但它拿到的 `submitted` 裡沒有錨(錨是 locate 算的,不是抄的)。
function f_anchor(card) {
  const t = (card.querySelector(".tag") || {}).textContent || "";
  return Number(t.replace(/[^\d]/g, "")) || null;
}

// 抄單格 —— 跟資料頁那顆按鈕走同一個後端工作,所以一次只准跑一個。
async function runCell(doc, cls, model = "claude") {
  const r = await post("autofill", { cell: `${doc}|${cls}`, reader: model });
  const tag = document.getElementById("jobtag");
  if (!r.started) { alert(r.why); return; }
  if (tag) { tag.hidden = false; tag.textContent = `抄列中… ${cls}`; }
  const t = setInterval(async () => {
    const s = await api("autofill/status");
    if (tag) tag.textContent = "抄列中… " + (s.lines[s.lines.length - 1] || "").slice(0, 60);
    if (s.running) return;
    clearInterval(t);
    const lastLine = s.lines[s.lines.length - 1] || "";
    S.page = null; S.rowIdx = 0;
    await viewDoc(doc, { reload: true });        // 剛抄完,facts/ 變了,一定要重拉
    const after = (S.doc.classes[cls] || {}).status;
    const newTag = document.getElementById("jobtag");
    if (!newTag) return;
    newTag.hidden = false;
    if (after === "blocked" || after === "rejected") {
      newTag.classList.add("w");
      newTag.textContent = `✗ ${cls} 重抄失敗(${after === "blocked" ? "分類表缺口" : "擴頁到上限仍對不上"})——見下方卡片`;
    } else if (after === "done") {
      newTag.textContent = `✓ ${cls} 抄列完成`;
      setTimeout(() => { if (document.getElementById("jobtag") === newTag) newTag.hidden = true; }, 4000);
    } else {
      newTag.textContent = lastLine.slice(0, 80);
    }
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
