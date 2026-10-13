"""Turn timed browser actions + captured pages into animation tracks for the stage.

Pure and deterministic. The stage (``synccut/stage/stage.js``) only interpolates
these tracks, so preview and render show exactly the same thing at time t.

It should read as a real screen recording: the pointer is always visible and
continuous (never teleports), the click lands before the state it causes, and
each result (page, tab, window, scroll) appears right as the narration says it,
because the travel, typing and loading are scheduled before the trigger word.
The optional camera push-in is off by default.
"""

from __future__ import annotations

import hashlib
import math
from urllib.parse import urlparse

# A MacBook screen: macOS menu bar, the Dock, and Chrome windows in dark mode. Sizes
# follow Chrome on macOS: tab strip (window controls, tab search, tabs, +), toolbar
# (back/forward/reload, omnibox, extensions, profile) and the bookmarks bar.
# The window rectangle and every bar height are measured from a real macOS Chrome
# screenshot (see skin.py), so a skin cut from that screenshot lines up 1:1.
STAGE_W, STAGE_H = 1920, 1080
MENUBAR_H = 24
WINDOW = {"x": 293, "y": 91, "w": 1272, "h": 862}
TABSTRIP_H, TOOLBAR_H, BOOKMARKS_H = 39, 42, 40  # bookmarks bar includes its 1 px divider
CHROME_H = TABSTRIP_H + TOOLBAR_H + BOOKMARKS_H
CONTENT_INSET = 1  # the window's 1 px border
VIEW_W, VIEW_H = WINDOW["w"] - 2 * CONTENT_INSET, WINDOW["h"] - CHROME_H  # captured pages are rendered at exactly this size
TAB_LEFT, TAB_W, TAB_TOP, TAB_GAP = 126, 232, 5, 1  # within the window; TAB_LEFT/W are the tab body
OMNI_LEFT, OMNI_W, OMNI_TOP, OMNI_H = 118, 622, 43, 38
OMNI_RIGHT = WINDOW["w"] - OMNI_LEFT - OMNI_W
DOCK = {"icon": 56, "gap": 12, "h": 76, "y": STAGE_H - 76 - 4}
# A second or third window opens offset from the first, like macOS cascades them
# (kept clear of the Dock).
WINDOW_OFFSETS = [(0, 0), (-46, 22), (46, 32)]
MAX_WINDOWS = len(WINDOW_OFFSETS)


def window_rect(index: int) -> dict:
    dx, dy = WINDOW_OFFSETS[min(index, MAX_WINDOWS - 1)]
    return {"x": WINDOW["x"] + dx, "y": WINDOW["y"] + dy, "w": WINDOW["w"], "h": WINDOW["h"]}


def geometry(index: int) -> dict:
    """Clickable places in window `index`, in stage pixels."""
    w = window_rect(index)
    return {
        "window": w,
        "content": {"x": w["x"] + CONTENT_INSET, "y": w["y"] + CHROME_H, "w": VIEW_W, "h": VIEW_H},
        "address": {"x": w["x"] + OMNI_LEFT, "y": w["y"] + OMNI_TOP, "w": OMNI_W, "h": OMNI_H},
        "tab_y": w["y"] + 19,
        "tabs_x": w["x"] + TAB_LEFT,
        "back": (w["x"] + 23, w["y"] + 62),
    }


G0 = geometry(0)
CONTENT, ADDRESS = G0["content"], G0["address"]

LAYOUT = {
    "stage": {"w": STAGE_W, "h": STAGE_H},
    "menubar_h": MENUBAR_H,
    "window": WINDOW,
    "window_offsets": WINDOW_OFFSETS,
    "tabstrip_h": TABSTRIP_H,
    "toolbar_h": TOOLBAR_H,
    "bookmarks_h": BOOKMARKS_H,
    "tab": {"left": TAB_LEFT, "w": TAB_W, "top": TAB_TOP, "gap": TAB_GAP},
    "omnibox": {"left": OMNI_LEFT, "right": OMNI_RIGHT, "w": OMNI_W, "top": OMNI_TOP, "h": OMNI_H},
    "content_inset": CONTENT_INSET,
    "dock": DOCK,
}

