// 配置空間 —— 選軸即選圖。取數全部由 /api/sim(=sim/axes.payload())提供,
// 這支只管畫圖。規則見 docs/plan_simulator.md §11.2 / §11.2a / §11.4a。
"use strict";

const S = {
  data: null,
  lens: "整體",          // 內部值:整體 | 揭露 | 變化 —— 只管①②,見 §11.4a
  selected: [],          // 最多 3 個 axis id,FIFO(§11.2 規則1)
  variant: {},           // { axisId: variantId } —— 每根軸各自的「用哪把尺量」,跟口徑正交
  yearIdx: 4,
  hidden: new Set(),     // 被點掉的銀行 —— 只影響「畫不畫」,不影響座標軸範圍(見 visibleBanks)
  trajectory: true,      // 1/2 軸預設顯示軌跡(§11.2「時間」)
  rot: { x: -20, y: -35 },   // 3 軸旋轉角度(度),拖曳更新,跨渲染保留
  playTimer: null,
};

// 按鈕上的字講「看不看得到」,不講桶名 —— 同一顆鈕在①是三桶、在②是 OCI+AC,
// 寫桶名一定有一根軸是錯的。精確定義走 lens_note 那行副標(見 renderLensNote)。
// 內部值不動:payload 的 lens 表、endpoints() 都還是吃 整體/揭露。
const LENS_LABEL = { "整體": "全部位", "揭露": "帳上看得到", "變化": "差多少（全部位 → 帳上）" };
const lensName = (L) => LENS_LABEL[L] || L;

let dragging = false, dragLastX = 0, dragLastY = 0;   // 拖曳狀態,監聽器只掛一次(見 setupDrag)

const $ = (sel) => document.querySelector(sel);

async function boot() {
  S.data = await fetch("/api/sim").then((r) => r.json());
  $("#src").textContent = `data.json 來源:${S.data.source}`;
  S.selected = [S.data.axes[0].id, S.data.axes[1].id];   // 預設①②,最容易看到翻轉
  renderLensSeg();
  renderAxisChips();
  renderYearSlider();
  $("#trajChk").onchange = (e) => { S.trajectory = e.target.checked; render(); };
  $("#playBtn").onclick = togglePlay;
  setupDrag();
  render();
}

// ── 口徑三態鈕 ──────────────────────────────────────────────────────
function switchableSelected() {
  return S.selected.some((id) => axisById(id).switchable);
}

function renderLensSeg() {
  const seg = $("#lensSeg");
  seg.innerHTML = "";
  for (const L of ["整體", "揭露", "變化"]) {
    const b = document.createElement("button");
    b.textContent = lensName(L);
    b.className = S.lens === L ? "on" : "";
    b.onclick = () => { S.lens = L; renderLensSeg(); render(); };
    seg.appendChild(b);
  }
  const enabled = switchableSelected();
  seg.querySelectorAll("button").forEach((b) => { b.disabled = !enabled; });
  if (!enabled && S.lens !== "整體") {
    // 選到的軸都不能切 → 口徑鈕灰掉,自動退回「整體」(§11.4a)
    S.lens = "整體";
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.textContent === lensName("整體")));
  }
}

// 「帳上看得到／全部位」在每根軸上是哪些桶 —— 按鈕只負責直覺,精確定義在這行。
function renderLensNote() {
  const el = $("#lensNote");
  if (!el) return;
  const notes = S.selected.map(axisById).filter((a) => a.lens_note);
  el.innerHTML = notes.length
    ? notes.map((a) => `<b>${a.label}</b>：帳上看得到＝${a.lens_note["揭露"]}　全部位＝${a.lens_note["整體"]}`)
           .join("　｜　")
    : "";
}

// ── 軸 chips,最多三根,FIFO ─────────────────────────────────────────
function axisById(id) { return S.data.axes.find((a) => a.id === id); }

// 每根軸現在有好幾把尺(variants);這兩層正交(見 sim/axes.py 開頭的說明) ——
// 選哪個 variant 不影響口徑鈕能不能按,S.lens 只吃 axis.switchable。
function activeVariant(axis) {
  const vid = S.variant[axis.id] || axis.default;
  return axis.variants.find((v) => v.id === vid) || axis.variants[0];
}

// 把「軸 + 目前選的 variant」併成畫圖函式原本吃的形狀(lens/unit/hint/label),
// 下面所有 dotPlot/quadrant/... 都不用改,只要在 render() 這一層先 resolve 過。
function resolveAxis(axis) {
  const v = activeVariant(axis);
  return {
    id: axis.id, switchable: axis.switchable, lens: v.lens,
    label: axis.variants.length > 1 ? `${axis.label}·${v.label}` : axis.label,
    unit: v.unit, hint: v.hint, caveat: v.caveat, more: v.more, invert: !!v.invert,
  };
}

function renderAxisChips() {
  const box = $("#axisChips");
  box.innerHTML = "";
  S.data.axes.forEach((a) => {
    const defV = a.variants.find((v) => v.id === a.default) || a.variants[0];
    const sub = (a.variants.length > 1 ? `${a.variants.length} 種定義可選` : defV.hint) +
      (a.switchable ? "" : "・不隨口徑切換");
    const chip = document.createElement("div");
    const order = S.selected.indexOf(a.id);
    chip.className = "chip" + (order >= 0 ? " sel" : "");
    chip.innerHTML =
      (order >= 0 ? `<span class="n"><span class="ord">${order + 1}</span>${a.label}</span>` : `<span class="n">${a.label}</span>`) +
      `<span class="s">${sub}</span>`;
    chip.onclick = () => toggleAxis(a.id);
    box.appendChild(chip);
  });
}

