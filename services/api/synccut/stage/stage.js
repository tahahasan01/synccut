/* SyncCut stage: a MacBook screen with one or more Chrome windows, driven by a scene timeline.
 *
 * Everything on screen is a pure function of time: stage.seek(ms) draws the
 * exact state at that moment and returns a signature string, which the renderer
 * uses to reuse identical frames. Preview mode follows postMessage seeks from
 * the editor; render mode is driven by headless Chromium frame by frame.
 *
 * It should read as a plain screen recording: the macOS pointer is always on
 * screen, moves on a slight arc and clicks without effects; pages swap in the
 * moment they "load" while the tab shows Chrome's spinner; new tabs slide open
 * and new windows zoom in the way macOS opens them. The optional camera push-in
 * (off by default) follows the interactive-product-demo skill.
 */
(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  const SCENE_URL = params.get("scene");
  const ASSETS = (params.get("assets") || "").replace(/\/?$/, "/");
  const MODE = params.get("mode") || "preview";

  const CAM_MS = 800;
  const PAN = 0.85;
  const TAB_OPEN_MS = 170;
  const WINDOW_OPEN_MS = 240;
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

  const SVG = (inner, cls = "") => `<svg ${cls ? `class="${cls}" ` : ""}viewBox="0 0 24 24">${inner}</svg>`;
  const ICON = {
    search: SVG('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/>'),
    tune: SVG('<path d="M4 8h9M17 8h3M4 16h3M11 16h9"/><circle cx="15" cy="8" r="2.2"/><circle cx="9" cy="16" r="2.2"/>'),
    globe: SVG('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>'),
    star: SVG('<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9Z"/>'),
    lens: SVG('<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="3.2"/>'),
    back: SVG('<path d="M19 12H5M11 6l-6 6 6 6"/>'),
    fwd: SVG('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    reload: SVG('<path d="M19 12a7 7 0 1 1-2.05-4.95M19 4.5V8h-3.5"/>'),
    stop: SVG('<path d="M6 6l12 12M18 6 6 18"/>'),
    x: SVG('<path d="M7 7l10 10M17 7 7 17"/>', "x"),
  };

  // Chrome toolbar extensions: small coloured glyphs, as installed extensions look.
  const EXTENSIONS = [
    '<rect x="3" y="5" width="18" height="14" rx="3" fill="#9aa0a6"/><circle cx="12" cy="12" r="3.5" fill="#3b3a43"/>',
    '<circle cx="12" cy="12" r="8.5" fill="none" stroke="#f29900" stroke-width="3"/><circle cx="12" cy="12" r="3" fill="#7b61ff"/>',
    '<path d="M12 3 20 12 12 21 4 12Z" fill="#8a5cf6"/>',
    '<rect x="5" y="3" width="14" height="18" rx="2.5" fill="#e8eaed"/><path d="M8 8h8M8 12h8M8 16h5" stroke="#4285f4" stroke-width="1.8"/>',
    '<rect x="3" y="3" width="18" height="18" rx="4" fill="#1a73e8"/><text x="12" y="16.5" text-anchor="middle" font-size="11" font-weight="800" fill="#fff" font-family="-apple-system,Segoe UI,sans-serif">F</text>',
    '<circle cx="12" cy="12" r="9" fill="#ea4335"/><circle cx="12" cy="12" r="4" fill="#fff"/>',
    '<path d="M12 3 19 6v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6Z" fill="#5f6368" stroke="#bdc1c6" stroke-width="1.4"/>',
    '<circle cx="12" cy="12" r="9" fill="#1e8e3e"/><path d="m10 8 6 4-6 4Z" fill="#fff"/>',
    '<rect x="3" y="4" width="18" height="16" rx="3" fill="#c5221f"/><path d="M6 15l4-4 3 3 5-5" stroke="#fff" stroke-width="1.8" fill="none"/>',
  ];
  const AVATAR = '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#7a5a48"/><circle cx="13" cy="10.5" r="5" fill="#e3b28f"/><path d="M3 26c1-6 5-9 10-9s9 3 10 9Z" fill="#2f3b4c"/><path d="M8 9c0-4 2.5-5.5 5-5.5S18 5 18 9c-1.5-1.8-3-2.4-5-2.4S9.5 7.2 8 9Z" fill="#2a1d16"/></svg>';

  // Dock apps: generic glyphs on macOS-style squircle tiles, no real product logos.
  const squircle = (() => {
    const n = 5, c = 32, a = 29, pts = [];
    for (let i = 0; i < 72; i++) {
      const th = (i / 72) * Math.PI * 2, co = Math.cos(th), si = Math.sin(th);
      pts.push(`${(c + a * Math.sign(co) * Math.pow(Math.abs(co), 2 / n)).toFixed(2)} ${(c + a * Math.sign(si) * Math.pow(Math.abs(si), 2 / n)).toFixed(2)}`);
    }
    return `M${pts.join("L")}Z`;
  })();
  let tileN = 0;
  const tile = (fill, inner, defs = "") => {
    const id = `sq${tileN++}`;
    return `<svg viewBox="0 0 64 64"><defs><clipPath id="${id}"><path d="${squircle}"/></clipPath>${defs}</defs>` +
      `<g clip-path="url(#${id})"><rect width="64" height="64" fill="${fill}"/>${inner}</g>` +
      `<path d="${squircle}" fill="none" stroke="rgba(255,255,255,.18)" stroke-width="1"/></svg>`;
  };
  const grad = (id, a, b) => [`url(#${id})`, `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient>`];
  const gtile = (id, a, b, inner) => {
    const [fill, defs] = grad(id, a, b);
    return tile(fill, inner, defs);
  };
  const DOCK_APPS = [
    { run: true, svg: gtile("d1", "#74c7ff", "#1d7ae0", '<path d="M14 21h14l4 5h18v20H14Z" fill="#fff" opacity=".95"/><path d="M14 30h36" stroke="#1d7ae0" stroke-width="1.5" opacity=".35"/>') },
    { svg: gtile("d2", "#5e6069", "#30323a", [0, 1, 2].map((r) => [0, 1, 2].map((c) => `<rect x="${15 + c * 13}" y="${15 + r * 13}" width="9" height="9" rx="2.5" fill="${["#ff6b6b", "#ffd43b", "#69db7c", "#4dabf7", "#da77f2", "#ff922b", "#38d9a9", "#748ffc", "#f783ac"][r * 3 + c]}"/>`).join("")).join("")) },
    { svg: tile("#f5f7fb", '<circle cx="32" cy="32" r="20" fill="none" stroke="#1d8cf8" stroke-width="4"/><path d="m40 24-5 11-11 5 5-11Z" fill="#ff4d4f"/><path d="m24 40 5-11 6 6Z" fill="#c9d3e3"/>') },
    { svg: tile("#1f2430", '<rect x="14" y="19" width="36" height="26" rx="3" fill="none" stroke="#fff" stroke-width="3"/><path d="m21 27 5 4-5 4M29 36h9" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>') },
    { badge: "1", svg: gtile("d3", "#a5aab3", "#5f646e", '<circle cx="32" cy="32" r="13" fill="none" stroke="#eceff3" stroke-width="7" stroke-dasharray="5 4"/><circle cx="32" cy="32" r="8" fill="#3e424b"/><circle cx="32" cy="32" r="4" fill="#d7dbe1"/>') },
    { svg: gtile("d4", "#5cb2ff", "#1769e0", '<rect x="14" y="20" width="36" height="25" rx="3" fill="#fff"/><path d="m15 22 17 12 17-12" fill="none" stroke="#1769e0" stroke-width="2.5"/>') },
    { svg: gtile("d5", "#72f08d", "#22b14c", '<path d="M32 15c10.5 0 19 6.8 19 15.2S42.5 45.4 32 45.4c-2 0-4-.3-5.9-.8L17.5 48l2.7-6.8C16 38.4 13 34.6 13 30.2 13 21.8 21.5 15 32 15Z" fill="#fff"/>') },
    { svg: tile("#fff", '<rect width="64" height="20" fill="#ff3b30"/><text x="32" y="15" text-anchor="middle" font-size="10.5" font-weight="700" fill="#fff" font-family="-apple-system,Segoe UI,sans-serif">OCT</text><text x="32" y="49" text-anchor="middle" font-size="27" font-weight="300" fill="#222" font-family="-apple-system,Segoe UI,sans-serif">13</text>') },
    { svg: tile("#fffdf2", '<rect width="64" height="18" fill="#ffd60a"/><path d="M13 30h38M13 38h38M13 46h26" stroke="#d6d1bf" stroke-width="2"/>') },
    { svg: gtile("d6", "#ff7c95", "#fa2d48", '<path d="M27 43V22l16-4v20" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/><circle cx="23" cy="43" r="5" fill="#fff"/><circle cx="39" cy="38" r="5" fill="#fff"/>') },
    { svg: tile("#fff", ["#ff9f0a", "#ffd60a", "#30d158", "#64d2ff", "#5e5ce6", "#ff375f"].map((c, i) => `<ellipse cx="32" cy="20" rx="6" ry="11" fill="${c}" opacity=".88" transform="rotate(${i * 60} 32 32)"/>`).join("")) },
    { run: true, svg: gtile("d7", "#3ea2ff", "#0b5cd6", '<path d="m26 22-10 10 10 10M38 22l10 10-10 10" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>') },
    { run: true, svg: gtile("d8", "#8e80ff", "#5a3fe0", '<path d="M16 20h22a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4H26l-7 6v-6h-3a4 4 0 0 1-4-4V24a4 4 0 0 1 4-4Z" fill="#fff"/><circle cx="21" cy="30" r="2" fill="#5a3fe0"/><circle cx="27" cy="30" r="2" fill="#5a3fe0"/><circle cx="33" cy="30" r="2" fill="#5a3fe0"/>') },
    { svg: gtile("d9", "#4fe2b3", "#0e9f78", '<rect x="12" y="22" width="27" height="20" rx="4" fill="#fff"/><path d="m41 28 11-6v20l-11-6Z" fill="#fff"/>') },
    { svg: gtile("d10", "#ffb544", "#ff6a00", '<circle cx="32" cy="32" r="14" fill="none" stroke="#fff" stroke-width="4"/><path d="M32 22v10l7 5" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/>') },
    { run: true, svg: gtile("d11", "#33415e", "#141b2b", '<circle cx="32" cy="32" r="17" fill="none" stroke="#7cc4ff" stroke-width="3.5"/><path d="M15 32h34M32 15c6 6 6 28 0 34M32 15c-6 6-6 28 0 34" fill="none" stroke="#7cc4ff" stroke-width="3"/>') },
    { sep: true },
    { svg: gtile("d12", "#74c7ff", "#1d7ae0", '<path d="M14 21h14l4 5h18v20H14Z" fill="#fff" opacity=".95"/><path d="M32 30v11M27 36l5 5 5-5" stroke="#1d7ae0" stroke-width="3" fill="none" stroke-linecap="round"/>') },
    { svg: '<svg viewBox="0 0 64 64"><path d="M17 18h30l-3 38H20Z" fill="rgba(235,240,248,.5)" stroke="rgba(255,255,255,.7)" stroke-width="1.5"/><rect x="14" y="13" width="36" height="6" rx="3" fill="rgba(235,240,248,.72)"/><path d="M26 25v24M32 25v24M38 25v24" stroke="rgba(120,130,150,.6)" stroke-width="1.6"/></svg>' },
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

  const MENU_STATUS = [
    '<rect x="3" y="6" width="18" height="12" rx="2.5"/><circle cx="12" cy="12" r="2.5" class="fill"/>',
    '<path d="M4 17c2-6 5-9 8-9s6 3 8 9"/><path d="M8 17h8"/>',
    '<path d="M12 3v10M8 9l4 4 4-4M5 15v4h14v-4"/>',
    '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9Z"/>',
    '<path d="M7 7l10 10-5 5V2l5 5L7 17"/>',
    '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    '<path d="M12 4v16M4 12h16" />',
  ];

  let S, L, tr;
  let skinUrl = (name) => "";
  const dom = { windows: {}, tabs: {} };
  let perTab = {};
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function newTabPage(parent) {
    return el("div", "page start", parent,
      `<div class="box">${ICON.search}Search or type a URL</div>` +
      '<div class="tiles">' + [["U", "Upwork", "#14a800"], ["M", "Inbox", "#c5221f"], ["P", "Projects", "#5b4bd6"], ["D", "Docs", "#1a73e8"], ["C", "Calendar", "#0b8043"], ["+", "Add shortcut", "#4a4953"]]
        .map(([l, t, c]) => `<div class="tile"><i>${l === "+" ? "+" : `<b style="background:${c}">${l}</b>`}</i>${t}</div>`).join("") + "</div>");
  }

  /* A window cut from the user's own screenshot (skin.py): only what changes is drawn. */
  function buildSkinWindow(win, camera, loads) {
    const r = win.rect, C = S.skin.colors, o = L.omnibox;
    const root = el("div", "window skin", camera);
    Object.assign(root.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
    // the theme's own colours (custom properties need setProperty; Object.assign ignores them)
    for (const [k, v] of Object.entries({ strip: C.strip, toolbar: C.toolbar, omni: C.omni, text: C.text, muted: C.muted, icon: C.icon })) {
      root.style.setProperty(`--${k}`, v);
    }
    const base = el("img", "base", root);
    base.src = skinUrl("window");
    loads.push(base.decode().catch(() => {}));

    const strip = el("div", "tabstrip", root);
    strip.style.height = `${L.tabstrip_h}px`;
    const cover = el("div", "cover", strip);  // hides the screenshot's own tab and +
    Object.assign(cover.style, { left: `${L.tab.left - 10}px`, top: "2px", width: "290px", height: `${L.tabstrip_h - 2}px` });
    el("div", "dim-lights", strip, "<i></i><i></i><i></i>");
    const plus = el("img", "plus-img", strip);
    plus.src = skinUrl("plus");

    const back = el("div", "nav-on back-on", root, ICON.back);
    const stop = el("div", "nav-on stop-on", root, ICON.stop);

    const omni = el("div", "omni-skin", root);
    Object.assign(omni.style, { left: `${o.left}px`, top: `${o.top}px`, width: `${o.w}px`, height: `${o.h}px` });
    const focusImg = el("img", "focus-img", omni);
    focusImg.src = skinUrl("omni_focus");
    const caretCover = el("div", "caret-cover", omni);
    const typed = el("div", "typed", omni);
    const pill = el("div", "pill", omni);
    const pillLead = el("span", "chip", pill);
    const pillText = el("div", "text", pill);
    const pillEnd = el("span", "end", pill);
    const suggest = el("div", "suggest", omni);

    const content = el("div", "content", root);
    Object.assign(content.style, { top: `${L.tabstrip_h + L.toolbar_h + L.bookmarks_h}px`, left: `${L.content_inset}px`, right: `${L.content_inset}px` });
    const pages = {};
    for (const [id, page] of Object.entries(S.pages)) {
      let pr, img = null;
      if (page.status === "start") {
        pr = el("div", "page ntp", content);
        img = el("img", "", pr);
        img.src = skinUrl("ntp");
      } else if (page.image) {
        pr = el("div", "page", content);
        img = el("img", "", pr);
        img.src = ASSETS + page.image;
      } else {
        const host = splitUrl(page.url).host || "This site";
        pr = el("div", "page placeholder-page", content,
          `<div class="card"><svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#b9b7c2" stroke-width="1.5"><path d="M4 5h16v12H4ZM8 21h8M12 17v4"/><path d="m9 9 6 4M15 9l-6 4"/></svg>` +
          `<b>This site can’t be reached</b><span>${esc(host)} took too long to respond.</span></div>`);
      }
      img && (img.alt = "", loads.push(img.decode().catch(() => {})));
      pages[id] = { root: pr, img: page.status === "start" ? null : img };
    }
    dom.windows[win.id] = { skin: true, root, strip, plus, back, stop, omni, focusImg, caretCover, typed, pill, pillLead, pillText, pillEnd, suggest, pages };
  }

  function drawOmniboxSkin(w, active, shown, t, isFront) {
    const typing = isFront && tr.typing.find((x) => x.tab === active && t >= x.t0 - 90 && t < x.enter);
    const page = S.pages[shown.page];
    const caretOn = Math.floor(t / 530) % 2 === 0;
    const focused = Boolean(typing) || (isFront && !page.url);
    w.focusImg.style.display = focused ? "block" : "none";
    w.caretCover.style.display = focused ? "block" : "none";
    w.pill.style.display = focused ? "none" : "flex";
    w.typed.style.display = focused ? "flex" : "none";
    w.omni.classList.toggle("open", false);
    if (typing) {
      let n = 0;
      if (typing.keys) {
        for (const k of typing.keys) if (t >= typing.t0 + k) n++;
      } else {
        n = t < typing.t0 ? 0 : Math.round(clamp((t - typing.t0) / (typing.t1 - typing.t0)) * typing.text.length);
      }
      const isSearch = typing.kind === "search";
      const text = typing.text.slice(0, n);
      const completion = !isSearch && n >= 2 ? typing.text.slice(n) : "";
      const caret = !completion && caretOn;
      w.typed.innerHTML = `<span>${esc(text)}</span>${caret ? '<span class="caret"></span>' : ""}${completion ? `<span class="auto">${esc(completion)}</span>` : ""}`;
      w.omni.classList.toggle("open", n > 0);
      if (n > 0) {
        w.suggest.innerHTML = isSearch
          ? `<div class="row sel">${ICON.search}<span>${esc(text)}</span><span class="muted">– Google Search</span></div>` +
            `<div class="row">${ICON.search}<span>${esc(text)} <span class="muted">near me</span></span></div>` +
            `<div class="row">${ICON.search}<span>${esc(text)} <span class="muted">examples</span></span></div>`
          : `<div class="row sel">${ICON.globe}<span><b>${esc(text)}</b>${esc(completion)}</span></div>` +
            `<div class="row">${ICON.search}<span>${esc(text)}</span><span class="muted">– Google Search</span></div>`;
      }
      return `T${n}${caret ? "|" : ""}${completion ? "c" : ""}`;
    }
    if (focused) {  // a fresh tab: the screenshot's own focused omnibox, with a blinking caret
      w.typed.innerHTML = caretOn ? '<span class="caret"></span>' : "";
      return `F${caretOn ? "|" : ""}`;
    }
    if (!page.url) {
      w.pillLead.className = "chip";
      w.pillLead.innerHTML = ICON.search;
      w.pillText.innerHTML = '<span class="placeholder">Search Google or type a URL</span>';
      w.pillEnd.innerHTML = "";
      return "P";
    }
    const u = splitUrl(page.url);
    w.pillLead.className = "chip site";
    w.pillLead.innerHTML = ICON.tune;
    w.pillText.innerHTML = `<span class="host">${esc(u.host)}</span><span class="rest">${esc(u.rest)}</span>`;
    w.pillEnd.innerHTML = ICON.star;
    return `U${shown.page}`;
  }

  function buildWindow(win, camera, loads) {
    if (S.skin) return buildSkinWindow(win, camera, loads);
    const r = win.rect;
    const root = el("div", "window", camera);
    Object.assign(root.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });

    const strip = el("div", "tabstrip", root);
    strip.style.height = `${L.tabstrip_h}px`;
    el("div", "lights", strip, "<i></i><i></i><i></i>");
    el("div", "tabsearch", strip, '<svg viewBox="0 0 24 24" style="padding:5px"><path d="m7 10 5 5 5-5"/></svg>');
    const plus = el("div", "plus", strip, '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>');
    plus.style.top = `${(L.tabstrip_h - 28) / 2 + 2}px`;

    const toolbar = el("div", "toolbar", root);
    Object.assign(toolbar.style, { top: `${L.tabstrip_h}px`, height: `${L.toolbar_h}px` });
    const nav = el("div", "nav", toolbar, `<span class="back">${ICON.back}</span><span class="dim">${ICON.fwd}</span><span class="reload"></span>`);
    const o = L.omnibox;
    const omni = el("div", "omnibox", toolbar);
    Object.assign(omni.style, { left: `${o.left}px`, top: `${(L.toolbar_h - o.h) / 2}px`, width: `${r.w - o.left - o.right}px`, height: `${o.h}px` });
    const omniLead = el("span", "chip", omni);
    const omniText = el("div", "text", omni);
    const omniEnd = el("span", "end", omni);
    const suggest = el("div", "suggest", omni);
    el("div", "tools", toolbar,
      EXTENSIONS.map((g) => `<span class="ext"><svg viewBox="0 0 24 24">${g}</svg></span>`).join("") +
      '<svg viewBox="0 0 24 24"><path d="M10 4h4v3a2 2 0 1 0 4 0V4h2v6h-3a2 2 0 1 0 0 4h3v6h-6v-3a2 2 0 1 0-4 0v3H4v-6h3a2 2 0 1 0 0-4H4V4h6Z"/></svg>' +
      `<span class="avatar">${AVATAR}</span><svg viewBox="0 0 24 24"><circle cx="12" cy="5.5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="18.5" r="1.2"/></svg>`);

    const folder = '<svg viewBox="0 0 24 24"><path d="M3 6h7l2 2.5h9V19H3Z"/></svg>';
    const bm = el("div", "bookmarks", root,
      '<span class="bm"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/></svg></span>' +
      '<span class="bm"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg></span>' +
      '<span class="divider"></span>' +
      [["#14a800", "up", "Upwork"], ["#ea4335", "M", "Inbox (683)"], ["#7b68ee", "C", "Client projects"], ["#2684ff", "P", "Proposals"], ["#f4b400", "$", "Invoices"], ["#34a853", "D", "Docs"]]
        .map(([c, g, t]) => `<span class="bm"><i style="background:${c}">${esc(g)}</i>${esc(t)}</span>`).join("") +
      `<span class="bm">${folder}Useful tools</span><span class="bm right">${folder}All Bookmarks</span>`);
    Object.assign(bm.style, { top: `${L.tabstrip_h + L.toolbar_h}px`, height: `${L.bookmarks_h}px` });

    const content = el("div", "content", root);
    content.style.top = `${L.tabstrip_h + L.toolbar_h + L.bookmarks_h}px`;
    const pages = {};
    for (const [id, page] of Object.entries(S.pages)) {
      let p;
      if (page.status === "start") {
        p = { root: newTabPage(content) };
      } else if (page.image) {
        const pr = el("div", "page", content);
        const img = el("img", "", pr);
        img.alt = "";
        img.src = ASSETS + page.image;
        loads.push(img.decode().catch(() => {}));
        p = { root: pr, img };
      } else {
        const host = splitUrl(page.url).host || "This site";
        p = { root: el("div", "page placeholder-page", content,
          `<div class="card"><svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#b9b7c2" stroke-width="1.5"><path d="M4 5h16v12H4ZM8 21h8M12 17v4"/><path d="m9 9 6 4M15 9l-6 4"/></svg>` +
          `<b>This site can’t be reached</b><span>${esc(host)} took too long to respond.</span></div>`) };
      }
      pages[id] = p;
    }
    dom.windows[win.id] = { root, strip, plus, back: nav.querySelector(".back"), reload: nav.querySelector(".reload"),
      omni, omniLead, omniText, omniEnd, suggest, pages, key: {} };
  }

  function build(scene) {
    S = scene;
    L = scene.layout;
    tr = scene.tracks;
    for (const k of ["moves", "presses", "windows", "front", "tabs", "active", "tab_page", "typing", "loading", "scroll", "camera"]) {
      tr[k] = (tr[k] || []).slice().sort((a, b) => (a.t ?? a.t0) - (b.t ?? b.t0));
    }
    // older scenes had one window and no window ids
    if (!S.windows) S.windows = [{ id: "w0", index: 0, rect: L.window }];
    if (!tr.windows.length) tr.windows = [{ t: 0, id: "w0" }];
    if (!tr.front.length) tr.front = [{ t: 0, id: "w0" }];
    for (const t of S.tabs) t.win = t.win || "w0";
    for (const x of tr.tabs) x.win = x.win || "w0";
    for (const x of tr.active) x.win = x.win || "w0";
    perTab = {};
    for (const e of tr.tab_page) (perTab[e.tab] = perTab[e.tab] || []).push(e);

    const stage = document.getElementById("stage");
    stage.innerHTML = "";
    const camera = el("div", "", stage);
    camera.id = "camera";
    const loads = [];
    if (S.skin) {
      // The user's own desktop: wallpaper, menu bar and Dock exactly as in their screenshot.
      const root = new URL(S.skin.url, location.href).href.replace(/\/?$/, "/");
      skinUrl = (name) => `${root}${name}.png?v=${S.skin.version}`;
      stage.classList.add("skinned");
      const desk = el("img", "wallpaper", camera);
      desk.src = skinUrl("desktop");
      loads.push(desk.decode().catch(() => {}));
      dom.clock = null;
      for (const win of S.windows) buildWindow(win, camera, loads);
      buildTabs(loads);
      dom.camera = camera;
      dom.cursor = el("div", "", stage, '<svg viewBox="0 0 24 24"><path d="M5.5 2.8v16.6l4.1-3.9 2.7 6 2.9-1.3-2.7-5.9 5.6-.3Z"/></svg>');
      dom.cursor.id = "cursor";
      return Promise.all(loads);
    }
    camera.innerHTML = WALLPAPER;

    const menubar = el("div", "menubar", camera,
      '<div class="menus"><b>Chrome</b><span>File</span><span>Edit</span><span>View</span><span>History</span><span>Bookmarks</span><span>Profiles</span><span>Tab</span><span>Window</span><span>Help</span></div>' +
      '<div class="status">' + MENU_STATUS.map((g) => `<svg viewBox="0 0 24 24">${g}</svg>`).join("") +
      '<svg viewBox="0 0 24 24"><path d="M12 3v18M7 7.5l10 9-5 4.5V3l5 4.5-10 9"/></svg>' +
      '<svg viewBox="0 0 28 24"><rect x="1.5" y="6" width="22" height="12" rx="3.5"/><rect x="4" y="8.5" width="13" height="7" rx="1.6" class="fill"/><path d="M26 10v4"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M2 9a15 15 0 0 1 20 0M5.5 12.5a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0"/><circle cx="12" cy="19.5" r="1.2" class="fill"/></svg>' +
      '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></svg>' +
      '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="6" rx="3"/><rect x="3" y="13" width="18" height="6" rx="3"/><circle cx="16" cy="8" r="1.6" class="fill"/><circle cx="8" cy="16" r="1.6" class="fill"/></svg>' +
      '<span class="clock"></span></div>');
    menubar.style.height = `${L.menubar_h}px`;
    dom.clock = menubar.querySelector(".clock");

    for (const win of S.windows) buildWindow(win, camera, loads);
    buildTabs(loads);

    const d = L.dock;
    const dock = el("div", "dock", camera);
    DOCK_APPS.forEach((app, i) => {
      if (app.sep) {
        el("div", "sep", dock);
        return;
      }
      const a = el("div", `app${app.run ? " running" : ""}`, dock, app.svg + (app.badge ? `<span class="badge">${app.badge}</span>` : ""));
      Object.assign(a.style, { width: `${d.icon}px`, height: `${d.icon}px`, marginLeft: i ? `${d.gap}px` : "0" });
    });
    Object.assign(dock.style, { height: `${d.h}px`, top: `${d.y}px`, left: "0px" });
    dock.style.left = `${(W - dock.offsetWidth) / 2}px`;

    dom.camera = camera;
    dom.cursor = el("div", "", stage, '<svg viewBox="0 0 24 24"><path d="M5.5 2.8v16.6l4.1-3.9 2.7 6 2.9-1.3-2.7-5.9 5.6-.3Z"/></svg>');
    dom.cursor.id = "cursor";
    return Promise.all(loads);
  }

  // tabs live in their window's strip
  function buildTabs(loads) {
    for (const t of S.tabs) {
      const w = dom.windows[t.win];
      const html = S.skin
        ? `<span class="tbg"><img class="l" src="${skinUrl("tab_l")}"><span class="m" style="background-image:url('${skinUrl("tab_m")}')"></span><img class="r" src="${skinUrl("tab_r")}"></span>` +
          `<span class="clip"><span class="fav globe"></span><span class="title"></span></span><img class="x ximg" src="${skinUrl("tab_x")}">${ICON.x.replace('class="x"', 'class="xsvg"')}<span class="sep"></span>`
        : '<span class="clip"><span class="fav globe"></span><span class="title"></span></span>' + ICON.x + '<span class="sep"></span>';
      const root = el("div", `tab${S.skin ? " skin" : ""}`, w.strip, html);
      Object.assign(root.style, { top: `${L.tab.top}px`, height: `${S.skin ? 35 : L.tabstrip_h - L.tab.top}px`, display: "none" });
      dom.tabs[t.id] = { root, clip: root.querySelector(".clip"), fav: root.querySelector(".fav"), title: root.querySelector(".title"),
        x: root.querySelector(".x"), sep: root.querySelector(".sep"), favKey: null, win: t.win };
    }
    for (const page of Object.values(S.pages)) {
      if (page.favicon) {
        const pre = new Image();
        pre.src = ASSETS + page.favicon;
        loads.push(pre.decode().catch(() => {}));
      }
    }
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

  function setFav(tab, key) {
    if (key === tab.favKey) return;
    tab.favKey = key;
    let node;
    if (key === "spin") {
      node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      node.setAttribute("viewBox", "0 0 24 24");
      node.setAttribute("class", "spin");
      node.innerHTML = '<circle cx="12" cy="12" r="8"/>';
    } else if (key === "globe" || key === "newtab") {
      node = document.createElement("span");
      node.className = `fav ${key}`;
    } else {
      node = document.createElement("img");
      node.className = "fav";
      node.src = key;
    }
    tab.fav.replaceWith(node);
    tab.fav = node;
  }

  function drawOmnibox(w, active, shown, t, opened) {
    const typing = tr.typing.find((x) => x.tab === active && t >= x.t0 - 90 && t < x.enter);
    if (typing) {
      // one key at a time, at the human rhythm planned for this text
      let n = 0;
      if (typing.keys) {
        for (const k of typing.keys) if (t >= typing.t0 + k) n++;
      } else {
        n = t < typing.t0 ? 0 : Math.round(clamp((t - typing.t0) / (typing.t1 - typing.t0)) * typing.text.length);
      }
      const isSearch = typing.kind === "search";
      const typed = typing.text.slice(0, n);
      // Chrome completes a familiar address inline, shown selected, after the first keys
      const completion = !isSearch && n >= 2 ? typing.text.slice(n) : "";
      const caret = !completion && Math.floor(t / 530) % 2 === 0;
      w.omni.classList.add("focus");
      w.omni.classList.toggle("open", n > 0);
      w.omniLead.className = "chip";
      w.omniLead.innerHTML = ICON.search;
      w.omniText.innerHTML = `<span class="host">${esc(typed)}</span>${caret ? '<span class="caret"></span>' : ""}` +
        (completion ? `<span class="auto">${esc(completion)}</span>` : "");
      w.omniEnd.innerHTML = "";
      if (n > 0) {
        const full = typed + completion;
        w.suggest.innerHTML = isSearch
          ? `<div class="row sel">${ICON.search}<span>${esc(typed)}</span><span class="muted">– Search</span></div>` +
            `<div class="row">${ICON.search}<span>${esc(typed)} <span class="muted">near me</span></span></div>` +
            `<div class="row">${ICON.search}<span>${esc(typed)} <span class="muted">examples</span></span></div>`
          : `<div class="row sel">${ICON.globe}<span><b style="font-weight:600">${esc(typed)}</b>${esc(full.slice(typed.length))}</span></div>` +
            `<div class="row">${ICON.search}<span>${esc(typed)}</span><span class="muted">– Search</span></div>`;
      }
      return `T${n}${caret ? "|" : ""}${completion ? "c" : ""}`;
    }
    w.omni.classList.remove("focus", "open");
    const page = S.pages[shown.page];
    if (!page.url) {
      // a fresh tab or window: Chrome puts the caret in the address bar
      const caret = Math.floor(t / 530) % 2 === 0 && t - opened > 0 && active !== "t0";
      w.omniLead.className = "chip";
      w.omniLead.innerHTML = ICON.search;
      w.omniText.innerHTML = `${caret ? '<span class="caret"></span>' : ""}<span class="placeholder">Search or type a URL</span>`;
      if (caret) w.omni.classList.add("focus");
      w.omniEnd.innerHTML = ICON.lens;
      return `P${caret ? "|" : ""}`;
    }
    const u = splitUrl(page.url);
    w.omniLead.className = "chip site";
    w.omniLead.innerHTML = ICON.tune;
    w.omniText.innerHTML = `<span class="host">${esc(u.host)}</span><span class="rest">${esc(u.rest)}</span>`;
    w.omniEnd.innerHTML = ICON.star;
    return `U${shown.page}`;
  }

  function seek(t) {
    const cam = cameraAt(t);
    dom.camera.style.transform = `translate(${W / 2 - cam.cx * cam.z}px, ${H / 2 - cam.cy * cam.z}px) scale(${cam.z})`;
    const clock = dom.clock ? clockText(t) : "";
    if (dom.clock) dom.clock.textContent = clock;
    const sig = [cam.z.toFixed(4), cam.cx.toFixed(1), cam.cy.toFixed(1), clock];

    // window stacking: most recently focused on top
    const frontEvents = tr.front.filter((x) => x.t <= t);
    const front = frontEvents.length ? frontEvents[frontEvents.length - 1].id : "w0";
    const lastFocus = {};
    frontEvents.forEach((x, i) => (lastFocus[x.id] = i));
    const loads = tr.loading.filter((x) => t >= x.t0 && t < x.t1);
    const spin = Math.round(((t * 0.4) % 360) / 15) * 15;

    for (const win of S.windows) {
      const w = dom.windows[win.id];
      const openEv = tr.windows.find((x) => x.id === win.id);
      const isOpen = openEv && openEv.t <= t;
      w.root.style.display = isOpen ? "block" : "none";
      if (!isOpen) continue;
      const q = easeOutCubic(clamp((t - openEv.t) / WINDOW_OPEN_MS));
      w.root.style.zIndex = String(10 + (lastFocus[win.id] ?? 0));
      w.root.style.opacity = openEv.t > 0 ? q.toFixed(3) : "1";
      w.root.style.transform = openEv.t > 0 && q < 1 ? `scale(${(0.94 + 0.06 * q).toFixed(4)})` : "";
      w.root.classList.toggle("inactive", win.id !== front);

      // tabs of this window, sliding open left to right
      const tabsHere = tr.tabs.filter((x) => x.win === win.id && x.t <= t);
      const activeEv = lastAt(tr.active.filter((x) => x.win === win.id), t);
      const active = activeEv ? activeEv.id : tabsHere[0].id;
      let x = L.tab.left;
      tabsHere.forEach((ev, i) => {
        const tab = dom.tabs[ev.id];
        const grow = ev.t > 0 ? easeOutCubic(clamp((t - ev.t) / TAB_OPEN_MS)) : 1;
        const width = L.tab.w * grow;
        Object.assign(tab.root.style, { display: "flex", left: `${x}px`, width: `${width}px` });
        tab.clip.style.opacity = grow < 0.6 ? "0" : String((grow - 0.6) / 0.4);
        tab.x.style.opacity = grow < 0.9 ? "0" : "1";
        tab.root.classList.toggle("active", ev.id === active);
        const next = tabsHere[i + 1];
        tab.sep.style.display = ev.id !== active && (!next || next.id !== active) ? "block" : "none";
        const page = S.pages[pageOf(ev.id, t).page];
        tab.title.textContent = page.title || splitUrl(page.url).host || "New Tab";
        const loading = loads.some((l) => l.tab === ev.id);
        setFav(tab, loading ? "spin" : page.favicon ? ASSETS + page.favicon : page.status === "start" ? "newtab" : "globe");
        if (loading) tab.fav.style.transform = `rotate(${spin}deg)`;
        x += width + L.tab.gap;
        sig.push(`${ev.id}:${Math.round(width)}${ev.id === active ? "a" : ""}${loading ? `L${spin}` : ""}${pageOf(ev.id, t).page}`);
      });
      w.plus.style.left = w.skin ? `${x - L.tab.gap + 9}px` : `${x + 4}px`;

      const shown = pageOf(active, t);
      const scroll = scrollOf(active, shown, t);
      for (const [id, p] of Object.entries(w.pages)) p.root.classList.toggle("show", id === shown.page);
      const pageDom = w.pages[shown.page];
      if (pageDom && pageDom.img) pageDom.img.style.transform = `translateY(${-Math.round(scroll)}px)`;
      const history = (perTab[active] || []).filter((e) => e.t <= t).length;
      const activeLoading = loads.some((l) => l.tab === active);
      let omniSig;
      if (w.skin) {
        w.back.style.display = history >= 2 ? "flex" : "none";
        w.stop.style.display = activeLoading ? "flex" : "none";
        omniSig = drawOmniboxSkin(w, active, shown, t, win.id === front);
      } else {
        w.back.classList.toggle("dim", history < 2);
        w.reload.innerHTML = activeLoading ? ICON.stop : ICON.reload;
        const opened = (tabsHere.find((e) => e.id === active) || { t: 0 }).t;
        omniSig = win.id === front ? drawOmnibox(w, active, shown, t, opened) : drawOmnibox(w, active, shown, -1e9, opened);
      }
      sig.push(`${win.id}${win.id === front ? "*" : ""}${q.toFixed(3)}:${shown.page}:${Math.round(scroll)}:${omniSig}:${history}:${activeLoading}`);
    }

    // pointer, in screen space: always on screen, no click effects
    const c = cursorAt(t);
    const sx = (c.x - cam.cx) * cam.z + W / 2, sy = (c.y - cam.cy) * cam.z + H / 2;
    const vis = clamp((t - S.cursor.in) / 260) * clamp((S.cursor.out - t) / 260);
    dom.cursor.style.opacity = vis;
    dom.cursor.style.transform = `translate(${sx - 5.5}px, ${sy - 2.8}px)`;
    sig.push(sx.toFixed(1), sy.toFixed(1), vis.toFixed(2));
    return sig.join(",");
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
