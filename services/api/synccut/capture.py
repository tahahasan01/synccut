"""Execute an action plan on real websites in headless Chromium and capture each page state.

Output (``capture.json``):
  pages   {page_id: {url, title, image, height, favicon, status, error?}}
  results {action_id: {page?, box?, scroll_to?, flags[]}}

Nothing is invented: a page that can't be loaded (login wall, bot check,
offline) becomes a neutral placeholder and the action is flagged.
"""

from __future__ import annotations

import difflib
import glob
import os
import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlparse

from .core.actions import content_key
from .core.scene import VIEW_H, VIEW_W

MAX_PAGE_H = 7000
BLOCKED = re.compile(r"/sorry/|captcha|unusual traffic|just a moment|access denied|attention required|verify you are human", re.I)
CONSENT_TEXT = re.compile(r"^(accept all|accept|i agree|agree|allow all|got it|ok|accept cookies|alle akzeptieren)$", re.I)


def chromium_executable() -> str | None:
    explicit = os.environ.get("SYNCCUT_CHROMIUM")
    if explicit:
        return explicit
    home = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    found = sorted(glob.glob(str(home / "chromium-*" / "chrome-win64" / "chrome.exe")), key=lambda p: int(re.findall(r"chromium-(\d+)", p)[0]))
    return found[-1] if found else None  # None → Playwright's own default


def search_urls(query: str, prefer_google: bool) -> list[tuple[str, str]]:
    q = quote_plus(query)
    bing = ("bing", f"https://www.bing.com/search?q={q}")
    google = ("google", f"https://www.google.com/search?q={q}&hl=en")
    return [google, bing] if prefer_google else [bing]


RESULT_SELECTORS = ["li.b_algo h2 a", "#search a:has(h3)", "a.result__a", "h3 a", "h2 a"]

LINKS_JS = """() => [...document.querySelectorAll('a[href], button, [role=button], [role=link]')]
  .map(el => { const r = el.getBoundingClientRect();
    return { text: (el.innerText || el.getAttribute('aria-label') || el.title || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
             href: el.href || '', x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }; })
  .filter(l => l.w > 4 && l.h > 4 && l.text && l.y < %d).slice(0, 400)""" % MAX_PAGE_H

CAPTURE_VERSION = 3

# "scroll to the history section" means the section, not the first word "history" on the
# page (often a nav link at the top): prefer headings, then matches below the first screen.
FIND_TEXT_JS = """([needle, viewH]) => {
  needle = needle.toLowerCase().replace(/\\s+(section|part|area|bit)$/, '');
  const top = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? r.top + scrollY : null; };
  const inChrome = (el) => !!el.closest('nav, header, footer, [role=navigation], [role=banner], [role=tablist], #mw-head, #p-views');
  for (const h of document.querySelectorAll('h1, h2, h3, h4, [role=heading]')) {
    if (!inChrome(h) && h.textContent.toLowerCase().includes(needle)) { const y = top(h); if (y !== null) return y; }
  }
  let fallback = null;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, p = n.parentElement;
    if (!p || /^(SCRIPT|STYLE|NOSCRIPT)$/.test(p.tagName) || !n.textContent.toLowerCase().includes(needle)) continue;
    const y = top(p);
    if (y === null) continue;
    if (inChrome(p)) continue;  // "View history" in a tab bar is not the history section
    if (y > viewH * 0.6) return y;
    if (fallback === null) fallback = y;  // already on screen: no scroll needed
  }
  return fallback;  // null → not on the page: scroll down and flag it
}"""


