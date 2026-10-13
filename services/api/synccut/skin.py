"""Build the stage's look from a real screenshot of the user's Mac.

The desktop (wallpaper, menu bar, Dock and its app icons) and Chrome's frame
(traffic lights, tab search, "Ask Gemini", extensions, profile, bookmarks bar,
New Tab page) are cut from one full-screen screenshot of Chrome on the New Tab
page, so the video shows exactly that machine. Only what changes during the
video is drawn on top: tabs, the address bar's text, pages, the pointer.

Geometry is in stage pixels (1920x1080) and was measured on a macOS Chrome
screenshot; the generated window uses the same rectangle, so the crops line up
1:1. The output contains the user's bookmarks and profile photo, so it lives in
the (git-ignored) data directory, never in the repo.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import media

WINDOW = {"x": 293, "y": 91, "w": 1272, "h": 862}

# name: (x, y, w, h) in the 1920x1080 screenshot
CROPS = {
    "window": (WINDOW["x"], WINDOW["y"], WINDOW["w"], WINDOW["h"]),
    "ntp": (294, 212, 1270, 741),          # the New Tab page content
    "tab_l": (413, 96, 13, 35),            # active tab: left flare (6 px) and edge (7 px)
    "tab_m": (600, 96, 1, 35),             # active tab: a clean column to stretch
    "tab_r": (642, 96, 15, 35),            # active tab: right edge (10 px) and flare (5 px)
    "tab_x": (628, 103, 15, 15),           # the tab's close button
    "plus": (660, 99, 23, 23),             # new-tab button
    "omni_focus": (411, 134, 622, 38),     # focused omnibox: ring, G, AI Mode
}

# Colours sampled from the same screenshot (the Chrome theme in use).
COLORS = {
    "strip": "#211a28", "toolbar": "#3a3141", "omni": "#302935", "ring": "#d7b1fb",
    "text": "#efe9f2", "muted": "#b3aab9", "icon": "#e2dce6", "icon_dim": "#706576",
}


def build_skin(screenshot: Path, out_dir: Path) -> dict:
    """Crop the layers out of `screenshot` into `out_dir`; returns the skin description."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "desktop.png"
    media.ffmpeg("-i", str(screenshot), "-frames:v", "1", "-vf", "scale=1920:1080:flags=lanczos", str(base), timeout=60)
    for name, (x, y, w, h) in CROPS.items():
        media.ffmpeg("-i", str(base), "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y}", str(out_dir / f"{name}.png"), timeout=60)
    skin = {"version": int(time.time()), "window": WINDOW, "crops": CROPS, "colors": COLORS}
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
