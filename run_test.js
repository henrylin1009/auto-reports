const fs = require("fs");
const workbench = fs.readFileSync("web/workbench.js", "utf8");
const JSDOM = require("jsdom").JSDOM;
const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="app"></div><div id="navstat"></div><button id="rebuildBtn"></button><nav><a href="#/matrix"></a><a href="#/doc"></a></nav></body></html>`);
const window = dom.window;
const document = window.document;
window.Element.prototype.scrollIntoView = () => {};

global.window = window;
global.document = document;
global.confirm = () => true;
global.prompt = () => "reason";
global.alert = () => {};
global.addEventListener = () => {};
global.location = { hash: "#/doc/202404_5843_AI3" };
global.$ = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; };
global.esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
global.num = (n) => n == null ? "—" : Number(n).toLocaleString("en-US");
global.fetch = async (url) => {
  if (url.includes("/api/doc?doc=202404_5843_AI3")) return { json: async () => JSON.parse(fs.readFileSync("out.json", "utf8")), ok: true };
  if (url.includes("/api/pagetext")) return { json: async () => ({ n_pages: 130 }), ok: true };
  if (url.includes("/api/overview")) return { json: async () => ({ basis: {}, stats: {done:0,todo:0,blocked:0,rejected:0} }), ok: true };
  if (url.includes("/api/buckets")) return { json: async () => ([]), ok: true };
  throw new Error("Unknown url: " + url);
};

const patched = workbench.replace("boot();", "boot().then(async () => { try { await viewDoc('202404_5843_AI3', { reload: true }); console.log('viewDoc successful!'); } catch(e) { console.error('viewDoc failed:', e); } });");
try {
  eval(patched);
} catch(e) {
  console.log("Error evaling workbench:", e);
}
