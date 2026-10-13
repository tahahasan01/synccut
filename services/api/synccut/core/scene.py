"""Turn timed browser actions + captured pages into animation tracks for the stage.

Pure and deterministic. The stage (``synccut/stage/stage.js``) only interpolates
these tracks, so preview and render show exactly the same thing at time t.

It should read as a real screen recording: the pointer is always visible and
continuous (never teleports), the click lands before the state it causes, and
each result (page, tab, scroll) appears right as the narration says it, because
the travel, typing and loading are scheduled before the trigger word. The
optional camera push-in is off by default.
"""

from __future__ import annotations

from urllib.parse import urlparse

# A MacBook screen: macOS menu bar, the Dock, and a Chrome-style window in dark mode:
# tab strip (window controls, tab search, tabs, +), toolbar (back/forward/reload,
# omnibox, extensions, profile) and a bookmarks bar above the page.
STAGE_W, STAGE_H = 1920, 1080
MENUBAR_H = 26
WINDOW = {"x": 150, "y": 48, "w": 1620, "h": 924}
TABSTRIP_H, TOOLBAR_H, BOOKMARKS_H = 42, 44, 30
CHROME_H = TABSTRIP_H + TOOLBAR_H + BOOKMARKS_H
CONTENT = {"x": WINDOW["x"], "y": WINDOW["y"] + CHROME_H, "w": WINDOW["w"], "h": WINDOW["h"] - CHROME_H}
VIEW_W, VIEW_H = CONTENT["w"], CONTENT["h"]  # captured pages are rendered at exactly this size
ADDRESS = {"x": WINDOW["x"] + 122, "y": WINDOW["y"] + TABSTRIP_H + 5, "w": WINDOW["w"] - 122 - 360, "h": 34}
TABS_X, TAB_W, TAB_Y, TAB_H = WINDOW["x"] + 122, 236, WINDOW["y"] + 6, 36
TOOL_Y = WINDOW["y"] + TABSTRIP_H + TOOLBAR_H // 2
BACK_BTN = (WINDOW["x"] + 24, TOOL_Y)
DOCK = {"icon": 62, "h": 76, "y": STAGE_H - 76 - 5}

LAYOUT = {
    "stage": {"w": STAGE_W, "h": STAGE_H},
    "menubar_h": MENUBAR_H,
    "window": WINDOW,
    "tabstrip_h": TABSTRIP_H,
    "toolbar_h": TOOLBAR_H,
    "bookmarks_h": BOOKMARKS_H,
    "content": CONTENT,
    "address": ADDRESS,
    "tabs": {"x": TABS_X, "y": TAB_Y, "w": TAB_W, "h": TAB_H},
    "back": {"x": BACK_BTN[0], "y": BACK_BTN[1]},
    "dock": DOCK,
}

# Timing: the visible result of an action lands just after the word that triggers it,
# so the work (pointer travel, typing, loading) is scheduled *before* the word.
TRAVEL = 620     # pointer travel
PRESS = 90       # click
LOAD = 420       # navigation: the old page stays until the new one paints
LAND = 220       # result appears this long after the word starts
TYPE_PER_CHAR, TYPE_MIN, TYPE_MAX = 38, 280, 950
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


def _tab_point(index: int) -> tuple[float, float]:
    return TABS_X + index * (TAB_W + 4) + TAB_W / 2, TAB_Y + TAB_H / 2


def _plus_point(n_tabs: int) -> tuple[float, float]:
    return TABS_X + n_tabs * (TAB_W + 4) + 18, TAB_Y + TAB_H / 2  # Chrome: just after the last tab


