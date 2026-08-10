// 全站導覽列 —— **唯一一份**。四個頁面(工作台/分析/模擬器/複核台)共用。
//
// 2026-08-10 之前:workbench.html、sim.html、v4.html 各自寫一份 <nav>,
// 分析頁(make_web.py 產出)又用完全不同的 <header>+#pagetabs,加起來四套。
// 而且 workbench 是用 iframe 把分析頁掛進來 → 使用者會同時看到兩條導覽列疊著,
// 那正是「看起來像四個網站」的來源。
//
// 用法:頁面放一個 <div id="appnav"></div>,然後 <script src="/appnav.js"></script>。
// 右側狀態區(更新時間、資料來源、重建鈕)由各頁自己塞進 .slot,這支不管內容。
//
// ⚠️ **在 iframe 裡自動不畫。** 分析頁被工作台用 iframe 嵌著,外層已經有一條了,
//    再畫一條就是原本那個兩層疊的問題。
(function () {
  if (window.self !== window.top) return;

  //: 一級項目 = 「去哪一頁」。順序照使用頻率由讀者往操作者排:
  //  分析(給人看的成品)→ 模擬器(探索)→ 資料(把文件變成數字)。
  //  **頁內的分頁不放這裡** —— 那是第二層,見 tokens.css 的 .appnav 註解。
  var ITEMS = [
    { href: "/workbench.html#/analysis", label: "分析",  match: /^\/workbench\.html$/, hash: "#/analysis" },
    { href: "/sim.html",                 label: "模擬器", match: /^\/sim\.html$/ },
    { href: "/workbench.html#/matrix",   label: "資料",  match: /^\/workbench\.html$/, hash: "#/matrix" },
    // v4 複核**不在這裡**(2026-08-10)。它跟「資料」做的是同一件事——把文件變成
    // 可發布的數字,只是走另一條管線——並排在最上層會被當成兩個獨立的功能領域。
    // 入口收在資料頁的 `#/v4`。/v4.html 仍可直接開,那時這條導覽照常顯示。
  ];

  var host = document.getElementById("appnav");
  if (!host) return;

  var path = location.pathname;
  var nav = document.createElement("nav");
  nav.className = "appnav";

  var brand = document.createElement("a");
  brand.className = "brand";
  brand.href = "/workbench.html#/analysis";
  brand.textContent = "銀行債券投資";
  nav.appendChild(brand);

  var links = document.createElement("div");
  links.className = "links";
  ITEMS.forEach(function (it) {
    var a = document.createElement("a");
    a.href = it.href;
    a.textContent = it.label;
    a.dataset.hash = it.hash || "";
    a.dataset.match = it.match.source;
    links.appendChild(a);
  });
  nav.appendChild(links);

  var slot = document.createElement("div");
  slot.className = "slot";
  slot.id = "navslot";
  nav.appendChild(slot);

  host.replaceWith(nav);

  // 同一個 pathname 底下有兩個項目(分析 / 資料 都在 workbench.html),
  // 所以要連 hash 一起比;hash 會變,所以每次變都重算。
  function mark() {
    [].forEach.call(links.children, function (a) {
      var re = new RegExp(a.dataset.match);
      // 「資料」底下還有子路由(#/buckets #/queue #/v4 #/doc/…),它們都算在資料裡 ——
      // 點進分桶檢視卻看到整條導覽都沒亮,會讓人以為自己離開了這個 app。
      // 規則:分析只認 #/analysis(與空 hash,那是預設頁);同頁的其餘 hash 都歸資料。
      var h = location.hash;
      var on = re.test(path) && (!a.dataset.hash
        ? true
        : a.dataset.hash === "#/analysis"
          ? (h === "#/analysis" || !h)
          : (h !== "#/analysis" && !!h) || h === a.dataset.hash);
      a.classList.toggle("on", on);
    });
  }
  mark();
  window.addEventListener("hashchange", mark);
})();
