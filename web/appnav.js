// 全站導覽列 —— **唯一一份**。四個頁面(工作台/分析/多軸分析/複核台)共用。
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
  //  報表(給人看的成品)→ 多軸分析(探索)→ 資料核對(把文件變成數字)。
  //  **頁內的分頁不放這裡** —— 那是第二層,見 tokens.css 的 .appnav 註解。
  //
  // 2026-08-13(R2)一度把個體/合併拆成兩個一級項目,同時保留分析頁自己的
  // #pagetabs —— 結果同一個選擇在畫面上出現兩遍(上面一排、內容區再一排)。
  // 現在收回一個一級項目「報表」,個體/合併的切換交還給頁內的 #pagetabs。
  // `hash` 收兩個值:從 #/consol 進來(舊網址、iframe 深連結)也要讓這項亮著,
  // 否則會落到下面 fallback 的「資料核對」去。
  var ITEMS = [
    { href: "/workbench.html#/analysis", label: "報表", match: /^\/workbench\.html$/, hash: ["#/analysis", "#/consol"] },
    { href: "/sim.html",                 label: "多軸分析", match: /^\/sim\.html$/ },
    // 資料核對:吃掉 workbench.html 底下所有沒被上面兩項認領的 hash
    // (空 hash / #/matrix / #/buckets / #/doc/… / #/v4 全算),見下面 mark() 的 fallback 規則。
    { href: "/workbench.html#/matrix",   label: "資料核對", match: /^\/workbench\.html$/, fallback: true },
    // v4 複核**不在這裡**(2026-08-10)。它跟「資料核對」做的是同一件事——把文件變成
    // 可發布的數字,只是走另一條管線——並排在最上層會被當成兩個獨立的功能領域。
    // 入口收在資料核對頁的 `#/v4`。/v4.html 仍可直接開,那時這條導覽照常顯示。
    //
    // 資本/pillar3 **不在這裡**(2026-08-13 裁示)。它一度破例放頂層是為了
    // 「至少看得到」,但那頁日常用不到,擺在一級導覽是拿最貴的位置放最少人看的東西。
    // /capital.html 仍可直接開,那時這條導覽照常顯示(沒有項目會亮)。
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
    // 一個項目可以認多個 hash,存成逗號分隔(dataset 只吃字串)。
    a.dataset.hash = [].concat(it.hash || []).join(",");
    if (it.fallback) a.dataset.fallback = "1";
    a.dataset.match = it.match.source;
    links.appendChild(a);
  });
  nav.appendChild(links);

  var slot = document.createElement("div");
  slot.className = "slot";
  slot.id = "navslot";
  nav.appendChild(slot);

  host.replaceWith(nav);

  // 同一個 pathname 底下有兩個項目(報表/資料核對都在 workbench.html),
  // 所以要連 hash 一起比;hash 會變,所以每次變都重算。
  //
  // 規則(2026-08-13 重寫,見 docs/plan_ui_一層導覽.md R2):
  //   有宣告 hash 的項目 —— 只認自己宣告的那幾個 hash,完全比對。
  //   宣告 fallback 的項目(資料核對)—— 吃掉同 pathname 下所有「沒被其他
  //   項目認領」的 hash,包含空 hash(那是 workbench.js route() 的預設頁)、
  //   #/buckets、#/doc/…、#/v4 等子路由。**這條不能漏**——點進分桶檢視卻
  //   看到整條導覽都沒亮,會讓人以為自己離開了這個 app(2026-07 踩過)。
  //   沒宣告 hash 也沒宣告 fallback 的項目(多軸分析)—— pathname 對上就算亮。
  var CLAIMED_HASHES = ITEMS.reduce(function (acc, it) {
    return it.hash ? acc.concat(it.hash) : acc;
  }, []);
  function mark() {
    var h = location.hash;
    [].forEach.call(links.children, function (a) {
      var re = new RegExp(a.dataset.match);
      if (!re.test(path)) { a.classList.toggle("on", false); return; }
      var on;
      if (a.dataset.fallback) on = CLAIMED_HASHES.indexOf(h) === -1;
      else if (a.dataset.hash) on = a.dataset.hash.split(",").indexOf(h) !== -1;
      else on = true;
      a.classList.toggle("on", on);
    });
  }
  mark();
  window.addEventListener("hashchange", mark);

  // ── R3-1(2026-08-12):示範資料橫幅 ─────────────────────────────────────
  // 別人 clone 下來第一眼看到的是**你的**示範資料(五家台灣銀行的債券投資),
  // 不是空白畫面 —— 沒有這條,會被誤會成「這個工具只做這五家銀行」。
  // 只在四頁的**外層**畫一次(iframe 判斷已經在最上面 return 過);
  // 關掉之後記在 localStorage,不會每次開都跳出來煩人。
  var DISMISS_KEY = "demo-banner-dismissed-v1";
  if (!localStorage.getItem(DISMISS_KEY)) {
    var banner = document.createElement("div");
    banner.className = "demo-banner";
    banner.innerHTML =
      '<span>這是<b>示範資料集</b>(五家台灣銀行的債券投資組合),用來證明這台機器會動 —— ' +
      '不是你的資料。想放自己的資料:把要分析的銀行加進 ' +
      '<code>banks.json</code>,把財報 PDF 拖進「資料」頁上傳即可,不用改程式碼。' +
      '詳見 <a href="https://github.com/henrylin1009/auto-reports#readme" target="_blank" rel="noopener">README</a>。</span>' +
      '<button type="button" aria-label="關閉">✕</button>';
    banner.querySelector("button").addEventListener("click", function () {
      localStorage.setItem(DISMISS_KEY, "1");
      banner.remove();
    });
    nav.insertAdjacentElement("afterend", banner);
  }
})();