def build_scene(
    actions: list[dict],
    capture: dict,
    duration_ms: float,
    *,
    camera: bool = False,
    fps: int = 30,
    clock_ms: float = 0,
    opening_url: str = "",
) -> dict:
    pages = {"start": {"id": "start", "url": "", "title": "New Tab", "image": None, "height": VIEW_H, "status": "start", "favicon": None}}
    for pid, page in capture.get("pages", {}).items():
        pages[pid] = {**page, "url": clean_url(page.get("url") or "")}
    results = capture.get("results", {})

    tracks: dict[str, list] = {
        "moves": [], "presses": [], "tabs": [{"t": 0, "id": "t0"}], "active": [{"t": 0, "id": "t0"}],
        "tab_page": [{"t": 0, "tab": "t0", "page": "start"}], "typing": [], "loading": [], "scroll": [], "camera": [],
    }
    tabs = [{"id": "t0", "page": "start", "scroll": 0.0, "history": ["start"]}]
    active = 0
    previous = 0
    cursor = (CONTENT["x"] + CONTENT["w"] * 0.6, CONTENT["y"] + CONTENT["h"] * 0.55)
    t_free = 0.0
    issues: list[dict] = []

    def move(t0: float, to: tuple[float, float], dur: float = TRAVEL) -> float:
        nonlocal cursor
        if abs(to[0] - cursor[0]) < 1 and abs(to[1] - cursor[1]) < 1:
            return t0
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

    omnibox_focused = None  # tab id whose omnibox already has focus (a new tab's does)

    def lead(ideal: float) -> tuple[float, float]:
        """Start no earlier than the previous action allows; return (start, how late)."""
        begin = max(ideal, t_free, 0.0)
        return begin, begin - max(ideal, 0.0)  # work that "would have" started before 0:00 isn't late

    for action in actions:
        r = results.get(action["id"], {})
        flags = list(r.get("flags", []))
        at = action["at_ms"]
        tab = tabs[active]
        kind = action["type"]
        end = at
        shift = 0.0

        opens_first = at <= 400 or (opening_url and action["url"] == opening_url)
        if kind == "navigate" and opens_first and not tracks["moves"] and r.get("page") and len(tabs) == 1 and tab["page"] == "start":
            # The recording opens on this page (e.g. the job post being replied to): already loaded.
            tracks["tab_page"][0] = {"t": 0, "tab": tab["id"], "page": r["page"]}
            tab.update(page=r["page"], scroll=0.0, history=[r["page"]])
            end = 0.0

        elif kind in ("navigate", "search"):
            text = typed_text(action)
            typing_ms = min(max(len(text) * TYPE_PER_CHAR, TYPE_MIN), TYPE_MAX)
            skip_click = omnibox_focused == tab["id"]
            # Back-schedule from the moment the page should appear.
            enter_ideal = at + LAND - LOAD
            click_ideal = enter_ideal - 110 - typing_ms - (0 if skip_click else 90)
            begin, shift = lead(click_ideal - (0 if skip_click else TRAVEL))
            point = (ADDRESS["x"] + ADDRESS["w"] * 0.55, ADDRESS["y"] + ADDRESS["h"] / 2)  # clear of the typed text
            if skip_click:
                click = begin
            else:
                shot(begin, CAMERA_ZOOM, (ADDRESS["x"] + ADDRESS["w"] / 2, ADDRESS["y"] + 170))
                click = max(move(begin, point), click_ideal)  # no travel needed: still wait for the moment
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
            t0 = click + (0 if skip_click else 90)
            t1 = t0 + typing_ms
            enter = t1 + 110
            loaded = enter + LOAD
            tracks["typing"].append({"t0": t0, "t1": t1, "enter": enter, "until": loaded, "tab": tab["id"],
                                     "text": text, "kind": kind})
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

        elif kind == "click":
            box = r.get("box")
            page_id = r.get("page")
            if box:
                y_top = box["y"] - tab["scroll"]
                needs_scroll = y_top < 40 or y_top + box["h"] > VIEW_H - 40
                scroll_ms = 650.0 if needs_scroll else 0.0
                begin, shift = lead(at - 90 - TRAVEL - scroll_ms)
                travel_at = begin
                if needs_scroll:
                    to = max(0.0, min(box["y"] - VIEW_H * 0.35, page_height(tab["page"]) - VIEW_H))
                    tracks["scroll"].append({"t0": begin, "t1": begin + scroll_ms, "tab": tab["id"], "page": tab["page"],
                                             "from": tab["scroll"], "to": to})
                    tab["scroll"] = to
                    travel_at = begin + scroll_ms
                point = (CONTENT["x"] + box["x"] + min(box["w"], 240) / 2, CONTENT["y"] + box["y"] - tab["scroll"] + box["h"] / 2)
                shot(travel_at, CAMERA_ZOOM, point)
                click = max(move(travel_at, point), at - 90)
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
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
                inside = (CONTENT["x"] + CONTENT["w"] * 0.62, CONTENT["y"] + CONTENT["h"] * 0.5)
                pointer_out = not (CONTENT["x"] <= cursor[0] <= CONTENT["x"] + CONTENT["w"]
                                   and CONTENT["y"] <= cursor[1] <= CONTENT["y"] + CONTENT["h"])
                begin, shift = lead(at - 80 - (450 if pointer_out else 0))
                start_scroll = move(begin, inside, 450) if pointer_out else begin
                distance = abs(to - tab["scroll"])
                dur = 650 + min(distance, 3000) / 3000 * 650  # a trackpad flick, then momentum
                if distance > 1:
                    tracks["scroll"].append({"t0": start_scroll, "t1": start_scroll + dur, "tab": tab["id"], "page": tab["page"],
                                             "from": tab["scroll"], "to": to})
                tab["scroll"] = to
                end = start_scroll + dur * 0.6  # the next action can start while momentum settles

        elif kind == "new_tab":
            point = _plus_point(len(tabs))
            begin, shift = lead(at - 90 - TRAVEL)
            click = max(move(begin, point), at - 90)
            tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
            new = {"id": f"t{len(tabs)}", "page": "start", "scroll": 0.0, "history": ["start"]}
            tabs.append(new)
            previous, active = active, len(tabs) - 1
            tracks["tabs"].append({"t": click + PRESS, "id": new["id"]})
            tracks["active"].append({"t": click + PRESS, "id": new["id"]})
            tracks["tab_page"].append({"t": click + PRESS, "tab": new["id"], "page": "start"})
            omnibox_focused = new["id"]  # Chrome focuses the address bar of a new tab
            end = click + PRESS + 120

        elif kind == "switch_tab":
            index = action.get("tab", 0)
            index = previous if index < 0 else index
            if not 0 <= index < len(tabs):
                flags.append("no_such_tab")
            elif index != active:
                point = _tab_point(index)
                begin, shift = lead(at - 90 - TRAVEL)
                click = max(move(begin, point), at - 90)
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
                previous, active = active, index
                omnibox_focused = None
                tracks["active"].append({"t": click + PRESS, "id": tabs[index]["id"]})
                end = click + PRESS + 120

        elif kind == "back":
            if len(tab["history"]) < 2:
                flags.append("nothing_to_go_back_to")
            else:
                point = BACK_BTN
                begin, shift = lead(at - 90 - TRAVEL)
                click = max(move(begin, point), at - 90)
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
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

    if tracks["camera"]:
        tracks["camera"].insert(0, {"t": 0, "zoom": 1.0, "fx": STAGE_W / 2, "fy": STAGE_H / 2})

    return {
        "version": 2,
        "fps": fps,
        "duration_ms": duration_ms,
        "layout": LAYOUT,
        "pages": pages,
        "tabs": [{"id": t["id"]} for t in tabs],
        "tracks": tracks,
        # A real screen recording: the pointer is on screen the whole time.
        "cursor": {"in": -1000, "out": duration_ms + 1000, "start": [CONTENT["x"] + CONTENT["w"] * 0.6, CONTENT["y"] + CONTENT["h"] * 0.55]},
        "clock_ms": clock_ms,
        "issues": issues,
        "results": {aid: {"page": r.get("page"), "link_text": r.get("link_text")} for aid, r in results.items()},
    }
