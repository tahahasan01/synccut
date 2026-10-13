"""Turn timed browser actions + captured pages into animation tracks for the stage.

Pure and deterministic. The stage (``synccut/stage/stage.js``) only interpolates
these tracks, so preview and render show exactly the same thing at time t.

Motion rules follow the interactive-product-demo skill: the click lands before
the state it causes, the cursor is continuous (never teleports), travel ~850 ms,
press ~190 ms, and the camera opens and closes on the whole window.
"""

from __future__ import annotations

from urllib.parse import urlparse

# macOS desktop: menu bar on top, dock at the bottom, and a Safari-style window with
# one unified toolbar (window controls, sidebar, back/forward, centred address field,
# share / new tab / tab overview) and the tab strip underneath.
STAGE_W, STAGE_H = 1920, 1080
MENUBAR_H = 30
WINDOW = {"x": 150, "y": 52, "w": 1620, "h": 950}
TOOLBAR_H, TABBAR_H = 52, 38
CONTENT = {"x": WINDOW["x"], "y": WINDOW["y"] + TOOLBAR_H + TABBAR_H, "w": WINDOW["w"], "h": WINDOW["h"] - TOOLBAR_H - TABBAR_H}
VIEW_W, VIEW_H = CONTENT["w"], CONTENT["h"]  # captured pages are rendered at exactly this size
ADDRESS = {"x": WINDOW["x"] + (WINDOW["w"] - 760) // 2, "y": WINDOW["y"] + 8, "w": 760, "h": 36}
TABS_X, TAB_W, TAB_Y, TAB_H = WINDOW["x"] + 8, 260, WINDOW["y"] + TOOLBAR_H + 3, 32
TOOL_Y = WINDOW["y"] + TOOLBAR_H // 2
BACK_BTN = (WINDOW["x"] + 140, TOOL_Y)
PLUS_BTN = (WINDOW["x"] + WINDOW["w"] - 88, TOOL_Y)
DOCK = {"w": 560, "h": 62, "y": STAGE_H - 62 - 10}

LAYOUT = {
    "stage": {"w": STAGE_W, "h": STAGE_H},
    "menubar_h": MENUBAR_H,
    "window": WINDOW,
    "tabbar_h": TABBAR_H,
    "toolbar_h": TOOLBAR_H,
    "content": CONTENT,
    "address": ADDRESS,
    "tabs": {"x": TABS_X, "y": TAB_Y, "w": TAB_W, "h": TAB_H},
    "back": {"x": BACK_BTN[0], "y": BACK_BTN[1]},
    "plus": {"x": PLUS_BTN[0], "y": PLUS_BTN[1]},
    "dock": DOCK,
}

TRAVEL = 850
PRESS = 190
LOAD = 650
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
    return PLUS_BTN  # Safari-style: "new tab" lives in the toolbar, not after the last tab


def build_scene(
    actions: list[dict],
    capture: dict,
    duration_ms: float,
    *,
    camera: bool = True,
    fps: int = 30,
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

    first_cursor = None
    for action in actions:
        r = results.get(action["id"], {})
        flags = list(r.get("flags", []))
        start = max(action["at_ms"], t_free)
        tab = tabs[active]
        kind = action["type"]
        end = start

        if kind in ("navigate", "search"):
            point = (ADDRESS["x"] + 90, ADDRESS["y"] + ADDRESS["h"] / 2)
            travel_from = max(t_free, start - TRAVEL)
            shot(travel_from, CAMERA_ZOOM, (ADDRESS["x"] + ADDRESS["w"] / 2, ADDRESS["y"] + 170))
            click = move(travel_from, point)
            first_cursor = first_cursor if first_cursor is not None else travel_from
            tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
            text = typed_text(action)
            t0 = click + 120
            t1 = t0 + min(max(len(text) * 55, 350), 1500)
            enter = t1 + 150
            loaded = enter + LOAD
            tracks["typing"].append({"t0": t0, "t1": t1, "enter": enter, "until": loaded, "tab": tab["id"], "text": text})
            tracks["loading"].append({"t0": enter, "t1": loaded, "tab": tab["id"]})
            page_id = r.get("page")
            if page_id:
                show(loaded, tab, page_id)
                tab["history"] = tab["history"] + [page_id]
            else:
                flags.append("not_captured")
            shot(loaded, 1.0)
            end = loaded + 250
            start = click

        elif kind == "click":
            box = r.get("box")
            page_id = r.get("page")
            if box:
                y_top = box["y"] - tab["scroll"]
                travel_at = start
                if y_top < 40 or y_top + box["h"] > VIEW_H - 40:
                    to = max(0.0, min(box["y"] - VIEW_H * 0.35, page_height(tab["page"]) - VIEW_H))
                    dur = 700.0
                    tracks["scroll"].append({"t0": start, "t1": start + dur, "tab": tab["id"], "page": tab["page"], "from": tab["scroll"], "to": to})
                    tab["scroll"] = to
                    travel_at = start + dur
                point = (CONTENT["x"] + box["x"] + min(box["w"], 240) / 2, CONTENT["y"] + box["y"] - tab["scroll"] + box["h"] / 2)
                shot(travel_at, CAMERA_ZOOM, point)
                click = move(travel_at, point)
                first_cursor = first_cursor if first_cursor is not None else travel_at
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
                end = click + PRESS
                if page_id:
                    loaded = click + PRESS + LOAD
                    tracks["loading"].append({"t0": click + PRESS, "t1": loaded, "tab": tab["id"]})
                    show(loaded, tab, page_id)
                    tab["history"] = tab["history"] + [page_id]
                    end = loaded + 250
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
                at = start
                if not (CONTENT["x"] <= cursor[0] <= CONTENT["x"] + CONTENT["w"] and CONTENT["y"] <= cursor[1] <= CONTENT["y"] + CONTENT["h"]):
                    at = move(max(t_free, start - 500), inside, 500)
                first_cursor = first_cursor if first_cursor is not None else start - 500
                distance = abs(to - tab["scroll"])
                dur = 900 + min(distance, 3000) / 3000 * 700
                if distance > 1:
                    tracks["scroll"].append({"t0": at, "t1": at + dur, "tab": tab["id"], "page": tab["page"], "from": tab["scroll"], "to": to})
                tab["scroll"] = to
                end = at + dur + 100

        elif kind == "new_tab":
            point = _plus_point(len(tabs))
            click = move(max(t_free, start - TRAVEL), point)
            first_cursor = first_cursor if first_cursor is not None else click - TRAVEL
            tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
            new = {"id": f"t{len(tabs)}", "page": "start", "scroll": 0.0, "history": ["start"]}
            tabs.append(new)
            previous, active = active, len(tabs) - 1
            tracks["tabs"].append({"t": click + PRESS, "id": new["id"]})
            tracks["active"].append({"t": click + PRESS, "id": new["id"]})
            tracks["tab_page"].append({"t": click + PRESS, "tab": new["id"], "page": "start"})
            end = click + PRESS + 300

        elif kind == "switch_tab":
            index = action.get("tab", 0)
            index = previous if index < 0 else index
            if not 0 <= index < len(tabs):
                flags.append("no_such_tab")
            elif index != active:
                point = _tab_point(index)
                click = move(max(t_free, start - TRAVEL), point)
                first_cursor = first_cursor if first_cursor is not None else click - TRAVEL
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
                previous, active = active, index
                tracks["active"].append({"t": click + PRESS, "id": tabs[index]["id"]})
                end = click + PRESS + 200

        elif kind == "back":
            if len(tab["history"]) < 2:
                flags.append("nothing_to_go_back_to")
            else:
                point = BACK_BTN
                click = move(max(t_free, start - TRAVEL), point)
                first_cursor = first_cursor if first_cursor is not None else click - TRAVEL
                tracks["presses"].append({"t": click, "x": point[0], "y": point[1]})
                tab["history"] = tab["history"][:-1]
                loaded = click + PRESS + 350
                tracks["loading"].append({"t0": click + PRESS, "t1": loaded, "tab": tab["id"]})
                show(loaded, tab, tab["history"][-1])
                end = loaded + 200

        late = start - action["at_ms"]
        if late > LATE_FLAG_MS:
            flags.append("late")
        if action.get("source") == "rules":
            flags.append("rules_guess")
        if flags:
            issues.append({"action_id": action["id"], "flags": sorted(set(flags)), "late_ms": round(max(late, 0))})
        t_free = max(t_free, end)

    if tracks["camera"]:
        tracks["camera"].insert(0, {"t": 0, "zoom": 1.0, "fx": STAGE_W / 2, "fy": STAGE_H / 2})

    cursor_in = max(0.0, (first_cursor if first_cursor is not None else duration_ms) - 300)
    return {
        "version": 1,
        "fps": fps,
        "duration_ms": duration_ms,
        "layout": LAYOUT,
        "pages": pages,
        "tabs": [{"id": t["id"]} for t in tabs],
        "tracks": tracks,
        "cursor": {"in": cursor_in, "out": duration_ms + 1000, "start": [CONTENT["x"] + CONTENT["w"] * 0.6, CONTENT["y"] + CONTENT["h"] * 0.55]},
        "issues": issues,
        "results": {aid: {"page": r.get("page"), "link_text": r.get("link_text")} for aid, r in results.items()},
    }
