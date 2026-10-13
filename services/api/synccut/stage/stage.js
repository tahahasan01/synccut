/* SyncCut stage: a MacBook screen with a Chrome-style browser, driven by a scene timeline.
 *
 * Everything on screen is a pure function of time: stage.seek(ms) draws the
 * exact state at that moment and returns a signature string, which the renderer
 * uses to reuse identical frames. Preview mode follows postMessage seeks from
 * the editor; render mode is driven by headless Chromium frame by frame.
 *
 * It should read as a plain screen recording: the macOS pointer is always on
 * screen, moves on a slight arc, and clicks without effects; pages swap in the
 * moment they "load" while the tab shows Chrome's spinner. The optional camera
 * push-in (off by default) follows the interactive-product-demo skill.
 */
(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  const SCENE_URL = params.get("scene");
  const ASSETS = (params.get("assets") || "").replace(/\/?$/, "/");
  const MODE = params.get("mode") || "preview";

  const CAM_MS = 800;
  const PAN = 0.85;
  const W = 1920, H = 1080;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, p) => a + (b - a) * p;
  const easeOut = (p) => 1 - Math.pow(1 - p, 5);
  const easeOutCubic = (p) => 1 - Math.pow(1 - p, 3);
  // smooth start, quick middle, soft landing (monotonic, 0 to 1)
  const pointer = (p) => 0.4 * p * p * (3 - 2 * p) + 0.6 * easeOutCubic(p);
  const el = (tag, cls, parent, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html) n.innerHTML = html;
    if (parent) parent.appendChild(n);
    return n;
  };
  const splitUrl = (u) => {
    if (!u) return { host: "", rest: "" };
    try {
      const x = new URL(u);
      const path = x.pathname.replace(/\/$/, "");
      return { host: x.host.replace(/^www\./, ""), rest: path + (x.search || "") };
    } catch {
      return { host: u, rest: "" };
    }
  };
  const lastAt = (list, t, key = "t") => {
    let found = null;
    for (const item of list) {
      if (item[key] <= t) found = item;
      else break;
    }
    return found;
  };

  const ICON = {
    search: '<svg class="lead" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/></svg>',
    tune: '<svg class="lead" viewBox="0 0 24 24"><path d="M4 8h9M17 8h3M4 16h3M11 16h9"/><circle cx="15" cy="8" r="2.2"/><circle cx="9" cy="16" r="2.2"/></svg>',
    globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>',
    star: '<svg class="star" viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9Z"/></svg>',
    reload: '<svg viewBox="0 0 24 24"><path d="M19 12a7 7 0 1 1-2.05-4.95M19 4.5V8h-3.5"/></svg>',
    stop: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  };

  // Generic Dock apps: simple glyphs, no real product logos.
  const tile = (bg, inner) => `<svg viewBox="0 0 64 64"><defs>${bg.defs || ""}</defs><rect x="2" y="2" width="60" height="60" rx="14" fill="${bg.fill}"/>${inner}</svg>`;
  const grad = (id, a, b) => ({ defs: `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient>`, fill: `url(#${id})` });
  const DOCK_APPS = [
    { run: true, svg: tile(grad("g1", "#6ec6ff", "#1e7bdc"), '<path d="M14 22h14l4 5h18v19H14Z" fill="#fff" opacity=".95"/>') },
    { svg: tile(grad("g2", "#5b5d66", "#2e3038"), [0, 1, 2].map((r) => [0, 1, 2].map((c) => `<rect x="${15 + c * 13}" y="${15 + r * 13}" width="9" height="9" rx="2.5" fill="${["#ff6b6b", "#ffd43b", "#69db7c", "#4dabf7", "#da77f2", "#ff922b", "#38d9a9", "#748ffc", "#f783ac"][r * 3 + c]}"/>`).join("")).join("")) },
    { svg: tile({ fill: "#f4f6fa" }, '<circle cx="32" cy="32" r="21" fill="none" stroke="#1d8cf8" stroke-width="4"/><path d="m40 24-5 11-11 5 5-11Z" fill="#ff4d4f"/><path d="m24 40 5-11 6 6Z" fill="#c9d3e3"/>') },
    { svg: tile({ fill: "#1f2937" }, '<path d="M16 20h32v20H16Z" fill="none" stroke="#fff" stroke-width="3" stroke-linejoin="round"/><path d="m22 26 5 4-5 4M30 35h9" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>') },
    { badge: "1", svg: tile(grad("g3", "#a1a6b0", "#5e636d"), '<circle cx="32" cy="32" r="13" fill="none" stroke="#e9ecf1" stroke-width="7" stroke-dasharray="5 4"/><circle cx="32" cy="32" r="8" fill="#3d4149"/><circle cx="32" cy="32" r="4" fill="#d5d9df"/>') },
    { svg: tile(grad("g4", "#59b0ff", "#1769e0"), '<rect x="15" y="20" width="34" height="24" rx="3" fill="#fff"/><path d="m16 22 16 12 16-12" fill="none" stroke="#1769e0" stroke-width="2.5"/>') },
    { svg: tile(grad("g5", "#6ff08a", "#21b04b"), '<path d="M32 16c10 0 18 6.5 18 14.5S42 45 32 45c-2 0-4-.3-5.8-.8L18 48l2.6-6.6C16.5 38.8 14 35 14 30.5 14 22.5 22 16 32 16Z" fill="#fff"/>') },
    { svg: tile({ fill: "#fff" }, '<path d="M2 16a14 14 0 0 1 14-14h32a14 14 0 0 1 14 14v6H2Z" fill="#ff3b30"/><text x="32" y="17" text-anchor="middle" font-size="11" font-weight="700" fill="#fff" font-family="-apple-system,Segoe UI,sans-serif">OCT</text><text x="32" y="50" text-anchor="middle" font-size="26" font-weight="300" fill="#222" font-family="-apple-system,Segoe UI,sans-serif">13</text>') },
    { svg: tile({ fill: "#fffdf3" }, '<path d="M2 16a14 14 0 0 1 14-14h32a14 14 0 0 1 14 14v4H2Z" fill="#ffd60a"/><path d="M14 32h36M14 40h36M14 48h24" stroke="#d9d4c3" stroke-width="2"/>') },
    { svg: tile(grad("g6", "#ff7a93", "#fa2d48"), '<path d="M27 42V22l16-4v20" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/><circle cx="23" cy="42" r="5" fill="#fff"/><circle cx="39" cy="38" r="5" fill="#fff"/>') },
    { svg: tile({ fill: "#fff" }, ["#ff9f0a", "#ffd60a", "#30d158", "#64d2ff", "#5e5ce6", "#ff375f"].map((c, i) => `<ellipse cx="32" cy="20" rx="6" ry="11" fill="${c}" opacity=".85" transform="rotate(${i * 60} 32 32)"/>`).join("")) },
    { run: true, svg: tile(grad("g7", "#3aa0ff", "#0b5cd6"), '<path d="m26 22-10 10 10 10M38 22l10 10-10 10" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>') },
    { run: true, svg: tile(grad("g8", "#8b7cff", "#5a3fe0"), '<path d="M16 20h22a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4H26l-7 6v-6h-3a4 4 0 0 1-4-4V24a4 4 0 0 1 4-4Z" fill="#fff"/><circle cx="21" cy="30" r="2" fill="#5a3fe0"/><circle cx="27" cy="30" r="2" fill="#5a3fe0"/><circle cx="33" cy="30" r="2" fill="#5a3fe0"/>') },
    { svg: tile(grad("g9", "#4be0b0", "#0e9f78"), '<rect x="13" y="22" width="26" height="20" rx="4" fill="#fff"/><path d="m41 28 10-6v20l-10-6Z" fill="#fff"/>') },
    { svg: tile(grad("g10", "#ffb340", "#ff6a00"), '<circle cx="32" cy="32" r="14" fill="none" stroke="#fff" stroke-width="4"/><path d="M32 22v10l7 5" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/>') },
    { run: true, svg: tile(grad("g11", "#2e3b55", "#151c2c"), '<circle cx="32" cy="32" r="17" fill="none" stroke="#7cc4ff" stroke-width="3.5"/><path d="M15 32h34M32 15c6 6 6 28 0 34M32 15c-6 6-6 28 0 34" fill="none" stroke="#7cc4ff" stroke-width="3"/>') },
    { sep: true },
    { svg: tile(grad("g12", "#6ec6ff", "#1e7bdc"), '<path d="M14 22h14l4 5h18v19H14Z" fill="#fff" opacity=".95"/><path d="M32 30v11M27 36l5 5 5-5" stroke="#1e7bdc" stroke-width="3" fill="none" stroke-linecap="round"/>') },
    { svg: '<svg viewBox="0 0 64 64"><path d="M17 18h30l-3 38H20Z" fill="rgba(235,240,248,.55)" stroke="rgba(255,255,255,.7)" stroke-width="1.5"/><rect x="14" y="13" width="36" height="6" rx="3" fill="rgba(235,240,248,.75)"/><path d="M26 25v24M32 25v24M38 25v24" stroke="rgba(120,130,150,.6)" stroke-width="1.6"/></svg>' },
  ];

  // Night coast: dark ridges falling to the sea, lit by a cold sky.
  const WALLPAPER = `<svg class="wallpaper" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a1a2c"/><stop offset=".45" stop-color="#14324d"/><stop offset="1" stop-color="#0c2134"/></linearGradient>
      <linearGradient id="sea" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b5f7c"/><stop offset=".55" stop-color="#0d3a54"/><stop offset="1" stop-color="#06192a"/></linearGradient>
      <linearGradient id="land" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b3a54"/><stop offset=".6" stop-color="#0f263a"/><stop offset="1" stop-color="#0a1b2a"/></linearGradient>
      <linearGradient id="far" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#26496a"/><stop offset="1" stop-color="#173350"/></linearGradient>
      <radialGradient id="glow" cx=".2" cy=".75" r=".6"><stop offset="0" stop-color="#2a86a8" stop-opacity=".55"/><stop offset="1" stop-color="#2a86a8" stop-opacity="0"/></radialGradient>
    </defs>
    <rect width="1920" height="1080" fill="url(#sky)"/>
    <rect y="420" width="1920" height="660" fill="url(#sea)"/>
    <rect y="420" width="1920" height="660" fill="url(#glow)"/>
    <path d="M0 250 L140 210 L260 228 L400 170 L520 196 L660 150 L800 182 L950 128 L1090 160 L1230 110 L1380 140 L1520 96 L1680 120 L1820 84 L1920 100 L1920 420 L0 420Z" fill="url(#far)"/>
    <path d="M0 470 C140 452 250 500 380 520 C520 545 620 600 760 640 C900 680 1050 690 1200 712 C1380 738 1560 770 1720 790 C1810 800 1880 806 1920 810 L1920 150 L1820 196 L1700 168 L1560 226 L1440 200 L1300 262 L1160 236 L1020 300 L880 276 L740 340 L600 318 L470 380 L330 356 L200 410 L80 392 L0 420Z" fill="url(#land)"/>
    <g fill="none" stroke="#3d6688" stroke-opacity=".32" stroke-width="2">
      <path d="M180 430 C330 380 470 400 620 360 C760 322 900 330 1040 300 C1200 268 1360 250 1520 214 C1660 184 1800 170 1920 160"/>
      <path d="M420 520 C560 470 700 470 840 430 C1000 386 1160 380 1320 340 C1480 300 1640 286 1920 250"/>
      <path d="M760 620 C900 570 1040 560 1180 520 C1340 474 1520 460 1700 420 C1800 398 1880 390 1920 386"/>
      <path d="M1100 700 C1240 660 1380 640 1540 600 C1680 566 1820 550 1920 540"/>
    </g>
    <path d="M0 470 C140 452 250 500 380 520 C520 545 620 600 760 640 C900 680 1050 690 1200 712 C1380 738 1560 770 1720 790 C1810 800 1880 806 1920 810" fill="none" stroke="#8fc7dc" stroke-opacity=".35" stroke-width="3"/>
  </svg>`;

  let S, L, tr;
  const dom = { tabs: {}, pages: {} };
  let perTab = {};
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function build(scene) {
    S = scene;
    L = scene.layout;
    tr = scene.tracks;
    for (const k of ["moves", "presses", "tabs", "active", "tab_page", "typing", "loading", "scroll", "camera"]) {
      tr[k] = (tr[k] || []).slice().sort((a, b) => (a.t ?? a.t0) - (b.t ?? b.t0));
    }
    perTab = {};
    for (const e of tr.tab_page) (perTab[e.tab] = perTab[e.tab] || []).push(e);

    const stage = document.getElementById("stage");
    stage.innerHTML = "";
    const camera = el("div", "", stage);
    camera.id = "camera";
    camera.innerHTML = WALLPAPER;
    const w = L.window;

    const menubar = el("div", "menubar", camera,
      '<div class="menus"><b>Chrome</b><span>File</span><span>Edit</span><span>View</span><span>History</span><span>Bookmarks</span><span>Profiles</span><span>Tab</span><span>Window</span><span>Help</span></div>' +
      '<div class="status">' +
      '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2.5"/><circle cx="12" cy="12" r="2.5" class="fill"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M12 3v10M8 9l4 4 4-4M5 15v4h14v-4"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M7 7l10 10-5 5V2l5 5L7 17"/></svg>' +
      '<svg viewBox="0 0 28 24"><rect x="1.5" y="6" width="22" height="12" rx="3.5"/><rect x="4" y="8.5" width="13" height="7" rx="1.6" class="fill"/><path d="M26 10v4"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M2 9a15 15 0 0 1 20 0M5.5 12.5a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0"/><circle cx="12" cy="19.5" r="1.2" class="fill"/></svg>' +
      '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></svg>' +
      '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="6" rx="3"/><rect x="3" y="13" width="18" height="6" rx="3"/><circle cx="16" cy="8" r="1.6" class="fill"/><circle cx="8" cy="16" r="1.6" class="fill"/></svg>' +
      '<span class="clock"></span></div>');
    menubar.style.height = `${L.menubar_h}px`;
    dom.clock = menubar.querySelector(".clock");

    const d = L.dock;
    const dock = el("div", "dock", camera);
    for (const app of DOCK_APPS) {
      if (app.sep) {
        el("div", "sep", dock);
        continue;
      }
      const a = el("div", `app${app.run ? " running" : ""}`, dock, app.svg + (app.badge ? `<span class="badge">${app.badge}</span>` : ""));
      Object.assign(a.style, { width: `${d.icon}px`, height: `${d.icon}px` });
    }
    Object.assign(dock.style, { height: `${d.h}px`, top: `${d.y}px` });
    dock.style.left = "0px";
    camera.appendChild(dock);
    dock.style.left = `${(W - dock.offsetWidth) / 2}px`;

    const win = el("div", "window", camera);
    Object.assign(win.style, { left: `${w.x}px`, top: `${w.y}px`, width: `${w.w}px`, height: `${w.h}px` });

    // tab strip
    const strip = el("div", "tabstrip", win);
    strip.style.height = `${L.tabstrip_h}px`;
    el("div", "lights", strip, "<i></i><i></i><i></i>");
    el("div", "tabsearch", strip, '<svg viewBox="0 0 24 24" style="padding:5px"><path d="m7 10 5 5 5-5"/></svg>');
    scene.tabs.forEach((t, i) => {
      const tab = el("div", "tab", strip,
        '<span class="fav globe"></span><span class="title"></span><svg class="x" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></svg>');
      Object.assign(tab.style, { left: `${L.tabs.x - w.x + i * (L.tabs.w + 4)}px`, top: `${L.tabs.y - w.y}px`, width: `${L.tabs.w}px`, height: `${L.tabstrip_h - (L.tabs.y - w.y)}px` });
      dom.tabs[t.id] = { root: tab, fav: tab.querySelector(".fav"), title: tab.querySelector(".title"), favKey: null };
    });
    dom.plus = el("div", "plus", strip, '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>');
    dom.plus.style.top = `${(L.tabstrip_h - 28) / 2 + 1}px`;

    // toolbar
    const toolbar = el("div", "toolbar", win);
    Object.assign(toolbar.style, { top: `${L.tabstrip_h}px`, height: `${L.toolbar_h}px` });
    const nav = el("div", "nav", toolbar,
      '<svg viewBox="0 0 24 24" class="back"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>' +
      '<svg viewBox="0 0 24 24" class="dim"><path d="M5 12h14M13 6l6 6-6 6"/></svg><span class="reload"></span>');
    dom.back = nav.querySelector(".back");
    dom.reload = nav.querySelector(".reload");
    const a = L.address;
    dom.omni = el("div", "omnibox", toolbar);
    Object.assign(dom.omni.style, { left: `${a.x - w.x}px`, top: `${a.y - w.y - L.tabstrip_h}px`, width: `${a.w}px`, height: `${a.h}px` });
    dom.omniLead = el("span", "", dom.omni);
    dom.omniText = el("div", "text", dom.omni);
    dom.omniStar = el("span", "", dom.omni);
    dom.suggest = el("div", "suggest", dom.omni);
    const exts = ["#7b8cff", "#ffb347", "#55c2a8", "#e86a6a", "#9aa3b5"];
    el("div", "tools", toolbar,
      exts.map((c) => `<i class="ext" style="background:${c};opacity:.85"></i>`).join("") +
      '<svg viewBox="0 0 24 24"><path d="M10 4h4v3a2 2 0 1 0 4 0V4h2v6h-3a2 2 0 1 0 0 4h3v6h-6v-3a2 2 0 1 0-4 0v3H4v-6h3a2 2 0 1 0 0-4H4V4h6Z"/></svg>' +
      '<span class="avatar"></span><svg viewBox="0 0 24 24"><circle cx="12" cy="5.5" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="12" cy="18.5" r="1.3"/></svg>');

    // bookmarks bar
    const folder = '<svg viewBox="0 0 24 24"><path d="M3 6h7l2 2.5h9V19H3Z"/></svg>';
    const bm = el("div", "bookmarks", win,
      '<span class="bm"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg></span>' +
      [["#14a800", "Upwork"], ["#ea4335", "Inbox"], ["#7b68ee", "Client projects"], ["#2684ff", "Proposals"], ["#f4b400", "Invoices"], ["#34a853", "Docs"]]
        .map(([c, t]) => `<span class="bm"><i style="background:${c}"></i>${esc(t)}</span>`).join("") +
      `<span class="bm">${folder}Useful tools</span><span class="bm right">${folder}All Bookmarks</span>`);
    Object.assign(bm.style, { top: `${L.tabstrip_h + L.toolbar_h}px`, height: `${L.bookmarks_h}px` });

    const content = el("div", "content", win);
    content.style.top = `${L.tabstrip_h + L.toolbar_h + L.bookmarks_h}px`;
    const loads = [];
    for (const [id, page] of Object.entries(scene.pages)) {
      let root;
      if (page.status === "start") {
        root = el("div", "page start", content,
          `<div class="box">${ICON.search.replace('class="lead" ', "")}Search or type a URL</div>` +
          '<div class="tiles">' + [["U", "Upwork", "#14a800"], ["M", "Inbox", "#c5221f"], ["P", "Projects", "#5b4bd6"], ["D", "Docs", "#1a73e8"], ["C", "Calendar", "#0b8043"], ["+", "Add shortcut", "#4a4953"]]
            .map(([l, t, c]) => `<div class="tile"><i style="background:${c}">${l}</i>${t}</div>`).join("") + "</div>");
      } else if (page.image) {
        root = el("div", "page", content);
        const img = el("img", "", root);
        img.alt = "";
        img.src = ASSETS + page.image;
        loads.push(img.decode().catch(() => {}));
        dom.pages[id] = { root, img };
      } else {
        const host = splitUrl(page.url).host || "This site";
        root = el("div", "page placeholder-page", content,
          `<div class="card"><svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#b9b7c2" stroke-width="1.5"><path d="M4 5h16v12H4ZM8 21h8M12 17v4"/><path d="m9 9 6 4M15 9l-6 4"/></svg>` +
          `<b>This site can’t be reached</b><span>${esc(host)} took too long to respond.</span></div>`);
      }
      dom.pages[id] = dom.pages[id] || { root };
      if (page.favicon) {
        const pre = new Image();
        pre.src = ASSETS + page.favicon;
        loads.push(pre.decode().catch(() => {}));
      }
    }

    dom.camera = camera;
    dom.cursor = el("div", "", stage, '<svg viewBox="0 0 24 24"><path d="M5.5 2.8v16.6l4.1-3.9 2.7 6 2.9-1.3-2.7-5.9 5.6-.3Z"/></svg>');
    dom.cursor.id = "cursor";
    return Promise.all(loads);
  }

  /* ── state at time t ─────────────────────────────────────────────────── */

  function cameraAt(t) {
    const shots = tr.camera;
    if (!shots.length) return { z: 1, cx: W / 2, cy: H / 2 };
    let from = { zoom: 1, fx: W / 2, fy: H / 2 }, target = from, lastT = 0;
    const mix = (p) => ({ zoom: lerp(from.zoom, target.zoom, p), fx: lerp(from.fx, target.fx, p), fy: lerp(from.fy, target.fy, p) });
    for (const shot of shots) {
      if (shot.t > t) break;
      from = mix(easeOut(clamp((shot.t - lastT) / CAM_MS)));
      target = shot;
      lastT = shot.t;
    }
    const v = mix(easeOut(clamp((t - lastT) / CAM_MS)));
    const z = Math.max(1, v.zoom);
    const k = PAN * clamp((z - 1) / 0.12);
    let cx = W / 2 + (v.fx - W / 2) * k, cy = H / 2 + (v.fy - H / 2) * k;
    cx = clamp(cx, W / (2 * z), W - W / (2 * z));
    cy = clamp(cy, H / (2 * z), H - H / (2 * z));
    return { z, cx, cy };
  }

  function cursorAt(t) {
    let idx = -1;
    for (let i = 0; i < tr.moves.length; i++) {
      if (tr.moves[i].t0 <= t) idx = i;
      else break;
    }
    if (idx < 0) return { x: S.cursor.start[0], y: S.cursor.start[1] };
    const m = tr.moves[idx];
    if (t >= m.t1) return { x: m.x1, y: m.y1 };
    // A hand on a trackpad: quick start, gentle landing, on a slight arc.
    const p = pointer(clamp((t - m.t0) / (m.t1 - m.t0)));
    const dx = m.x1 - m.x0, dy = m.y1 - m.y0;
    const bend = 0.08 * (idx % 2 ? 1 : -1);
    const cx = (m.x0 + m.x1) / 2 - dy * bend, cy = (m.y0 + m.y1) / 2 + dx * bend;
    const u = 1 - p;
    return { x: u * u * m.x0 + 2 * u * p * cx + p * p * m.x1, y: u * u * m.y0 + 2 * u * p * cy + p * p * m.y1 };
  }

  function pageOf(tabId, t) {
    const e = lastAt(perTab[tabId] || [], t);
    return e ? e : { page: "start", t: 0 };
  }

  function scrollOf(tabId, shown, t) {
    let y = 0;
    for (const s of tr.scroll) {
      if (s.t0 > t) break;
      if (s.tab !== tabId || s.page !== shown.page || s.t0 < shown.t) continue;
      y = t >= s.t1 ? s.to : lerp(s.from, s.to, easeOutCubic(clamp((t - s.t0) / (s.t1 - s.t0))));
    }
    return y;
  }

  function clockText(t) {
    if (!S.clock_ms) return "Tue 9:41 AM";
    const d = new Date(S.clock_ms + t);
    const h = d.getUTCHours(), m = d.getUTCMinutes();
    return `${DAYS[d.getUTCDay()]} ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}  ${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  }

  function seek(t) {
    const cam = cameraAt(t);
    dom.camera.style.transform = `translate(${W / 2 - cam.cx * cam.z}px, ${H / 2 - cam.cy * cam.z}px) scale(${cam.z})`;
    const clock = clockText(t);
    dom.clock.textContent = clock;

    const opened = tr.tabs.filter((x) => x.t <= t).map((x) => x.id);
    const active = (lastAt(tr.active, t) || { id: "t0" }).id;
    const loads = tr.loading.filter((x) => t >= x.t0 && t < x.t1);
    const spin = Math.round(((t * 0.4) % 360) / 15) * 15;
    for (const [id, tab] of Object.entries(dom.tabs)) {
      const isOpen = opened.includes(id);
      tab.root.classList.toggle("open", isOpen);
      tab.root.classList.toggle("active", id === active);
      if (!isOpen) continue;
      const page = S.pages[pageOf(id, t).page];
      tab.title.textContent = page.title || splitUrl(page.url).host || "New Tab";
      const loading = loads.some((x) => x.tab === id);
      const key = loading ? "spin" : page.favicon ? ASSETS + page.favicon : "globe";
      if (key !== tab.favKey) {
        tab.favKey = key;
        let node;
        if (key === "spin") {
          node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          node.setAttribute("viewBox", "0 0 24 24");
          node.setAttribute("class", "spin");
          node.innerHTML = '<circle cx="12" cy="12" r="8"/>';
        } else if (key === "globe") {
          node = document.createElement("span");
          node.className = "fav globe";
        } else {
          node = document.createElement("img");
          node.className = "fav";
          node.src = key;
        }
        tab.fav.replaceWith(node);
        tab.fav = node;
      }
      if (key === "spin") tab.fav.style.transform = `rotate(${spin}deg)`;
    }
    const nOpen = opened.length;
    dom.plus.style.left = `${L.tabs.x - L.window.x + nOpen * (L.tabs.w + 4) + 4}px`;

    const shown = pageOf(active, t);
    const scroll = scrollOf(active, shown, t);
    for (const [id, p] of Object.entries(dom.pages)) p.root.classList.toggle("show", id === shown.page);
    const pageDom = dom.pages[shown.page];
    if (pageDom && pageDom.img) pageDom.img.style.transform = `translateY(${-Math.round(scroll)}px)`;

    const history = (perTab[active] || []).filter((e) => e.t <= t).length;
    dom.back.classList.toggle("dim", history < 2);
    const activeLoading = loads.some((x) => x.tab === active);
    dom.reload.innerHTML = activeLoading ? ICON.stop : ICON.reload;

    // omnibox
    const typing = tr.typing.find((x) => x.tab === active && t >= x.t0 - 90 && t < x.enter);
    let omniSig;
    if (typing) {
      const n = t < typing.t0 ? 0 : Math.round(clamp((t - typing.t0) / (typing.t1 - typing.t0)) * typing.text.length);
      const typed = typing.text.slice(0, n);
      const caret = Math.floor(t / 530) % 2 === 0;
      dom.omni.classList.add("focus");
      dom.omni.classList.toggle("open", n > 0);
      dom.omniLead.innerHTML = ICON.search;
      dom.omniText.innerHTML = `<span class="host">${esc(typed)}</span>${caret ? '<span class="caret"></span>' : ""}`;
      dom.omniStar.innerHTML = "";
      if (n > 0) {
        const isSearch = typing.kind === "search";
        dom.suggest.innerHTML =
          `<div class="row sel">${isSearch ? ICON.search.replace('class="lead" ', "") : ICON.globe}<span>${esc(typed)}</span>` +
          `<span class="muted">${isSearch ? "– Search" : ""}</span></div>` +
          (isSearch ? `<div class="row">${ICON.search.replace('class="lead" ', "")}<span>${esc(typed)} <span class="muted">near me</span></span></div>` : "");
      }
      omniSig = `T${n}${caret ? "|" : ""}`;
    } else {
      dom.omni.classList.remove("focus", "open");
      const page = S.pages[shown.page];
      if (!page.url) {
        // a fresh tab: Chrome puts the caret in the address bar
        const caret = Math.floor(t / 530) % 2 === 0 && opened.length > 1 && active !== "t0";
        dom.omniLead.innerHTML = ICON.search;
        dom.omniText.innerHTML = `<span class="placeholder">Search or type a URL</span>`;
        dom.omniStar.innerHTML = "";
        omniSig = `P${caret ? "|" : ""}`;
      } else {
        const u = splitUrl(page.url);
        dom.omniLead.innerHTML = ICON.tune;
        dom.omniText.innerHTML = `<span class="host">${esc(u.host)}</span><span class="rest">${esc(u.rest)}</span>`;
        dom.omniStar.innerHTML = ICON.star;
        omniSig = `U${shown.page}`;
      }
    }

    // pointer, in screen space: always on screen, no click effects
    const c = cursorAt(t);
    const sx = (c.x - cam.cx) * cam.z + W / 2, sy = (c.y - cam.cy) * cam.z + H / 2;
    const vis = clamp((t - S.cursor.in) / 260) * clamp((S.cursor.out - t) / 260);
    dom.cursor.style.opacity = vis;
    dom.cursor.style.transform = `translate(${sx - 5.5}px, ${sy - 2.8}px)`;

    return [
      cam.z.toFixed(4), cam.cx.toFixed(1), cam.cy.toFixed(1), nOpen, active, shown.page, Math.round(scroll),
      omniSig, activeLoading ? `L${spin}` : "", loads.map((x) => x.tab).join(""), history, clock,
      sx.toFixed(1), sy.toFixed(1), vis.toFixed(2),
    ].join(",");
  }

  /* ── boot ─────────────────────────────────────────────────────────────── */

  function fit() {
    const s = Math.min(innerWidth / W, innerHeight / H);
    const stage = document.getElementById("stage");
    stage.style.transform = `translate(${(innerWidth - W * s) / 2}px, ${(innerHeight - H * s) / 2}px) scale(${s})`;
  }

  const ready = fetch(SCENE_URL)
    .then((r) => {
      if (!r.ok) throw new Error(`scene ${r.status}`);
      return r.json();
    })
    .then(build)
    .then(() => {
      if (MODE === "preview") {
        fit();
        addEventListener("resize", fit);
      }
      seek(0);
      document.documentElement.dataset.ready = "1";
      parent !== window && parent.postMessage({ source: "synccut-stage", type: "ready", duration: S.duration_ms }, "*");
    })
    .catch((e) => {
      document.documentElement.dataset.error = String(e);
      const pre = el("pre", "", document.body);
      pre.style.cssText = "color:#fff;padding:24px";
      pre.textContent = `Stage failed: ${e}`;
    });

  addEventListener("message", (e) => {
    if (e.data && e.data.source === "synccut-editor" && e.data.type === "seek" && S) seek(e.data.t);
  });

  window.stage = { ready, seek: (t) => seek(t) };
})();
