const fs = require("fs");
const JSDOM = require("jsdom").JSDOM;
const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="app"></div><div id="cls"></div></body></html>`);
const window = dom.window;
global.document = window.document;
global.location = { hash: "#/doc/202404_兆豐_個體" };
global.addEventListener = () => {};
global.fetch = async () => ({
  json: async () => JSON.parse(fs.readFileSync("out.json", "utf8"))
});
function $(h) { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function num(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }
const S = { page: null, nPages: 130, rowIdx: 0 };
const CLS = ["AC", "OCI", "Trading"];
function viewDoc(doc) {
  const d = JSON.parse(fs.readFileSync("out.json", "utf8"));
  S.doc = d;
  const inRange = S.page != null && S.nPages && S.page >= 0 && S.page < S.nPages;
  const page = inRange ? S.page : (d.pages && d.pages.length ? d.pages[0] : 0);
  S.page = page;
  const el = $(`<div><div class="two"><div id="cls"></div></div></div>`);
  const host = el.querySelector("#cls");
  for (const cls of CLS) {
    const v = d.classes[cls];
    if (v.status === "na" && v.anchor == null) continue;
    host.appendChild(v.status === "no_data" ? document.createElement("div") : v.cell ? clsDone(doc, cls, v.cell, []) : clsTodo(doc, cls, v.fill, v.status, v.reason, v.anchor, v.submitted, v.v4_cell));
  }
}
// Append clsDone and clsTodo from workbench.js
function clsDone(doc, cls, cell, flat) {
  const bad = cell.records.reduce((n, r) => n + r.rows.filter(x => !x.bucket).length, 0);
  const checks = cell.checks || { ok: true, problems: {} };
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(cell.anchor)}</span>
      ${bad ? `<span class="tag w">${bad} 列未收錄</span>` : `<span class="tag">已抄</span>`}
      <span class="i" data-usepage style="margin-left:auto">用目前頁(p.${(S.page || 0) + 1})重抄</span>
      <span class="i" data-refill>手動指定多頁</span>
      <div style="display:flex;align-items:center;gap:6px">
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
  if (card.querySelector("[data-refill]")) {
    card.querySelector("[data-refill]").onclick = async () => {
      if (!(await setPagesOverride(doc, cls))) return;
      if (!confirmOverwrite(doc, cls, cell)) return;
      await runCell(doc, cls);
    };
  }
  if (card.querySelector("[data-usepage]")) {
    card.querySelector("[data-usepage]").onclick = () => usePageOverride(doc, cls, cell);
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
function clsTodo(doc, cls, f, status, reason, anchor, submitted, v4_cell) {
  const card = $(`<div class="card">
    <div class="bar" style="margin:0 0 8px">
      <b>${cls}</b>
      <span class="tag">錨 ${num(f.anchor)}</span>
      <div style="margin-left:auto;display:flex;align-items:center;gap:6px">
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
      <span class="i" data-usepage>用目前頁(p.${(S.page || 0) + 1})當候選頁</span>
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
try { viewDoc("202404_兆豐_個體"); console.log("OK"); } catch(e) { console.error(e); }
