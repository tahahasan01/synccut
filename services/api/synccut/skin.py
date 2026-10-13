"""Build the stage's look from a real screenshot of the user's Mac.

The desktop (wallpaper, menu bar, Dock and its app icons) and Chrome's frame
(traffic lights, tab search, "Ask Gemini", extensions, New Tab page) are cut from
one full-screen screenshot of Chrome on the New Tab page, so the video shows
exactly that machine. Only what changes during the video is drawn on top: tabs,
the address bar's text, pages, the pointer.

The look can be tidied while keeping those pixels: hide the bookmarks bar and the
profile photo, keep only the first few extensions, and take apps out of the Dock
(the remaining icons are closed up, as macOS does).

Geometry is in stage pixels (1920x1080) and was measured on a macOS Chrome
screenshot; the generated window uses the same rectangle, so the crops line up
1:1. The output contains the user's own screen, so it lives in the (git-ignored)
data directory, never in the repo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import media
from .core.scene import BOOKMARKS_H, CHROME_H, OMNI_W, VIEW_H, VIEW_W

WINDOW = {"x": 293, "y": 91, "w": 1272, "h": 862}

# Measured on the screenshot, all in 1920x1080 stage pixels.
SHOT = {
    "toolbar_rows": (40, 81),      # window-relative rows of the toolbar
    "bookmarks_rows": (81, 119),   # the bookmarks bar
    "divider_rows": (119, 121),    # the line above the page
    "omni": (411, 134, 622, 38),   # focused omnibox (x, y, w, h), absolute
    "omni_slices": (60, 300, 115),  # left part, a clean column to stretch, right part (AI Mode)
    "toolbar_icons_y": (137, 169),
    "extensions": [1055.5, 1092, 1128, 1163.5, 1200, 1236, 1272, 1308.5, 1344, 1380.5, 1416.5],
    "puzzle": 1453.5, "avatar": 1507, "menu": 1543, "icon_pitch": 36,
    "ntp_avatar": (1218, 14, 36, 36),  # Google account photo on the New Tab page (in ntp coords)
    "dock": {"x0": 72, "x1": 1844, "y0": 997, "y1": 1076, "radius": 20, "first": 109, "pitch": 68, "apps": 21,
             "sep1": (1503, 1537), "recent": [1571, 1639, 1707], "sep2": (1741, 1772), "trash": (1772, 1840)},
}

# Crops used as-is: name -> (x, y, w, h)
CROPS = {
    "tab_l": (413, 96, 13, 35),            # active tab: left flare (6 px) and edge (7 px)
    "tab_m": (600, 96, 1, 35),             # active tab: a clean column to stretch
    "tab_r": (642, 96, 15, 35),            # active tab: right edge (10 px) and flare (5 px)
    "tab_x": (628, 103, 15, 15),           # the tab's close button
    "plus": (660, 99, 23, 23),             # new-tab button
}

COLORS = {
    "strip": "#211a28", "toolbar": "#3a3141", "omni": "#302935", "ring": "#d7b1fb",
    "text": "#efe9f2", "muted": "#b3aab9", "icon": "#e2dce6", "icon_dim": "#706576",
}
TOOLBAR_RGB = (58, 49, 65)
NTP_RGB = (58, 49, 65)

# The look this machine's videos use: no bookmarks bar or profile photo, two extensions,
# and a Dock without Slack, Teams, Bitsnap or the extra Chrome icons (apps are numbered
# left to right from 0; 21+ are the recent apps after the divider).
DEFAULT_OPTIONS = {"bookmarks": False, "avatar": False, "extensions": 2, "dock_remove": [13, 16, 18, 21, 22, 23]}


def _read(path: Path) -> np.ndarray:
    out = subprocess.run([media.FFMPEG, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    info = media.probe(path)
    return np.frombuffer(out, np.uint8).reshape(info["height"], info["width"], 3).copy()


def _write(img: np.ndarray, path: Path) -> None:
    h, w = img.shape[:2]
    subprocess.run([media.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-",
                    "-frames:v", "1", str(path)], input=np.ascontiguousarray(img, np.uint8).tobytes(), check=True)


def _rounded_mask(h: int, w: int, r: int) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(float) + 0.5
    cx = np.clip(xx, r, w - r)
    cy = np.clip(yy, r, h - r)
    d = np.hypot(xx - cx, yy - cy)
    return np.clip(r + 0.5 - d, 0, 1)[..., None]


def _edit_dock(desk: np.ndarray, nodock: np.ndarray, remove: list[int]) -> np.ndarray:
    """Close up the Dock without the removed apps, keeping its real pixels and shape."""
    d = SHOT["dock"]
    half = d["pitch"] // 2
    strip = desk[d["y0"]:d["y1"], :]
    pieces = [strip[:, d["x0"]:d["first"] - half]]  # left end
    for k in range(d["apps"]):
        if k not in remove:
            c = d["first"] + k * d["pitch"]
            pieces.append(strip[:, c - half:c + half])
    recent = [c for i, c in enumerate(d["recent"]) if d["apps"] + i not in remove]
    if recent:
        pieces.append(strip[:, d["sep1"][0]:d["sep1"][1]])
        pieces += [strip[:, int(c) - half:int(c) + half] for c in recent]
    pieces.append(strip[:, d["sep2"][0]:d["sep2"][1]])
    pieces.append(strip[:, d["trash"][0]:d["trash"][1]])
    pieces.append(strip[:, d["trash"][1]:d["x1"]])  # right end
    dock = np.concatenate(pieces, axis=1).astype(float)
    h, w = dock.shape[:2]
    x = (1920 - w) // 2
    out = nodock.astype(float)
    m = _rounded_mask(h, w, d["radius"])
    region = out[d["y0"]:d["y1"], x:x + w]
    out[d["y0"]:d["y1"], x:x + w] = region * (1 - m) + dock * m
    return out.round().astype(np.uint8)


def _icon(img: np.ndarray, cx: float) -> np.ndarray:
    y0, y1 = SHOT["toolbar_icons_y"]
    x = int(round(cx)) - 16
    return img[y0:y1, x:x + 32]


def _edit_window(desk: np.ndarray, options: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The Chrome window, its focused omnibox and its New Tab page, per `options`."""
    wx, wy, ww, wh = WINDOW["x"], WINDOW["y"], WINDOW["w"], WINDOW["h"]
    src = desk
    ox, oy, ow, oh = SHOT["omni"]
    left, mid, right = SHOT["omni_slices"]
    focus = src[oy:oy + oh, ox:ox + ow]
    omni = np.concatenate([focus[:, :left], np.repeat(focus[:, mid:mid + 1], OMNI_W - left - right, axis=1),
                           focus[:, ow - right:]], axis=1)

    # toolbar: clear everything right of the omnibox, then lay out the kept icons from the right
    t0, t1 = SHOT["toolbar_rows"]
    tb = src[wy + t0:wy + t1, wx:wx + ww].copy()
    keep = SHOT["extensions"][: options.get("extensions", 2)] + [SHOT["puzzle"]]
    if options.get("avatar", True):
        keep.append(SHOT["avatar"])
    icons = [_icon(src, c) for c in keep] + [_icon(src, SHOT["menu"])]
    tb[1:, ox - wx:ww - 2] = TOOLBAR_RGB
    iy = SHOT["toolbar_icons_y"][0] - wy - t0
    for i, ic in enumerate(reversed(icons)):
        cx = int(round(SHOT["menu"] - i * SHOT["icon_pitch"] - wx))
        tb[iy:iy + ic.shape[0], cx - 16:cx + 16] = ic
    tb[oy - wy - t0:oy - wy - t0 + oh, ox - wx:ox - wx + OMNI_W] = omni

    top = src[wy:wy + t0, wx:wx + ww]
    bm = src[wy + SHOT["bookmarks_rows"][0]:wy + SHOT["bookmarks_rows"][1], wx:wx + ww]
    div = src[wy + SHOT["divider_rows"][0]:wy + SHOT["divider_rows"][1], wx:wx + ww]
    page_top = wy + SHOT["divider_rows"][1]
    ntp = src[page_top:page_top + 741, wx + 1:wx + 1 + VIEW_W].copy()
    if not options.get("avatar", True):
        x, y, w, h = SHOT["ntp_avatar"]
        ntp[y:y + h, x:x + w] = NTP_RGB
    # the New Tab page re-centred in the (possibly taller) page area
    grow = VIEW_H - ntp.shape[0]
    if grow:
        page = np.empty((VIEW_H, VIEW_W, 3), np.uint8)
        page[:] = NTP_RGB
        page[:80] = ntp[:80]                                   # Gmail / Images row stays at the top
        page[80 + grow // 2:680 + grow // 2] = ntp[80:680]     # logo, search box and shortcuts move to the middle
        page[680 + grow:] = ntp[680:]                          # "Customize Chrome" stays at the bottom
        ntp = page
    chrome = np.concatenate([top, tb] + ([bm] if options.get("bookmarks", True) else []) + [div], axis=0)
    assert chrome.shape[0] == CHROME_H, (chrome.shape, CHROME_H)
    window = np.empty((wh, ww, 3), np.uint8)
    window[:] = NTP_RGB
    window[:CHROME_H] = chrome
    window[CHROME_H:, 1:1 + VIEW_W] = ntp
    window[CHROME_H:, 0] = src[page_top + 100, wx]          # the window's 1 px side borders
    window[CHROME_H:, ww - 1] = src[page_top + 100, wx + ww - 1]
    return window, omni, ntp


DOCK_TOP = 984  # the Dock and the strip around it, in the 1920x1080 screenshot


def build_skin(screenshot: Path, out_dir: Path, empty_desktop: Path | None = None, options: dict | None = None) -> dict:
    """Cut the layers out of `screenshot` into `out_dir`; returns the skin description.

    `empty_desktop` (optional) is a screenshot of the same desktop with no windows: its
    wallpaper above the Dock fills the Dock's place for videos with the Dock hidden.
    """
    options = {**DEFAULT_OPTIONS, **(options or {})}
    if options.get("bookmarks", True) != (BOOKMARKS_H > 2):
        raise ValueError("the stage geometry (BOOKMARKS_H) and the skin's bookmarks option disagree")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "desktop_full.png"
    media.ffmpeg("-i", str(screenshot), "-frames:v", "1", "-vf", "scale=1920:1080:flags=lanczos", str(base), timeout=60)
    # Dock hidden (like macOS's auto-hide): mirror the wallpaper just above it into its place,
    # softened, with the seam blurred. Taken from the empty desktop when there is one, since
    # in `screenshot` a window covers the middle of that strip.
    band = 1080 - DOCK_TOP
    source = "[1]scale=1920:1080:flags=lanczos," if empty_desktop else "[0]"
    inputs = ["-i", str(base)] + (["-i", str(empty_desktop)] if empty_desktop else [])
    media.ffmpeg(*inputs, "-filter_complex",
                 f"{source}crop=1920:{band}:0:{DOCK_TOP - band},vflip,gblur=sigma=1.0[b];"
                 f"[0][b]overlay=0:{DOCK_TOP},format=rgb24,split[o1][o2];"
                 f"[o2]crop=1920:20:0:{DOCK_TOP - 10},gblur=sigma=4[s];[o1][s]overlay=0:{DOCK_TOP - 10}",
                 "-frames:v", "1", str(out_dir / "desktop_nodock.png"), timeout=60)

    desk = _read(base)
    nodock = _read(out_dir / "desktop_nodock.png")
    remove = options.get("dock_remove") or []
    _write(_edit_dock(desk, nodock, remove) if remove else desk, out_dir / "desktop.png")
    window, omni, ntp = _edit_window(desk, options)
    _write(window, out_dir / "window.png")
    _write(omni, out_dir / "omni_focus.png")
    _write(ntp, out_dir / "ntp.png")
    for name, (x, y, w, h) in CROPS.items():
        _write(desk[y:y + h, x:x + w], out_dir / f"{name}.png")
    base.unlink(missing_ok=True)
    skin = {"version": int(time.time()), "window": WINDOW, "crops": CROPS, "colors": COLORS, "options": options}
    (out_dir / "skin.json").write_text(json.dumps(skin, indent=2), encoding="utf-8")
    return skin


def load_skin(skins_dir: Path, name: str = "default") -> dict | None:
    path = skins_dir / name / "skin.json"
    if not path.exists():
        return None
    skin = json.loads(path.read_text(encoding="utf-8"))
    skin["url"] = f"/skins/{name}/"
    return skin


def remove_skin(skins_dir: Path, name: str = "default") -> None:
    shutil.rmtree(skins_dir / name, ignore_errors=True)
