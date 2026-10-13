/* SyncCut stage: a generated browser window driven by a scene timeline.
 *
 * Everything on screen is a pure function of time: stage.seek(ms) draws the
 * exact state at that moment and returns a signature string, which the renderer
 * uses to reuse identical frames. Preview mode follows postMessage seeks from
 * the editor; render mode is driven by headless Chromium frame by frame.
 *
 * Cursor, press ripple and camera follow the interactive-product-demo skill:
 * continuous pointer, click before state, push-in on the acting control,
 * whole window on holds. Cursor path from that skill's template (MIT).
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
  // cubic-bezier(0.22, 1, 0.36, 1) from the skill, approximated by an ease-out quint
  const easeOut = (p) => 1 - Math.pow(1 - p, 5);
  const easeInOut = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
  const el = (tag, cls, parent, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html) n.innerHTML = html;
    if (parent) parent.appendChild(n);
    return n;
  };
  const prettyUrl = (u) => {
    if (!u) return "";
    try {
      const x = new URL(u);
      const path = x.pathname.replace(/\/$/, "");
      return x.host.replace(/^www\./, "") + path + (x.search || "");
    } catch {
      return u;
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

  let S, L, tr;
  const dom = { tabs: {}, pages: {} };
  let perTab = {};

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
    const w = L.window;

    // macOS desktop: menu bar + dock. Generic on purpose: no Apple logo, no real app icons.
    const menubar = el("div", "menubar", camera,
      '<div class="menus"><b>Browser</b><span>File</span><span>Edit</span><span>View</span><span>History</span><span>Bookmarks</span><span>Window</span><span>Help</span></div>' +
      '<div class="status"><svg viewBox="0 0 24 24"><path d="M2 9a15 15 0 0 1 20 0M5.5 12.5a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0"/><circle cx="12" cy="19.5" r="1.2"/></svg>' +
      '<svg viewBox="0 0 28 24"><rect x="1.5" y="6" width="22" height="12" rx="3.5"/><rect x="4" y="8.5" width="15" height="7" rx="1.6" class="fill"/><path d="M26 10v4"/></svg>' +
      '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></svg><span>Tue 9:41 AM</span></div>');
    menubar.style.height = `${L.menubar_h}px`;
    const dock = el("div", "dock", camera);
    Object.assign(dock.style, { width: `${L.dock.w}px`, height: `${L.dock.h}px`, top: `${L.dock.y}px`, left: `${(W - L.dock.w) / 2}px` });
    ["#5b8def,#2f5fd0", "#34d399,#059669", "#fbbf24,#f59e0b", "#f472b6,#db2777", "#a78bfa,#7c3aed", "#38bdf8,#0284c7", "#fb7185,#e11d48", "#94a3b8,#475569"]
      .forEach((g, i) => {
        const icon = el("i", i === 0 ? "running" : "", dock);
        icon.style.background = `linear-gradient(160deg, ${g})`;
      });

    const win = el("div", "window", camera);
    Object.assign(win.style, { left: `${w.x}px`, top: `${w.y}px`, width: `${w.w}px`, height: `${w.h}px` });

    const toolbar = el("div", "toolbar", win);
    toolbar.style.height = `${L.toolbar_h}px`;
    el("div", "lights", toolbar, "<i></i><i></i><i></i>");
    el("div", "nav", toolbar,
      '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg><svg viewBox="0 0 24 24" class="dim"><path d="M9 5l7 7-7 7"/></svg>');
    const a = L.address;
    dom.address = el("div", "address", toolbar);
    Object.assign(dom.address.style, { left: `${a.x - w.x}px`, top: `${a.y - w.y}px`, width: `${a.w}px`, height: `${a.h}px` });
    dom.addressText = el("div", "text", dom.address);
    dom.loading = el("div", "loading", dom.address);
    el("div", "tools", toolbar,
      '<svg viewBox="0 0 24 24"><path d="M12 3v12M7.5 7.5L12 3l4.5 4.5M6 12H5v9h14v-9h-1"/></svg>' +
      '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></svg>');

    const tabbar = el("div", "tabbar", win);
    Object.assign(tabbar.style, { top: `${L.toolbar_h}px`, height: `${L.tabbar_h}px` });
    scene.tabs.forEach((t, i) => {
      const tab = el("div", "tab", tabbar, '<span class="fav globe"></span><span class="title"></span><span class="x">×</span>');
      Object.assign(tab.style, { left: `${L.tabs.x - w.x + i * (L.tabs.w + 4)}px`, top: `${L.tabs.y - w.y - L.toolbar_h}px`, width: `${L.tabs.w}px`, height: `${L.tabs.h}px` });
      dom.tabs[t.id] = { root: tab, fav: tab.querySelector(".fav"), title: tab.querySelector(".title"), favSrc: null };
    });

    const content = el("div", "content", win);
    content.style.top = `${L.toolbar_h + L.tabbar_h}px`;
    const loads = [];
    for (const [id, page] of Object.entries(scene.pages)) {
      let root;
      if (page.status === "start") {
        root = el("div", "page start", content, '<div class="hello">New Tab</div><div class="box">Search or enter website name</div>');
      } else if (page.image) {
        root = el("div", "page", content);
        const img = el("img", "", root);
        img.alt = "";
        img.src = ASSETS + page.image;
        loads.push(img.decode().catch(() => {}));
        dom.pages[id] = { root, img };
      } else {
        root = el("div", "page placeholder-page", content,
          `<div class="card"><svg width="54" height="54" viewBox="0 0 24 24" fill="none" stroke="#8e8e93" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>` +
          `<b>${esc(prettyUrl(page.url).split("/")[0] || "Page")}</b><span>Preview not available</span></div>`);
      }
      dom.pages[id] = dom.pages[id] || { root };
      if (page.favicon) {
        const pre = new Image();
        pre.src = ASSETS + page.favicon;
        loads.push(pre.decode().catch(() => {}));
      }
    }

    dom.camera = camera;
    dom.cursor = el("div", "", stage,
      '<div class="flash"></div><div class="ring"></div><svg viewBox="0 0 24 24"><path d="M5.8 2.5v17.1l4.5-4.3 2.8 6 3-1.4-2.8-5.9 5.8-.4Z"/></svg>');
    dom.cursor.id = "cursor";
    dom.cursorSvg = dom.cursor.querySelector("svg");
    dom.flash = dom.cursor.querySelector(".flash");
    dom.ring = dom.cursor.querySelector(".ring");
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
    const m = lastAt(tr.moves, t, "t0");
    if (!m) return { x: S.cursor.start[0], y: S.cursor.start[1] };
    if (t >= m.t1) return { x: m.x1, y: m.y1 };
    const p = easeOut(clamp((t - m.t0) / (m.t1 - m.t0)));
    return { x: lerp(m.x0, m.x1, p), y: lerp(m.y0, m.y1, p) };
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
      y = t >= s.t1 ? s.to : lerp(s.from, s.to, easeInOut(clamp((t - s.t0) / (s.t1 - s.t0))));
    }
    return y;
  }

  function seek(t) {
    const cam = cameraAt(t);
    dom.camera.style.transform = `translate(${W / 2 - cam.cx * cam.z}px, ${H / 2 - cam.cy * cam.z}px) scale(${cam.z})`;

    const opened = tr.tabs.filter((x) => x.t <= t).map((x) => x.id);
    const active = (lastAt(tr.active, t) || { id: "t0" }).id;
    for (const [id, tab] of Object.entries(dom.tabs)) {
      const isOpen = opened.includes(id);
      tab.root.classList.toggle("open", isOpen);
      tab.root.classList.toggle("active", id === active);
      if (!isOpen) continue;
      const page = S.pages[pageOf(id, t).page];
      tab.title.textContent = page.title || prettyUrl(page.url) || "New Tab";
      const fav = page.favicon ? ASSETS + page.favicon : null;
      if (fav !== tab.favSrc) {
        tab.favSrc = fav;
        if (fav) {
          const img = document.createElement("img");
          img.className = "fav";
          img.src = fav;
          tab.fav.replaceWith(img);
          tab.fav = img;
        } else {
          const span = document.createElement("span");
          span.className = "fav globe";
          tab.fav.replaceWith(span);
          tab.fav = span;
        }
      }
    }
    const shown = pageOf(active, t);
    const scroll = scrollOf(active, shown, t);
    for (const [id, p] of Object.entries(dom.pages)) p.root.classList.toggle("show", id === shown.page);
    const pageDom = dom.pages[shown.page];
    if (pageDom && pageDom.img) pageDom.img.style.transform = `translateY(${-Math.round(scroll)}px)`;

    // address bar
    const typing = tr.typing.find((x) => x.tab === active && t >= x.t0 - 140 && t < x.until);
    let addressSig;
    if (typing) {
      const n = t < typing.t0 ? 0 : Math.round(clamp((t - typing.t0) / (typing.t1 - typing.t0)) * typing.text.length);
      const caret = t < typing.enter && Math.floor(t / 530) % 2 === 0;
      dom.address.classList.toggle("focus", t < typing.enter);
      dom.address.classList.add("typing");
      dom.addressText.innerHTML = `<span>${esc(typing.text.slice(0, n))}</span>${caret ? '<span class="caret"></span>' : ""}`;
      addressSig = `T${n}${caret ? "|" : ""}${t < typing.enter ? "f" : ""}`;
    } else {
      dom.address.classList.remove("focus", "typing");
      const page = S.pages[shown.page];
      if (!page.url) {
        dom.addressText.innerHTML = '<span class="placeholder">Search or enter website name</span>';
      } else {
        const secure = page.url.startsWith("https:");
        dom.addressText.innerHTML = (secure ? '<svg class="lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>' : "") +
          `<span>${esc(prettyUrl(page.url))}</span>`;
      }
      addressSig = `U${shown.page}`;
    }

    // loading bar
    const load = tr.loading.find((x) => x.tab === active && t >= x.t0 && t < x.t1 + 220);
    let loadP = -1;
    if (load) {
      loadP = t < load.t1 ? 0.15 + 0.75 * easeOut(clamp((t - load.t0) / (load.t1 - load.t0))) : 1;
      dom.loading.style.width = `${loadP * 100}%`;
      dom.loading.style.opacity = t < load.t1 ? 1 : 1 - (t - load.t1) / 220;
    } else {
      dom.loading.style.opacity = 0;
    }

    // cursor, in screen space
    const c = cursorAt(t);
    const sx = (c.x - cam.cx) * cam.z + W / 2, sy = (c.y - cam.cy) * cam.z + H / 2;
    const vis = clamp((t - S.cursor.in) / 260) * clamp((S.cursor.out - t) / 260);
    dom.cursor.style.opacity = vis;
    dom.cursor.style.transform = `translate(${sx - 7.2}px, ${sy - 3}px)`;
    const press = tr.presses.filter((x) => t >= x.t && t < x.t + 560).pop();
    let pressSig = "";
    if (press) {
      const dt = t - press.t;
      const down = dt < 190;
      dom.cursorSvg.style.transform = down ? "scale(0.8)" : "";
      const f = clamp(dt / 340), r = clamp(dt / 560);
      dom.flash.style.opacity = dt < 340 ? 0.9 * (1 - f) : 0;
      dom.flash.style.transform = `scale(${lerp(0.2, 1.25, easeOut(f))})`;
      dom.ring.style.opacity = r < 0.7 ? lerp(0.75, 0.25, r / 0.7) : lerp(0.25, 0, (r - 0.7) / 0.3);
      dom.ring.style.transform = `scale(${lerp(0.35, 2.1, easeOut(r))})`;
      pressSig = `P${Math.round(dt / 10)}`;
    } else {
      dom.cursorSvg.style.transform = "";
      dom.flash.style.opacity = 0;
      dom.ring.style.opacity = 0;
    }

    return [
      cam.z.toFixed(4), cam.cx.toFixed(1), cam.cy.toFixed(1), opened.length, active, shown.page, Math.round(scroll),
      addressSig, loadP.toFixed(3), sx.toFixed(1), sy.toFixed(1), vis.toFixed(2), pressSig,
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