# Timing: the visible result of an action lands just after the word that triggers it,
# so the work (pointer travel, typing, loading) is scheduled *before* the word.
# Every duration is human-paced: a person reading their own script, not a bot.
TRAVEL = 620     # a typical pointer move (actual moves scale with distance, see travel_ms)
DWELL = 110      # the pointer settles on its target before the click
PRESS = 90       # click
LOAD = 420       # navigation: the old page stays until the new one paints
LAND = 220       # result appears this long after the word starts
KEY_MS = 135     # average gap between keystrokes, about 75 words a minute
KEY_MS_FAST = 88  # a quick typist (~130 wpm): the fastest we type when the next line is close
REACT = 350      # a beat before typing into a tab or window that just opened
AUTOCOMPLETE_PAUSE = 260  # glance at Chrome's inline suggestion, then press Enter
CAMERA_ZOOM = 1.12
LATE_FLAG_MS = 1500


TRACKING_PARAMS = {"rdr", "rdrig", "form", "sei", "ved", "ei", "sa", "gs_lcrp", "sourceid", "ie", "oq", "aqs", "fbclid", "gclid"}


def clean_url(url: str) -> str:
    """Drop tracking parameters so the address bar shows what a person would type."""
    p = urlparse(url)
    if not p.query:
        return url
    kept = [kv for kv in p.query.split("&") if kv.split("=")[0] not in TRACKING_PARAMS and not kv.startswith("utm_")]
    return p._replace(query="&".join(kept)).geturl()


def pretty_url(url: str) -> str:
    if not url:
        return ""
    p = urlparse(clean_url(url))
    path = p.path.rstrip("/")
    query = f"?{p.query}" if p.query else ""
    return f"{p.netloc.removeprefix('www.')}{path}{query}"


def typed_text(action: dict) -> str:
    if action["type"] == "search":
        return action["query"]
    return pretty_url(action["url"])