// 定義選單 —— 只給目前選中的軸各畫一組,沒選到的軸不佔版面。
function renderVariantBar(axes) {
  const bar = $("#variantBar");
  const withChoice = axes.filter((a) => a.variants.length > 1);
  if (!withChoice.length) { bar.style.display = "none"; return; }
  bar.style.display = "flex";
  bar.innerHTML = "";
  withChoice.forEach((a) => {
    const grp = document.createElement("div");
    grp.className = "vgrp";
    const lbl = document.createElement("span");
    lbl.className = "vlbl"; lbl.textContent = `${a.label}定義`;
    grp.appendChild(lbl);
    const seg = document.createElement("div");
    seg.className = "ix-seg";
    const cur = activeVariant(a).id;
    a.variants.forEach((v) => {
      const b = document.createElement("button");
      b.textContent = v.label;
      b.className = v.id === cur ? "on" : "";
      b.onclick = () => { S.variant[a.id] = v.id; render(); };
      seg.appendChild(b);
    });
    grp.appendChild(seg);
    bar.appendChild(grp);
  });
}

function toggleAxis(id) {
  const i = S.selected.indexOf(id);
  if (i >= 0) {
    S.selected.splice(i, 1);
  } else {
    S.selected.push(id);
    if (S.selected.length > 3) S.selected.shift();   // 最多三根,FIFO(§11.2 規則1)
  }
  renderAxisChips();
  renderLensSeg();
  render();
}

// ── 年份滑桿 + 播放鈕 ──────────────────────────────────────────────
function renderYearSlider() {
  const s = $("#yearSlider");
  s.max = S.data.years.length - 1;
  s.value = S.yearIdx;
  $("#yearVal").textContent = S.data.years[S.yearIdx];
  s.oninput = () => {
    S.yearIdx = +s.value;
    $("#yearVal").textContent = S.data.years[S.yearIdx];
    render();
  };
}

function togglePlay() {
  const btn = $("#playBtn");
  if (S.playTimer) {
    clearInterval(S.playTimer); S.playTimer = null;
    btn.classList.remove("on"); btn.textContent = "▶";
    return;
  }
  btn.classList.add("on"); btn.textContent = "❚❚";
  S.playTimer = setInterval(() => {
    S.yearIdx = (S.yearIdx + 1) % S.data.years.length;
    $("#yearSlider").value = S.yearIdx;
    $("#yearVal").textContent = S.data.years[S.yearIdx];
    render();
  }, 800);
}

// 軌跡開著時年份滑桿沒有作用(軌跡本身就顯示全部年份),灰掉並停止播放。
function updateTimeControls(trajOn) {
  const slider = $("#yearSlider"), play = $("#playBtn"), row = slider.closest(".yr");
  slider.disabled = trajOn;
  play.disabled = trajOn;
  row.classList.toggle("off", trajOn);
  if (trajOn && S.playTimer) togglePlay();
}

// 軌跡勾選:只在 1/2 軸、非「變化」時可用(§11.2 規則8 的延伸;3 軸另有播放鈕)。
function renderTrajToggle(axesLen) {
  const wrap = $("#trajTgl"), chk = $("#trajChk");
  if (axesLen === 0) { wrap.style.display = "none"; return; }
  wrap.style.display = "flex";
  const allowed = S.lens !== "變化";
  chk.disabled = !allowed;
  wrap.classList.toggle("off", !allowed);
  chk.checked = allowed && S.trajectory;
}

// ── 取值 ─────────────────────────────────────────────────────────────
// 給定軸與口徑,回該軸在該口徑下的值;非 switchable 軸一律用「整體」那份。
function valAt(axis, lens, year, bank) {
  const key = `${year}|${bank}`;
  const table = axis.lens[lens] || axis.lens["整體"];
  return table[key] ?? null;
}

// 變化模式下,每家銀行回 {from(全部位/整體), to(帳上看得到/揭露)};非 switchable 軸兩端相同(§11.2a 混選規則)。
function endpoints(axis, year, bank) {
  const from = valAt(axis, "整體", year, bank);
  const to = axis.switchable ? valAt(axis, "揭露", year, bank) : from;
  return { from, to };
}

function fmt(v, unit) {
  return v === null || v === undefined ? "—" : `${v.toFixed(2)}${unit}`;
}

// 目前要畫的銀行。
// ★ 刻意只影響「畫不畫」,**不影響座標軸範圍** —— 範圍一律用五家算。
// 點掉一家如果整張圖的刻度跟著跳,剩下的點會平移,反而看不出「這家原本在哪」。
// 要的是清場,不是放大。
function visibleBanks() {
  return S.data.banks.filter((b) => !S.hidden.has(b));
}