class Capturer:
    def __init__(self, out_dir: Path, progress: Callable[[float, str], None]):
        self.out_dir = out_dir
        self.progress = progress
        self.pages: dict[str, dict] = {}
        self.n = 0

    # page loading ---------------------------------------------------------------
    def _snapshot(self, live, page_id: str) -> dict:
        try:
            # Most pages are visually complete well before the network goes fully idle
            # (analytics, chat widgets keep it busy), so don't wait long for that.
            live.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass
        self._dismiss_consent(live)
        live.wait_for_timeout(350)
        title = (live.title() or "").strip()
        url = live.url
        if BLOCKED.search(url) or BLOCKED.search(title):
            return {"id": page_id, "url": url, "title": urlparse(url).netloc, "image": None, "height": VIEW_H,
                    "status": "blocked", "error": "The site showed a bot check, so it can't be captured.", "favicon": None}
        height = live.evaluate("() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)")
        height = int(min(max(height or VIEW_H, VIEW_H), MAX_PAGE_H))
        image = f"pages/{page_id}.jpg"
        live.screenshot(path=str(self.out_dir / f"{page_id}.jpg"), type="jpeg", quality=85, full_page=True,
                        clip={"x": 0, "y": 0, "width": VIEW_W, "height": height})
        return {"id": page_id, "url": url, "title": title or urlparse(url).netloc, "image": image, "height": height,
                "status": "ok", "favicon": self._favicon(live, page_id), "links": live.evaluate(LINKS_JS)}

    def _dismiss_consent(self, live) -> None:
        """Click a visible cookie-consent button if there is one, in a single round trip."""
        try:
            clicked = live.evaluate(
                """(pattern) => { const re = new RegExp(pattern, 'i');
                     for (const b of document.querySelectorAll('button, [role=button], input[type=button], input[type=submit]')) {
                       const t = (b.innerText || b.value || '').trim(); const r = b.getBoundingClientRect();
                       if (re.test(t) && r.width > 0 && r.height > 0) { b.click(); return true; } }
                     return false; }""",
                CONSENT_TEXT.pattern,
            )
            if clicked:
                live.wait_for_timeout(400)
        except Exception:
            pass

    def _favicon(self, live, page_id: str) -> str | None:
        try:
            href = live.evaluate("""() => { const l = document.querySelector('link[rel~="icon"], link[rel="shortcut icon"]');
                                       return l ? l.href : location.origin + '/favicon.ico'; }""")
            res = live.context.request.get(href, timeout=3000)
            ctype = res.headers.get("content-type", "")
            if not res.ok or not ctype.startswith("image"):
                return None
            ext = {"image/svg+xml": "svg", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(ctype.split(";")[0], "ico")
            path = self.out_dir / f"{page_id}.{ext}"
            path.write_bytes(res.body())
            return f"pages/{page_id}.{ext}"
        except Exception:
            return None

    def load(self, tab: dict, url: str) -> dict:
        self.n += 1
        page_id = f"p{self.n}"
        try:
            if tab["live"] is None:
                tab["live"] = tab["ctx"].new_page()
            tab["live"].goto(url, wait_until="domcontentloaded", timeout=25000)
            record = self._snapshot(tab["live"], page_id)
        except Exception as exc:
            record = {"id": page_id, "url": url, "title": urlparse(url).netloc or url, "image": None, "height": VIEW_H,
                      "status": "failed", "error": f"Couldn't load the page ({exc.__class__.__name__}).", "favicon": None}
        self.pages[page_id] = record
        return record


def _match_link(links: list[dict], target: str) -> dict | None:
    target = target.lower().strip()
    best, best_score = None, 0.0
    for link in links:
        text = link["text"].lower()
        score = difflib.SequenceMatcher(None, target, text[: max(len(target) * 2, 20)]).ratio()
        if target in text:
            score = max(score, 0.75 + 0.25 * len(target) / max(len(text), 1))
        if score > best_score:
            best, best_score = link, score
    return best if best_score >= 0.55 else None


def _result_link(live, ordinal: int) -> dict | None:
    for selector in RESULT_SELECTORS:
        try:
            boxes = live.evaluate("""([sel, n]) => { const els = [...document.querySelectorAll(sel)].map(e => e.closest('a') || e)
                      .filter(e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; });
                      const e = els[n]; if (!e) return null; const r = e.getBoundingClientRect();
                      return { text: e.innerText.trim().slice(0, 120), href: e.href || '', x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }; }""",
                                  [selector, ordinal])
            if boxes:
                return boxes
        except Exception:
            continue
    return None


def capture_actions(actions: list[dict], out_dir: Path, progress: Callable[[float, str], None]) -> dict:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    cap = Capturer(out_dir, progress)
    results: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_executable(), headless=True)
        ctx = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=1, locale="en-US")
        tabs = [{"ctx": ctx, "live": None, "history": ["start"], "scroll": 0.0}]
        active, previous = 0, 0
        try:
            for i, action in enumerate(actions):
                progress(i / max(len(actions), 1), f"Capturing step {i + 1} of {len(actions)}: {action['type']}")
                tab = tabs[active]
                r: dict = {"flags": [], "key": list(content_key(action))}
                kind = action["type"]
                current = cap.pages.get(tab["history"][-1])

                if kind == "navigate":
                    record = cap.load(tab, action["url"])
                    r["page"] = record["id"]
                elif kind == "search":
                    prefer_google = "google" in (action.get("spoken", "") + (current or {}).get("url", "")).lower()
                    for engine, url in search_urls(action["query"], prefer_google):
                        record = cap.load(tab, url)
                        if record["status"] == "ok":
                            break
                    r["page"] = record["id"]
                elif kind == "click":
                    if not current or current["status"] != "ok" or tab["live"] is None:
                        r["flags"].append("target_not_found")
                    else:
                        m = re.match(r"(first|second|third) result", action["target"].lower())
                        link = _result_link(tab["live"], ["first", "second", "third"].index(m.group(1))) if m else _match_link(current.get("links", []), action["target"])
                        if not link:
                            r["flags"].append("target_not_found")
                        else:
                            r["box"] = {k: round(link[k], 1) for k in ("x", "y", "w", "h")}
                            r["link_text"] = link["text"]
                            if link.get("href", "").startswith("http"):
                                record = cap.load(tab, link["href"])
                                r["page"] = record["id"]
                            else:
                                r["flags"].append("not_a_link")
                elif kind == "scroll":
                    height = (current or {}).get("height", VIEW_H)
                    target = action["target"].lower()
                    y = tab["scroll"]
                    if target == "down":
                        y += VIEW_H * 0.75
                    elif target == "up":
                        y -= VIEW_H * 0.75
                    elif target == "bottom":
                        y = height
                    elif target == "top":
                        y = 0
                    elif current and current["status"] == "ok" and tab["live"] is not None:
                        found = tab["live"].evaluate(FIND_TEXT_JS, [target, VIEW_H])
                        if found is None:
                            r["flags"].append("scroll_text_not_found")
                            y += VIEW_H * 0.75
                        else:
                            y = found - 140
                    else:
                        y += VIEW_H * 0.75
                    y = max(0.0, min(y, max(height - VIEW_H, 0)))
                    tab["scroll"] = y
                    r["scroll_to"] = round(y, 1)
                elif kind == "new_tab":
                    tabs.append({"ctx": ctx, "live": None, "history": ["start"], "scroll": 0.0})
                    previous, active = active, len(tabs) - 1
                elif kind == "switch_tab":
                    index = previous if action.get("tab", 0) < 0 else action.get("tab", 0)
                    if 0 <= index < len(tabs):
                        previous, active = active, index
                    else:
                        r["flags"].append("no_such_tab")
                elif kind == "back":
                    if len(tab["history"]) > 1:
                        tab["history"] = tab["history"][:-1]
                        prior = cap.pages.get(tab["history"][-1])
                        if prior and tab["live"] is not None and prior.get("url"):
                            try:
                                tab["live"].goto(prior["url"], wait_until="domcontentloaded", timeout=20000)
                            except Exception:
                                pass
                        tab["scroll"] = 0.0
                    r["page"] = tab["history"][-1]

                if r.get("page") and kind in ("navigate", "search", "click"):
                    tab["history"] = tab["history"] + [r["page"]]
                    tab["scroll"] = 0.0
                    status = cap.pages[r["page"]]["status"]
                    if status != "ok":
                        r["flags"].append("page_unavailable")
                results[action["id"]] = r
        finally:
            browser.close()

    for page in cap.pages.values():
        page.pop("links", None)
    progress(1.0, "Pages captured")
    return {"pages": cap.pages, "results": results, "order": [a["id"] for a in actions], "viewport": [VIEW_W, VIEW_H],
            "version": CAPTURE_VERSION}


def capture_is_current(capture: dict | None, actions: list[dict]) -> bool:
    """A capture stays valid while every action's content is unchanged; timing edits don't matter."""
    if not capture or capture.get("order") != [a["id"] for a in actions]:
        return False  # capture runs the plan in order, so a reorder needs a fresh run
    if capture.get("viewport") != [VIEW_W, VIEW_H] or capture.get("version") != CAPTURE_VERSION:
        return False  # the browser window layout changed; pages must match its viewport
    results = capture.get("results", {})
    return all(a["id"] in results and results[a["id"]].get("key") == list(content_key(a)) for a in actions) and len(results) == len(actions)