def travel_ms(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Longer pointer moves take longer (roughly Fitts's law), within human limits."""
    return min(max(360 + math.dist(a, b) * 0.3, 420.0), 980.0)


def keystrokes(text: str, seed: str = "") -> list[float]:
    """Time of each key from the first one: an uneven human rhythm, but deterministic."""
    out: list[float] = []
    t = 0.0
    for i, ch in enumerate(text):
        if i:
            h = int(hashlib.md5(f"{seed}|{text}|{i}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
            gap = KEY_MS * (0.65 + 0.7 * h)
            if text[i - 1] == " ":
                gap += 90 + 150 * h  # thinking of the next word
            if ch.isupper():
                gap += 45  # shift
            if ch in "./-:":
                gap += 40
            t += gap
        out.append(round(t, 1))
    return out


def autocomplete_keys(text: str) -> int:
    """People type the start of a familiar address and let Chrome complete it."""
    host = text.split("/")[0]
    return min(len(text), max(3, min(7, round(len(host) * 0.45))))


def _inside(point: tuple[float, float], rect: dict) -> bool:
    return rect["x"] <= point[0] <= rect["x"] + rect["w"] and rect["y"] <= point[1] <= rect["y"] + rect["h"]


def _visible_point(target: dict, covering: list[dict]) -> tuple[float, float]:
    """A spot on window `target` (its title/tab strip first) that no window in front covers."""
    candidates = [(target["x"] + target["w"] - k, target["y"] + 14) for k in range(60, target["w"] - 200, 120)]
    candidates += [(target["x"] + 18, target["y"] + target["h"] * f) for f in (0.3, 0.5, 0.7)]
    candidates += [(target["x"] + target["w"] - 18, target["y"] + target["h"] * f) for f in (0.3, 0.5, 0.7)]
    candidates += [(target["x"] + target["w"] * f, target["y"] + target["h"] - 12) for f in (0.3, 0.5, 0.7)]
    for c in candidates:
        if not any(_inside(c, r) for r in covering):
            return c
    return candidates[0]


def build_scene(
    actions: list[dict],
    capture: dict,
    duration_ms: float,
    *,
    camera: bool = False,
    fps: int = 30,
    clock_ms: float = 0,
    opening_url: str = "",
    skin: dict | None = None,
) -> dict:
    pages = {"start": {"id": "start", "url": "", "title": "New Tab", "image": None, "height": VIEW_H, "status": "start", "favicon": None}}
    for pid, page in capture.get("pages", {}).items():
        pages[pid] = {**page, "url": clean_url(page.get("url") or "")}
    results = capture.get("results", {})

    tracks: dict[str, list] = {
        "moves": [], "presses": [],
        "windows": [{"t": 0, "id": "w0"}],          # window opened
        "front": [{"t": 0, "id": "w0"}],            # frontmost (focused) window
        "tabs": [{"t": 0, "id": "t0", "win": "w0"}],  # tab opened, in which window
        "active": [{"t": 0, "id": "t0", "win": "w0"}],  # active tab of a window
        "tab_page": [{"t": 0, "tab": "t0", "page": "start"}], "typing": [], "loading": [], "scroll": [], "camera": [],
    }
    windows = [{"id": "w0", "index": 0, "tabs": [], "active": 0, "previous": 0}]
    tabs: list[dict] = []

    def new_tab(win: dict) -> dict:
        tab = {"id": f"t{len(tabs)}", "win": win["id"], "page": "start", "scroll": 0.0, "history": ["start"]}
        tabs.append(tab)
        win["tabs"].append(tab)
        return tab

    new_tab(windows[0])
    front, previous_window = 0, 0
    cursor = (CONTENT["x"] + CONTENT["w"] * 0.6, CONTENT["y"] + CONTENT["h"] * 0.55)
    t_free = 0.0   # when the pointer and page are free again
    t_soft = 0.0   # when the pointer is free (a page may still be loading): enough to switch tab or window
    issues: list[dict] = []
    omnibox_focused = None  # tab id whose omnibox already has focus (a new tab's does)

    def move(t0: float, to: tuple[float, float], dur: float | None = None) -> float:
        nonlocal cursor
        if abs(to[0] - cursor[0]) < 1 and abs(to[1] - cursor[1]) < 1:
            return t0
        dur = travel_ms(cursor, to) if dur is None else dur
        tracks["moves"].append({"t0": t0, "t1": t0 + dur, "x0": cursor[0], "y0": cursor[1], "x1": to[0], "y1": to[1]})
        cursor = to
        return t0 + dur

    def shot(t: float, zoom: float, focus: tuple[float, float] | None = None) -> None:
        if not camera:
            return
        fx, fy = focus or (STAGE_W / 2, STAGE_H / 2)
        tracks["camera"].append({"t": t, "zoom": zoom, "fx": fx, "fy": fy})

    def show(t: float, tab: dict, page_id: str) -> None:
        tab["page"] = page_id
        tab["scroll"] = 0.0
        tracks["tab_page"].append({"t": t, "tab": tab["id"], "page": page_id})

    def page_height(page_id: str) -> float:
        return float(pages.get(page_id, {}).get("height") or VIEW_H)

    def lead(ideal: float, soft: bool = False) -> tuple[float, float]:
        """Start no earlier than the previous action allows; return (start, how late)."""
        begin = max(ideal, t_soft if soft else t_free, 0.0)
        return begin, begin - max(ideal, 0.0)  # work that "would have" started before 0:00 isn't late

    def tab_point(g: dict, index: int) -> tuple[float, float]:
        return g["tabs_x"] + index * (TAB_W + TAB_GAP) + TAB_W / 2, g["tab_y"]

    def plus_point(g: dict, n_tabs: int) -> tuple[float, float]:
        return g["tabs_x"] + n_tabs * (TAB_W + TAB_GAP) + 20, g["tab_y"]  # Chrome: just after the last tab

    def press(t: float, point: tuple[float, float]) -> None:
        tracks["presses"].append({"t": t, "x": point[0], "y": point[1]})

    for i_action, action in enumerate(actions):
        r = results.get(action["id"], {})
        next_at = actions[i_action + 1]["at_ms"] if i_action + 1 < len(actions) else None
        flags = list(r.get("flags", []))
        at = action["at_ms"]
        win = windows[front]
        g = geometry(win["index"])
        content = g["content"]
        tab = win["tabs"][win["active"]]
        kind = action["type"]
        end = at
        end_soft = None
        shift = 0.0

        opens_first = at <= 400 or (opening_url and action["url"] == opening_url)
        if (kind == "navigate" and opens_first and not tracks["moves"] and r.get("page") and len(tabs) == 1
                and tab["page"] == "start"):
            # The recording opens on this page (e.g. the job post being replied to): already loaded.
            tracks["tab_page"][0] = {"t": 0, "tab": tab["id"], "page": r["page"]}
            tab.update(page=r["page"], scroll=0.0, history=[r["page"]])
            end = 0.0

        elif kind in ("navigate", "search"):
            text = typed_text(action)
            n_keys = len(text) if kind == "search" else autocomplete_keys(text)
            keys = keystrokes(text[:n_keys], action["id"])
            if kind == "search" and next_at is not None and len(keys) > 1:
                # Type a little faster when the next line comes soon, never faster than a quick typist.
                room = next_at - 700 - (at - 150) - 180
                if 0 < room < keys[-1]:
                    factor = max(room / keys[-1], KEY_MS_FAST / (keys[-1] / (len(keys) - 1)))
                    keys = [round(k * factor, 1) for k in keys] if factor < 1 else keys
            typing_ms = keys[-1] if keys else 0.0
            pause = AUTOCOMPLETE_PAUSE if n_keys < len(text) else 180.0
            skip_click = omnibox_focused == tab["id"]
            a = g["address"]
            point = (a["x"] + a["w"] * 0.55, a["y"] + a["h"] / 2)  # clear of the typed text
            if kind == "search":
                t0_ideal = at - 150  # a query is typed while it's being said
            else:
                t0_ideal = at + LAND - LOAD - pause - typing_ms  # the page lands just after the word
            click_ideal = t0_ideal - (REACT if skip_click else 90)
            begin, shift = lead(click_ideal - (0 if skip_click else travel_ms(cursor, point) + DWELL))
            if skip_click:
                click = begin
            else:
                shot(begin, CAMERA_ZOOM, (a["x"] + a["w"] / 2, a["y"] + 170))
                click = max(move(begin, point) + DWELL, click_ideal)
                press(click, point)
            t0 = click + (REACT if skip_click else 90)
            t1 = t0 + typing_ms
            enter = t1 + pause
            loaded = enter + LOAD
            tracks["typing"].append({"t0": t0, "t1": t1, "enter": enter, "until": loaded, "tab": tab["id"],
                                     "text": text, "kind": kind, "keys": keys, "typed": n_keys})
            tracks["loading"].append({"t0": enter, "t1": loaded, "tab": tab["id"]})
            page_id = r.get("page")
            if page_id:
                show(loaded, tab, page_id)
                tab["history"] = tab["history"] + [page_id]
            else:
                flags.append("not_captured")
            shot(loaded, 1.0)
            omnibox_focused = None
            end = loaded + 150
            end_soft = enter + 120  # the hand can move on while the page loads

        elif kind == "click":
            box = r.get("box")
            page_id = r.get("page")
            if box:
                y_top = box["y"] - tab["scroll"]
                needs_scroll = y_top < 40 or y_top + box["h"] > VIEW_H - 40
                scroll_ms = 750.0 if needs_scroll else 0.0
                to = max(0.0, min(box["y"] - VIEW_H * 0.35, page_height(tab["page"]) - VIEW_H)) if needs_scroll else tab["scroll"]
                point = (content["x"] + box["x"] + min(box["w"], 240) / 2, content["y"] + box["y"] - to + box["h"] / 2)
                begin, shift = lead(at - 90 - DWELL - travel_ms(cursor, point) - scroll_ms)
                travel_at = begin
                if needs_scroll:
                    tracks["scroll"].append({"t0": begin, "t1": begin + scroll_ms, "tab": tab["id"], "page": tab["page"],
                                             "from": tab["scroll"], "to": to})
                    tab["scroll"] = to
                    travel_at = begin + scroll_ms
                shot(travel_at, CAMERA_ZOOM, point)
                click = max(move(travel_at, point) + DWELL, at - 90)
                press(click, point)
                end = click + PRESS
                if page_id:
                    loaded = click + PRESS + LOAD
                    tracks["loading"].append({"t0": click + PRESS, "t1": loaded, "tab": tab["id"]})
                    show(loaded, tab, page_id)
                    tab["history"] = tab["history"] + [page_id]
                    end = loaded + 150
                shot(end, 1.0)
            else:
                flags.append("target_not_found")

        elif kind == "scroll":
            to = r.get("scroll_to")
            if to is None:
                flags.append("not_captured")
            else:
                to = max(0.0, min(float(to), max(page_height(tab["page"]) - VIEW_H, 0.0)))
                inside = (content["x"] + content["w"] * 0.62, content["y"] + content["h"] * 0.5)
                begin, shift = lead(at - 80 - (0 if _inside(cursor, content) else 500))
                start_scroll = begin if _inside(cursor, content) else move(begin, inside, 500)
                distance = abs(to - tab["scroll"])
                dur = 800 + min(distance, 3000) / 3000 * 900  # a trackpad swipe or two, then momentum
                if distance > 1:
                    tracks["scroll"].append({"t0": start_scroll, "t1": start_scroll + dur, "tab": tab["id"], "page": tab["page"],
                                             "from": tab["scroll"], "to": to})
                tab["scroll"] = to
                end = start_scroll + dur * 0.6  # the next action can start while momentum settles

        elif kind == "new_tab":
            point = plus_point(g, len(win["tabs"]))
            begin, shift = lead(at - 90 - DWELL - travel_ms(cursor, point), soft=True)
            click = max(move(begin, point) + DWELL, at - 90)
            press(click, point)
            t = new_tab(win)
            win["previous"], win["active"] = win["active"], len(win["tabs"]) - 1
            tracks["tabs"].append({"t": click + PRESS, "id": t["id"], "win": win["id"]})
            tracks["active"].append({"t": click + PRESS, "id": t["id"], "win": win["id"]})
            tracks["tab_page"].append({"t": click + PRESS, "tab": t["id"], "page": "start"})
            omnibox_focused = t["id"]  # Chrome focuses the address bar of a new tab
            end = click + PRESS + 120

        elif kind == "switch_tab":
            index = action.get("tab", 0)
            index = win["previous"] if index < 0 else index
            if not 0 <= index < len(win["tabs"]):
                flags.append("no_such_tab")
            elif index != win["active"]:
                point = tab_point(g, index)
                begin, shift = lead(at - 90 - DWELL - travel_ms(cursor, point), soft=True)
                click = max(move(begin, point) + DWELL, at - 90)
                press(click, point)
                win["previous"], win["active"] = win["active"], index
                omnibox_focused = None
                tracks["active"].append({"t": click + PRESS, "id": win["tabs"][index]["id"], "win": win["id"]})
                end = click + PRESS + 120

        elif kind == "new_window":
            if len(windows) >= MAX_WINDOWS:
                flags.append("too_many_windows")
            else:
                # ⌘N: no pointer travel; the window opens on a New Tab with the address bar focused.
                begin, shift = lead(at - 120, soft=True)
                nw = {"id": f"w{len(windows)}", "index": len(windows), "tabs": [], "active": 0, "previous": 0}
                windows.append(nw)
                t = new_tab(nw)
                opened = begin + 120
                tracks["windows"].append({"t": opened, "id": nw["id"]})
                tracks["front"].append({"t": opened, "id": nw["id"]})
                tracks["tabs"].append({"t": opened, "id": t["id"], "win": nw["id"]})
                tracks["active"].append({"t": opened, "id": t["id"], "win": nw["id"]})
                tracks["tab_page"].append({"t": opened, "tab": t["id"], "page": "start"})
                previous_window, front = front, nw["index"]
                omnibox_focused = t["id"]
                end = opened + 260  # the window's open animation

        elif kind == "switch_window":
            index = action.get("tab", 0)
            index = previous_window if index < 0 else index
            if not 0 <= index < len(windows):
                flags.append("no_such_window")
            elif index != front:
                covering = [window_rect(w["index"]) for w in windows if w["index"] == front]
                point = _visible_point(window_rect(index), covering)
                begin, shift = lead(at - 90 - DWELL - travel_ms(cursor, point), soft=True)
                click = max(move(begin, point) + DWELL, at - 90)
                press(click, point)
                previous_window, front = front, index
                omnibox_focused = None
                tracks["front"].append({"t": click + PRESS, "id": windows[index]["id"]})
                end = click + PRESS + 120

        elif kind == "back":
            if len(tab["history"]) < 2:
                flags.append("nothing_to_go_back_to")
            else:
                point = g["back"]
                begin, shift = lead(at - 90 - DWELL - travel_ms(cursor, point))
                click = max(move(begin, point) + DWELL, at - 90)
                press(click, point)
                tab["history"] = tab["history"][:-1]
                loaded = click + PRESS + 280  # back is served from cache
                tracks["loading"].append({"t0": click + PRESS, "t1": loaded, "tab": tab["id"]})
                show(loaded, tab, tab["history"][-1])
                end = loaded + 120

        if shift > LATE_FLAG_MS:
            flags.append("late")
        if action.get("source") == "rules":
            flags.append("rules_guess")
        if flags:
            issues.append({"action_id": action["id"], "flags": sorted(set(flags)), "late_ms": round(max(shift, 0))})
        t_free = max(t_free, end)
        t_soft = max(t_soft, end if end_soft is None else end_soft)

    if tracks["camera"]:
        tracks["camera"].insert(0, {"t": 0, "zoom": 1.0, "fx": STAGE_W / 2, "fy": STAGE_H / 2})

    return {
        "version": 3,
        "fps": fps,
        "duration_ms": duration_ms,
        "layout": LAYOUT,
        "pages": pages,
        "windows": [{"id": w["id"], "index": w["index"], "rect": window_rect(w["index"])} for w in windows],
        "tabs": [{"id": t["id"], "win": t["win"]} for t in tabs],
        "tracks": tracks,
        # A real screen recording: the pointer is on screen the whole time.
        "cursor": {"in": -1000, "out": duration_ms + 1000, "start": [CONTENT["x"] + CONTENT["w"] * 0.6, CONTENT["y"] + CONTENT["h"] * 0.55]},
        "clock_ms": clock_ms,
        # A look cut from the user's own screenshot (skin.py), or None for the drawn one.
        "skin": {"url": skin["url"], "version": skin["version"], "colors": skin["colors"]} if skin else None,
        "issues": issues,
        "results": {aid: {"page": r.get("page"), "link_text": r.get("link_text")} for aid, r in results.items()},
    }