// ── 主渲染 ───────────────────────────────────────────────────────────
function render() {
  const year = S.data.years[S.yearIdx];
  const rawAxes = S.selected.map(axisById);
  const axes = rawAxes.map(resolveAxis);
  renderVariantBar(rawAxes);
  renderLensNote();
  renderHint(axes);
  renderFlags(year);
  renderTrajToggle(axes.length);
  const trajOn = axes.length > 0 && S.lens !== "變化" && S.trajectory;
  updateTimeControls(trajOn);
  const wrap = $("#plotWrap");
  wrap.innerHTML = "";
  if (axes.length === 0) {
    wrap.innerHTML = `<div class="empty">選一根軸開始</div>`;
    $("#legend").innerHTML = "";
    return;
  }
  if (axes.length === 1) {
    wrap.appendChild(
      S.lens === "變化" ? dumbbell(axes[0], year) :
      trajOn ? dotPlotTrajectory(axes[0]) : dotPlot(axes[0], year));
  } else if (axes.length === 2) {
    wrap.appendChild(
      S.lens === "變化" ? arrowScatter(axes[0], axes[1], year) :
      trajOn ? quadrantTrajectory(axes[0], axes[1]) : quadrant(axes[0], axes[1], year));
  } else {
    wrap.appendChild(threeD(axes, year, trajOn));
  }
  renderLegend(axes);
}

function renderHint(axes) {
  const el = $("#plotHint");
  const cav = $("#caveat");
  if (axes.length === 0) { el.textContent = ""; cav.textContent = ""; return; }
  const parts = axes.map((a) => `<b>${a.label}</b>(${a.hint})`);
  let extra = "";
  if (S.lens === "變化") extra += "　—　棒/箭頭長度＝被藏起來的那一段，兩點重疊代表這根軸看不看得到都一樣";
  if (axes.length === 3) {
    extra += S.lens === "變化" ? "　—　拖曳可旋轉；播放鈕看逐年變化"
      : (S.trajectory ? "　—　拖曳可旋轉；軌跡＝5期路徑，最新一期較大"
                      : "　—　拖曳可旋轉；播放鈕看逐年變化");
  }
  el.innerHTML = parts.join("　×　") + extra;
  const caveats = axes.filter((a) => a.caveat).map((a) => `${a.label}：${a.caveat}`);
  cav.innerHTML = caveats.length ? "⚠️ " + caveats.join("　｜　") : "";
}

function renderLegend(axes) {
  const el = $("#legend");
  el.innerHTML = "";
  S.data.banks.forEach((b) => {
    const off = S.hidden.has(b);
    const it = document.createElement("span");
    it.className = "it bank" + (off ? " off" : "");
    it.style.color = off ? S.data.colors[b] : "";   // 關掉時用空心圈,靠 currentColor 上色
    it.title = off ? `顯示 ${b}` : `隱藏 ${b}`;
    it.innerHTML = `<span class="sw" style="background:${S.data.colors[b]}"></span><span>${b}</span>`;
    it.onclick = () => {
      S.hidden.has(b) ? S.hidden.delete(b) : S.hidden.add(b);
      render();
    };
    el.appendChild(it);
  });
  if (S.hidden.size) {
    const btn = document.createElement("button");
    btn.className = "allbtn";
    btn.textContent = `全部顯示（已隱藏 ${S.hidden.size} 家）`;
    btn.onclick = () => { S.hidden.clear(); render(); };
    el.appendChild(btn);
  } else {
    const h = document.createElement("span");
    h.className = "hintlet"; h.textContent = "點銀行可隱藏";
    el.appendChild(h);
  }
  const extra = document.createElement("span");
  extra.style.display = "contents";
  extra.innerHTML = (S.lens === "變化"
    ? `<span class="it"><span class="sw hollow"></span>全部位（起點）</span><span class="it"><span class="sw" style="background:var(--fg)"></span>帳上看得到（箭頭端）</span>`
    : "") + (axes.length === 3
    ? `<span class="it"><span class="sw" style="background:#5f6672;opacity:.2;border-radius:2px"></span>地板與投影線（判讀高度用）</span>`
    : "");
  el.appendChild(extra);
}

function renderFlags(year) {
  const el = $("#flags");
  const notes = Object.entries(S.data.flags)
    .filter(([k]) => k.startsWith(year + "|"))
    .map(([k, arr]) => `${k.split("|")[1]}：${arr.join("；")}`);
  el.innerHTML = notes.length ? "口徑註記　" + notes.join("　｜　") : "";
}

// ── SVG 共用 ─────────────────────────────────────────────────────────
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

// 某些軸「數字越小＝風險越高」（利率敏感度：−4 比 −2 更敏感）。
// 這種軸把方向翻過來畫，讓「上/右＝更多」對全部軸都成立 —— 翻的是畫布位置，
// 不動資料，刻度數字仍照實印。invert 由 sim/axes.py 的 variant 宣告。
function axRange(axis, values) {
  const r = scaleFor(values);
  r.flip = !!(axis && axis.invert);
  return r;
}

// 值 → 0..1 的位置（0＝軸的起點端，1＝箭頭端），已含 invert。
function frac(r, v) {
  const t = (v - r.lo) / (r.hi - r.lo);
  return r.flip ? 1 - t : t;
}

function scaleFor(values) {
  const vs = values.filter((v) => v !== null && v !== undefined);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.15;
  return { lo: lo - pad, hi: hi + pad };
}

// 「漂亮」的刻度值:step 取 1/2/5 × 10^k。不寫死格數上限以外的常數。
function niceTicks(lo, hi, target = 5) {
  const raw = (hi - lo) / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);   // 消掉 -0 與浮點殘渣
  }
  return { ticks: out, step };
}

function tickText(v, step) {
  const dec = Math.max(0, -Math.floor(Math.log10(step)));
  return v.toFixed(Math.min(dec, 2));
}

