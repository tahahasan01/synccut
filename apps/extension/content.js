// Runs on browsed pages. Sends click / submit / scroll / typing events to the
// extension only while a SyncCut take is recording. Typed values are masked
// unless the field is a search box, and never sent for passwords or payment fields.

(() => {
  let recording = false;
  chrome.storage.local.get("recording").then(({ recording: r }) => (recording = Boolean(r)));
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.recording) recording = Boolean(changes.recording.newValue);
  });

  const now = () => performance.timeOrigin + performance.now();
  const send = (event) => {
    if (!recording) return;
    chrome.runtime.sendMessage({ kind: "page-event", event: { epoch_ms: now(), ...event } }).catch(() => {});
  };

  const SENSITIVE = /pass|pwd|card|cc-|cvv|cvc|otp|one-time|ssn|iban|account.?num|routing|pin\b/i;
  const SEARCH_NAMES = new Set(["q", "query", "search", "s", "keywords", "k"]);

  function isSensitive(el) {
    if (el.type === "password") return true;
    const hay = [el.name, el.id, el.autocomplete, el.getAttribute?.("aria-label"), el.placeholder].join(" ");
    return SENSITIVE.test(hay);
  }

  function isSearch(el) {
    return el.type === "search" || el.getAttribute?.("role") === "searchbox" || SEARCH_NAMES.has((el.name || "").toLowerCase());
  }

  function describe(el) {
    const rect = el.getBoundingClientRect();
    const role = el.getAttribute("role") || el.tagName.toLowerCase();
    let name = el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("placeholder") || "";
    if (!name && !(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
      name = (el.innerText || "").trim().replace(/\s+/g, " ");
    }
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
    return {
      role,
      name: name.slice(0, 100),
      selector: el.tagName.toLowerCase() + (el.id ? `#${el.id}` : cls ? `.${cls}` : ""),
      bbox: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)],
    };
  }

  function clickable(target) {
    return target.closest?.("a,button,[role=button],[role=link],[role=tab],[role=menuitem],input,select,summary,label") || target;
  }

  document.addEventListener("click", (e) => {
    if (e.target instanceof Element) send({ type: "click", target: describe(clickable(e.target)) });
  }, true);

  document.addEventListener("submit", (e) => {
    if (e.target instanceof Element) send({ type: "submit", target: describe(e.target) });
  }, true);

  const typing = new WeakMap();
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
    clearTimeout(typing.get(el));
    typing.set(el, setTimeout(() => {
      const value = el.value || "";
      const event = { type: "input", target: describe(el), length: value.length };
      if (!isSensitive(el) && isSearch(el)) event.value = value.slice(0, 120);
      send(event);
    }, 800));
  }, true);

  // At most one scroll event per second while scrolling, plus one when it settles,
  // so the final resting position is always recorded.
  let lastScroll = 0;
  let settle;
  const scrollEvent = (phase) =>
    send({ type: "scroll", phase, y: Math.round(window.scrollY), page_height: document.documentElement.scrollHeight });
  window.addEventListener("scroll", () => {
    clearTimeout(settle);
    settle = setTimeout(() => scrollEvent("end"), 400);
    const t = now();
    if (t - lastScroll < 1000) return;
    lastScroll = t;
    scrollEvent("move");
  }, { passive: true, capture: true });
})();