function median(vs) {
  const s = vs.filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  if (!s.length) return null;
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// 參考線放哪裡是有意義的,不能隨便放在範圍中點(原本就是這個 bug)。
// 規則:**0 落在畫得到的範圍內就用 0**(浮虧率的 0 = 沒有浮虧,是天然基準);
// 否則用五家中位數。純資料驅動,不對某根軸寫死。
function refLine(lo, hi, values) {
  if (lo < 0 && hi > 0) return { at: 0, label: "0" };
  const m = median(values);
  return m === null ? { at: (lo + hi) / 2, label: "" } : { at: m, label: "中位數" };
}

function polyPoints(pts) { return pts.map((p) => p.join(",")).join(" "); }

// 2 軸圖共用的框:刻度 + 數字 + 參考線 + 帶單位的軸標籤。
// 原本這三張圖一個數字都沒有 —— 只看得到軸名,讀不出任何值。
function drawFrame2D(svg, cfg) {
  const { W, H, pad, xs, ys, xr, yr, xvals, yvals, ax, ay, xsuffix, ysuffix } = cfg;
  const xt = niceTicks(xr.lo, xr.hi), yt = niceTicks(yr.lo, yr.hi);
  svg.appendChild(svgEl("line", { x1: pad, x2: W - pad, y1: H - pad, y2: H - pad, class: "axisline" }));
  svg.appendChild(svgEl("line", { x1: pad, x2: pad, y1: pad, y2: H - pad, class: "axisline" }));
  xt.ticks.forEach((v) => {
    const x = xs(v);
    svg.appendChild(svgEl("line", { x1: x, x2: x, y1: H - pad, y2: H - pad + 5, class: "tickmark" }));
    const t = svgEl("text", { x, y: H - pad + 17, class: "tick", "text-anchor": "middle" });
    t.textContent = tickText(v, xt.step); svg.appendChild(t);
  });
  yt.ticks.forEach((v) => {
    const y = ys(v);
    svg.appendChild(svgEl("line", { x1: pad - 5, x2: pad, y1: y, y2: y, class: "tickmark" }));
    const t = svgEl("text", { x: pad - 9, y: y + 3.5, class: "tick", "text-anchor": "end" });
    t.textContent = tickText(v, yt.step); svg.appendChild(t);
  });
  const rx = refLine(xr.lo, xr.hi, xvals), ry = refLine(yr.lo, yr.hi, yvals);
  svg.appendChild(svgEl("line", { x1: xs(rx.at), x2: xs(rx.at), y1: pad, y2: H - pad, class: "refline" }));
  svg.appendChild(svgEl("line", { x1: pad, x2: W - pad, y1: ys(ry.at), y2: ys(ry.at), class: "refline" }));
  if (rx.label) {
    const t = svgEl("text", { x: xs(rx.at) + 4, y: pad + 10, class: "reflbl" });
    t.textContent = rx.label; svg.appendChild(t);
  }
  if (ry.label) {
    const t = svgEl("text", { x: W - pad - 4, y: ys(ry.at) - 4, class: "reflbl", "text-anchor": "end" });
    t.textContent = ry.label; svg.appendChild(t);
  }
  const xl = svgEl("text", { x: W / 2, y: H - 10, class: "axlbl", "text-anchor": "middle" });
  xl.textContent = `${ax.label}（${ax.unit}${xsuffix || ""}） →`;
  svg.appendChild(xl);
  const yl = svgEl("text", { x: 4, y: pad - 14, class: "axlbl" });
  yl.textContent = `↑ ${ay.label}（${ay.unit}${ysuffix || ""}）`;
  svg.appendChild(yl);
}

// 1 軸,非變化,單期:排序點圖
function dotPlot(axis, year) {
  const W = 900, H = 70 + Math.max(1, visibleBanks().length) * 34;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const vals = S.data.banks.map((b) => valAt(axis, S.lens, year, b));
  const r = axRange(axis, vals);
  const x0 = 90, x1 = W - 40;
  const xs = (v) => x0 + frac(r, v) * (x1 - x0);
  const rank = (v) => (v === null || v === undefined ? -Infinity : frac(r, v));
  const rows = S.data.banks
    .map((b, i) => ({ b, v: vals[i] }))
    .filter((q) => !S.hidden.has(q.b))
    .sort((a, c) => rank(c.v) - rank(a.v));
  rows.forEach((row, i) => {
    const y = 40 + i * 34;
    svg.appendChild(svgEl("line", { x1: x0, x2: x1, y1: y, y2: y, class: "gridline" }));
    const t = svgEl("text", { x: 10, y: y + 4, class: "bankname" });
    t.textContent = row.b; svg.appendChild(t);
    if (row.v === null) return;
    const cx = xs(row.v);
    svg.appendChild(svgEl("circle", { cx, cy: y, r: 7, fill: S.data.colors[row.b], class: "dot" }));
    const vt = svgEl("text", { x: cx, y: y - 12, class: "tick", "text-anchor": "middle" });
    vt.textContent = fmt(row.v, axis.unit);
    svg.appendChild(vt);
  });
  const axl = svgEl("text", { x: x0, y: H - 6, class: "axlbl" });
  axl.textContent = `${axis.label}（${axis.unit}，${lensName(S.lens)}）`;
  svg.appendChild(axl);
  return svg;
}

// 1 軸,非變化,軌跡:5 期連成一條線,最新一期加粗(§11.2「時間」)
function dotPlotTrajectory(axis) {
  const years = S.data.years;
  const W = 900, H = 70 + Math.max(1, visibleBanks().length) * 34;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const series = S.data.banks.map((b) => years.map((y) => valAt(axis, S.lens, y, b)));
  const r = axRange(axis, series.flat());
  const x0 = 90, x1 = W - 40;
  const xs = (v) => x0 + frac(r, v) * (x1 - x0);
  const rank = (v) => (v === null || v === undefined ? -Infinity : frac(r, v));
  const rows = S.data.banks.map((b, i) => {
    const s = series[i];
    const last = [...s].reverse().find((v) => v !== null) ?? null;
    return { b, s, last };
  }).filter((r) => !S.hidden.has(r.b))
    .sort((a, c) => rank(c.last) - rank(a.last));
  rows.forEach((row, i) => {
    const y = 40 + i * 34;
    svg.appendChild(svgEl("line", { x1: x0, x2: x1, y1: y, y2: y, class: "gridline" }));
    const t = svgEl("text", { x: 10, y: y + 4, class: "bankname" });
    t.textContent = row.b; svg.appendChild(t);
    const pts = row.s.map((v) => (v === null ? null : [xs(v), y]));
    const valid = pts.filter(Boolean);
    if (valid.length > 1) {
      const d = valid.map((p, j) => (j === 0 ? "M" : "L") + p[0] + "," + p[1]).join(" ");
      svg.appendChild(svgEl("path", { d, stroke: S.data.colors[row.b], class: "traj-line" }));
    }
    pts.forEach((p, j) => {
      if (!p) return;
      const isLast = j === pts.length - 1;
      svg.appendChild(svgEl("circle", { cx: p[0], cy: p[1], r: isLast ? 7 : 3,
        fill: S.data.colors[row.b], class: isLast ? "dot" : "dot traj-dot" }));
      if (isLast) {
        const vt = svgEl("text", { x: p[0], y: y - 12, class: "tick", "text-anchor": "middle" });
        vt.textContent = fmt(row.last, axis.unit);
        svg.appendChild(vt);
      }
    });
  });
  const axl = svgEl("text", { x: x0, y: H - 6, class: "axlbl" });
  axl.textContent = `${axis.label}（${axis.unit}，${lensName(S.lens)}，${years[0]}→${years[years.length - 1]} 軌跡）`;
  svg.appendChild(axl);
  return svg;
}

// 2 軸,非變化,單期:象限散佈
function quadrant(ax, ay, year) {
  const W = 760, H = 580, pad = 66;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const xv = S.data.banks.map((b) => valAt(ax, S.lens, year, b));
  const yv = S.data.banks.map((b) => valAt(ay, S.lens, year, b));
  const xr = axRange(ax, xv), yr = axRange(ay, yv);
  const xs = (v) => pad + frac(xr, v) * (W - 2 * pad);
  const ys = (v) => H - pad - frac(yr, v) * (H - 2 * pad);
  drawFrame2D(svg, { W, H, pad, xs, ys, xr, yr, xvals: xv, yvals: yv, ax, ay,
                     xsuffix: `，${lensName(S.lens)}` });
  S.data.banks.forEach((b, i) => {
    if (S.hidden.has(b) || xv[i] === null || yv[i] === null) return;
    const cx = xs(xv[i]), cy = ys(yv[i]);
    svg.appendChild(svgEl("circle", { cx, cy, r: 8, fill: S.data.colors[b], class: "dot" }));
    const t = svgEl("text", { x: cx + 12, y: cy + 4, class: "bankname" });
    t.textContent = b; svg.appendChild(t);
  });
  return svg;
}

// 2 軸,非變化,軌跡:每家銀行 5 期連成一條線,最新一期加粗標籤
function quadrantTrajectory(ax, ay) {
  const years = S.data.years;
  const W = 760, H = 580, pad = 66;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const xSeries = S.data.banks.map((b) => years.map((y) => valAt(ax, S.lens, y, b)));
  const ySeries = S.data.banks.map((b) => years.map((y) => valAt(ay, S.lens, y, b)));
  const xr = axRange(ax, xSeries.flat()), yr = axRange(ay, ySeries.flat());
  const xs = (v) => pad + frac(xr, v) * (W - 2 * pad);
  const ys = (v) => H - pad - frac(yr, v) * (H - 2 * pad);
  drawFrame2D(svg, { W, H, pad, xs, ys, xr, yr,
                     xvals: xSeries.map((s) => s[s.length - 1]),
                     yvals: ySeries.map((s) => s[s.length - 1]), ax, ay,
                     xsuffix: `，${lensName(S.lens)}，${years[0]}→${years[years.length - 1]}` });
  S.data.banks.forEach((b, i) => {
    if (S.hidden.has(b)) return;
    const pts = years.map((_, j) =>
      (xSeries[i][j] === null || ySeries[i][j] === null) ? null : [xs(xSeries[i][j]), ys(ySeries[i][j])]);
    const valid = pts.filter(Boolean);
    if (valid.length > 1) {
      const d = valid.map((p, j) => (j === 0 ? "M" : "L") + p[0] + "," + p[1]).join(" ");
      svg.appendChild(svgEl("path", { d, stroke: S.data.colors[b], class: "traj-line" }));
    }
    pts.forEach((p, j) => {
      if (!p) return;
      const isLast = j === pts.length - 1;
      svg.appendChild(svgEl("circle", { cx: p[0], cy: p[1], r: isLast ? 8 : 3,
        fill: S.data.colors[b], class: isLast ? "dot" : "dot traj-dot" }));
      if (isLast) {
        const t = svgEl("text", { x: p[0] + 12, y: p[1] + 4, class: "bankname" });
        t.textContent = b; svg.appendChild(t);
      }
    });
  });
  return svg;
}

// 1 軸,變化:啞鈴圖
function dumbbell(axis, year) {
  const W = 900, H = 70 + Math.max(1, visibleBanks().length) * 34;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const eps = S.data.banks.map((b) => endpoints(axis, year, b));
  const r = axRange(axis, eps.flatMap((e) => [e.from, e.to]));
  const x0 = 90, x1 = W - 40;
  const xs = (v) => x0 + frac(r, v) * (x1 - x0);
  const rows = S.data.banks
    .map((b, i) => ({ b, ...eps[i], gap: Math.abs((eps[i].to ?? 0) - (eps[i].from ?? 0)) }))
    .filter((r) => !S.hidden.has(r.b))
    .sort((a, c) => c.gap - a.gap);
  rows.forEach((row, i) => {
    const y = 40 + i * 34;
    svg.appendChild(svgEl("line", { x1: x0, x2: x1, y1: y, y2: y, class: "gridline" }));
    const t = svgEl("text", { x: 10, y: y + 4, class: "bankname" });
    t.textContent = row.b; svg.appendChild(t);
    if (row.from === null || row.to === null) return;
    const cf = xs(row.from), ct = xs(row.to);
    svg.appendChild(svgEl("line", { x1: cf, x2: ct, y1: y, y2: y,
      stroke: S.data.colors[row.b], class: "dumbbell-line" }));
    svg.appendChild(svgEl("circle", { cx: cf, cy: y, r: 6, class: "dot hollow",
      stroke: S.data.colors[row.b] }));
    svg.appendChild(svgEl("circle", { cx: ct, cy: y, r: 6, fill: S.data.colors[row.b], class: "dot" }));
    const vt = svgEl("text", { x: (cf + ct) / 2, y: y - 12, class: "tick", "text-anchor": "middle" });
    vt.textContent = `${fmt(row.from, axis.unit)} → ${fmt(row.to, axis.unit)}`;
    svg.appendChild(vt);
  });
  const axl = svgEl("text", { x: x0, y: H - 6, class: "axlbl" });
  axl.textContent = `${axis.label}（${axis.unit}，全部位 → 帳上看得到，棒長＝差多少）`;
  svg.appendChild(axl);
  return svg;
}

// 2 軸,變化:箭頭(全部位→帳上看得到)。若某軸不 switchable,該方向不動(混選規則)。
function arrowScatter(ax, ay, year) {
  const W = 760, H = 580, pad = 66;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  svg.appendChild(svgEl("defs", {})).innerHTML =
    `<marker id="arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
       <path d="M0,0 L6,3 L0,6 Z" fill="var(--fg)"/>
     </marker>`;
  const eps = S.data.banks.map((b) => ({ x: endpoints(ax, year, b), y: endpoints(ay, year, b) }));
  const xr = axRange(ax, eps.flatMap((e) => [e.x.from, e.x.to]));
  const yr = axRange(ay, eps.flatMap((e) => [e.y.from, e.y.to]));
  const xs = (v) => pad + frac(xr, v) * (W - 2 * pad);
  const ys = (v) => H - pad - frac(yr, v) * (H - 2 * pad);
  // 「變化」不畫凸包 —— 每家有兩個位置,包起來會分不清是誰的範圍。
  drawFrame2D(svg, { W, H, pad, xs, ys, xr, yr,
                     xvals: eps.map((e) => e.x.to), yvals: eps.map((e) => e.y.to), ax, ay,
                     xsuffix: ax.switchable ? "，全部位→帳上看得到" : "，不隨口徑動",
                     ysuffix: ay.switchable ? "，全部位→帳上看得到" : "，不隨口徑動" });
  S.data.banks.forEach((b, i) => {
    const { x, y } = eps[i];
    if (S.hidden.has(b) || [x.from, x.to, y.from, y.to].some((v) => v === null)) return;
    const fx = xs(x.from), fy = ys(y.from), tx = xs(x.to), ty = ys(y.to);
    svg.appendChild(svgEl("line", { x1: fx, y1: fy, x2: tx, y2: ty,
      stroke: S.data.colors[b], class: "arrow-line" }));
    svg.appendChild(svgEl("circle", { cx: fx, cy: fy, r: 6, class: "dot hollow", stroke: S.data.colors[b] }));
    svg.appendChild(svgEl("circle", { cx: tx, cy: ty, r: 6, fill: S.data.colors[b], class: "dot" }));
    const t = svgEl("text", { x: tx + 10, y: ty + 4, class: "bankname" });
    t.textContent = b; svg.appendChild(t);
  });
  return svg;
}

// ── 3 軸:可拖曳旋轉的 3D 散佈(§11.2「3 根→可旋轉3D」) ────────────────
// 手刻正交投影 + 簡單深度提示(近的點大且不透明),不上 WebGL/三方庫。
// 「變化」時每家銀行畫成 3D 箭頭:endpoints() 對非 switchable 軸回相同座標,
// 混選規則(§11.2a)在 3D 下自然成立,不必另外寫分支。
function threeD(axes, year, traj) {
  const W = 760, H = 560, cx = W / 2, cy = H / 2 + 10, scale = 170;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "svg3d" });
  const years = S.data.years;

  // 軌跡開著時,範圍要跨全部 5 年(不然點跑出畫面);變化/單期就只看當年。
  const ranges = axes.map((a) => {
    const vals = S.data.banks.flatMap((b) => {
      if (S.lens === "變化") { const e = endpoints(a, year, b); return [e.from, e.to]; }
      if (traj) return years.map((y) => valAt(a, S.lens, y, b));
      return [valAt(a, S.lens, year, b)];
    });
    return axRange(a, vals);
  });
  const norm = (v, i) => (v === null || v === undefined) ? null :
    frac(ranges[i], v) * 2 - 1;

  const rx = S.rot.x * Math.PI / 180, ry = S.rot.y * Math.PI / 180;
  function project([x, y, z]) {
    const x1 = x * Math.cos(ry) + z * Math.sin(ry);
    const z1 = -x * Math.sin(ry) + z * Math.cos(ry);
    const y2 = y * Math.cos(rx) - z1 * Math.sin(rx);
    const z2 = y * Math.sin(rx) + z1 * Math.cos(rx);
    return { sx: cx + x1 * scale, sy: cy - y2 * scale, depth: z2 };
  }

  // 地板(axes[1] 的最小值那一面)。3D 散佈最難的是判斷「這點是高還是遠」——
  // 地板 + 垂直投影線是唯一便宜又有效的線索,所以這不是裝飾。先畫,墊在最底下。
  const floor = [[-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1]]
    .map((p) => { const q = project(p); return [q.sx, q.sy]; });
  svg.appendChild(svgEl("polygon", { points: polyPoints(floor), class: "floor" }));

  // 箭頭 marker —— 3D 旋轉後三條線長得一樣,沒有箭頭就分不出哪一端是「多」。
  const defs = svgEl("defs", {});
  defs.innerHTML =
    `<marker id="axarrow" markerWidth="9" markerHeight="9" refX="8" refY="3.2" orient="auto">
       <path d="M0,0 L8,3.2 L0,6.4 Z" fill="#8a919e"/>
     </marker>`;
  svg.appendChild(defs);

  // 三根軸:線(箭頭指向大值端) + 兩端實際數值 + 大值端的軸名與「往這邊代表什麼」。
  // 旋轉中的軸掛不了整排刻度,所以資訊集中在兩端。
  [[[-1.3, 0, 0], [1.3, 0, 0], [1.62, 0, 0], axes[0], 0],
   [[0, -1.3, 0], [0, 1.3, 0], [0, 1.62, 0], axes[1], 1],
   [[0, 0, -1.3], [0, 0, 1.3], [0, 0, 1.62], axes[2], 2]].forEach(([p1, p2, p3, ax, i]) => {
    const a = project(p1), b = project(p2), out = project(p3);
    svg.appendChild(svgEl("line", { x1: a.sx, y1: a.sy, x2: b.sx, y2: b.sy,
      class: "axis3d", "marker-end": "url(#axarrow)" }));
    // 標籤沿投影方向推到**最小半徑**之外。
    // 不能直接用 out 的位置:軸線指向觀察者時投影會被壓得很短,標籤就掉進資料點雲裡。
    // 方向仍然是對的,只是長度不能信 —— 所以取方向、自己給長度。
    const dx = out.sx - cx, dy = out.sy - cy;
    const len = Math.hypot(dx, dy), MIN_R = 215;
    const k = len < 1 ? 0 : Math.max(1, MIN_R / len);   // 軸完全對著鏡頭時 len≈0,退回原點附近
    const lx = cx + dx * k, ly = cy + dy * k;
    const anchor = lx < cx - 12 ? "end" : lx > cx + 12 ? "start" : "middle";
    const out2 = { sx: lx, sy: ly };
    const t = svgEl("text", { x: out2.sx, y: out2.sy, class: "axlbl", "text-anchor": anchor });
    t.textContent = `${ax.label}（${ax.unit}）`;
    svg.appendChild(t);
    if (ax.more) {
      // ★ 這一行是重點:光有箭頭只知道「哪邊多」,不知道「多代表什麼」。
      // 利率軸的原始數字是負的(−8.53 比 −2.16 更敏感),已用 invert 把方向翻正,
      // 箭頭端一律是「更多風險」;這行字還是要寫,不然對不上刻度上的負號。
      const m = svgEl("text", { x: out2.sx, y: out2.sy + 13, class: "moretag", "text-anchor": anchor });
      m.textContent = `▸ ${ax.more}`;
      svg.appendChild(m);
    }
    const step = niceTicks(ranges[i].lo, ranges[i].hi).step;
    const ends = ranges[i].flip ? [[a, ranges[i].hi], [b, ranges[i].lo]]
                                : [[a, ranges[i].lo], [b, ranges[i].hi]];
    ends.forEach(([pt, v]) => {
      const n = svgEl("text", { x: pt.sx, y: pt.sy + 13, class: "tick", "text-anchor": "middle" });
      n.textContent = tickText(v, step); svg.appendChild(n);
    });
  });

  // 軌跡:5 年連成一條線,只畫在地板上不畫垂直投影(5家×5點的投影線會糊成一片)。
  // 最新一期留給下面的 items[] 主流程處理(深度排序、投影線、放大)。
  if (traj && S.lens !== "變化") {
    S.data.banks.forEach((b) => {
      if (S.hidden.has(b)) return;
      const ptSeries = years.map((y) => {
        const raw = axes.map((a, i) => norm(valAt(a, S.lens, y, b), i));
        return raw.some((v) => v === null) ? null : project(raw);
      });
      const valid = ptSeries.filter(Boolean);
      if (valid.length > 1) {
        const d = valid.map((p, j) => (j === 0 ? "M" : "L") + p.sx + "," + p.sy).join(" ");
        svg.appendChild(svgEl("path", { d, stroke: S.data.colors[b], class: "traj-line" }));
      }
      ptSeries.forEach((p, j) => {
        if (!p || j === ptSeries.length - 1) return;
        svg.appendChild(svgEl("circle", { cx: p.sx, cy: p.sy, r: 3,
          fill: S.data.colors[b], class: "dot traj-dot" }));
      });
    });
  }

  const items = [];
  const lastYear = traj ? years[years.length - 1] : year;
  S.data.banks.forEach((b) => {
    if (S.hidden.has(b)) return;
    if (S.lens === "變化") {
      const eps = axes.map((a) => endpoints(a, year, b));
      if (eps.some((e) => e.from === null || e.to === null)) return;
      const rawFrom = axes.map((a, i) => norm(eps[i].from, i));
      const rawTo = axes.map((a, i) => norm(eps[i].to, i));
      const pFrom = project(rawFrom), pTo = project(rawTo);
      // 兩個端點都落地板 —— 使用者要的「下面的垂直虛線」,變化模式原本沒有
      const footFrom = project([rawFrom[0], -1, rawFrom[2]]);
      const footTo = project([rawTo[0], -1, rawTo[2]]);
      items.push({ type: "arrow", b, pFrom, pTo, footFrom, footTo,
                  depth: (pFrom.depth + pTo.depth) / 2 });
    } else {
      const raw = axes.map((a, i) => norm(valAt(a, S.lens, lastYear, b), i));
      if (raw.some((v) => v === null)) return;
      const p = project(raw);
      // 落在地板上的投影點:同一個 x/z,y 壓到 -1
      const foot = project([raw[0], -1, raw[2]]);
      items.push({ type: "dot", b, p, foot, depth: p.depth });
    }
  });
  if (items.length) {
    const depths = items.map((it) => it.depth);
    const dlo = Math.min(...depths), dhi = Math.max(...depths);
    items.forEach((it) => {
      const t = dhi > dlo ? (it.depth - dlo) / (dhi - dlo) : 0.5;
      it.op = (0.5 + t * 0.5).toFixed(2);
      it.r = 5 + t * 4;
    });
  }
  items.sort((a, c) => a.depth - c.depth);   // 遠的先畫(畫家演算法),近的疊在上面
  items.forEach((it) => {
    if (it.type === "dot") {
      svg.appendChild(svgEl("line", { x1: it.p.sx, y1: it.p.sy,
        x2: it.foot.sx, y2: it.foot.sy, class: "dropline" }));
      svg.appendChild(svgEl("circle", { cx: it.foot.sx, cy: it.foot.sy, r: 2.5, class: "dropdot" }));
      svg.appendChild(svgEl("circle", { cx: it.p.sx, cy: it.p.sy, r: it.r,
        fill: S.data.colors[it.b], class: "dot", opacity: it.op }));
      const t = svgEl("text", { x: it.p.sx + it.r + 4, y: it.p.sy + 4, class: "bankname" });
      t.textContent = it.b; svg.appendChild(t);
    } else {
      // 兩端各一條垂直虛線落地板 —— 跟單期模式的 dot 同一套判讀邏輯,只是這裡有兩個點。
      svg.appendChild(svgEl("line", { x1: it.pFrom.sx, y1: it.pFrom.sy,
        x2: it.footFrom.sx, y2: it.footFrom.sy, class: "dropline" }));
      svg.appendChild(svgEl("circle", { cx: it.footFrom.sx, cy: it.footFrom.sy, r: 2.5, class: "dropdot" }));
      svg.appendChild(svgEl("line", { x1: it.pTo.sx, y1: it.pTo.sy,
        x2: it.footTo.sx, y2: it.footTo.sy, class: "dropline" }));
      svg.appendChild(svgEl("circle", { cx: it.footTo.sx, cy: it.footTo.sy, r: 2.5, class: "dropdot" }));
      svg.appendChild(svgEl("line", { x1: it.pFrom.sx, y1: it.pFrom.sy, x2: it.pTo.sx, y2: it.pTo.sy,
        stroke: S.data.colors[it.b], class: "arrow-line", opacity: it.op }));
      svg.appendChild(svgEl("circle", { cx: it.pFrom.sx, cy: it.pFrom.sy, r: it.r - 1,
        class: "dot hollow", stroke: S.data.colors[it.b], opacity: it.op }));
      svg.appendChild(svgEl("circle", { cx: it.pTo.sx, cy: it.pTo.sy, r: it.r,
        fill: S.data.colors[it.b], class: "dot", opacity: it.op }));
      const t = svgEl("text", { x: it.pTo.sx + it.r + 4, y: it.pTo.sy + 4, class: "bankname" });
      t.textContent = it.b; svg.appendChild(t);
    }
  });
  return svg;
}

// 拖曳旋轉 —— 監聽器只在 boot() 掛一次,svg 元素本身每次 render 都會被換掉,
// 用 event delegation(closest(".svg3d"))認,不必每次渲染重新綁定。
function setupDrag() {
  document.addEventListener("mousedown", (e) => {
    const el = e.target.closest(".svg3d");
    if (!el) return;
    dragging = true; dragLastX = e.clientX; dragLastY = e.clientY;
    el.classList.add("dragging");
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - dragLastX, dy = e.clientY - dragLastY;
    dragLastX = e.clientX; dragLastY = e.clientY;
    S.rot.y += dx * 0.5;
    S.rot.x = Math.max(-85, Math.min(85, S.rot.x - dy * 0.5));
    render();
  });
  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    const el = document.querySelector(".svg3d");
    if (el) el.classList.remove("dragging");
  });
}

boot();
