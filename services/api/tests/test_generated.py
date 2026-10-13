from synccut.core.actions import validate_actions
from synccut.core.edl import validate
from synccut.core.scene import ADDRESS, build_scene
from synccut.core.subtitles import parse_subtitles
from synccut.core.timeline import build_generated_timeline

SRT = """1
00:00:01,000 --> 00:00:03,000
First I open Google.

2
00:00:03,500 --> 00:00:06,500
Then I search for <i>AI engineering</i> jobs.
"""

ACTIONS = validate_actions([
    {"type": "navigate", "at_ms": 1500, "url": "google"},
    {"type": "search", "at_ms": 4000, "query": "ai engineering jobs"},
    {"type": "scroll", "at_ms": 7000, "target": "down"},
    {"type": "click", "at_ms": 9000, "target": "first result"},
], 15_000)

CAPTURE = {
    "pages": {
        "p1": {"id": "p1", "url": "https://www.google.com/", "title": "Google", "image": "pages/p1.jpg", "height": 896, "status": "ok", "favicon": None},
        "p2": {"id": "p2", "url": "https://www.bing.com/search?q=x", "title": "x - Search", "image": "pages/p2.jpg", "height": 3000, "status": "ok", "favicon": None},
        "p3": {"id": "p3", "url": "https://example.com/", "title": "Example", "image": None, "height": 896, "status": "failed", "favicon": None},
    },
    "results": {
        "a1": {"flags": [], "page": "p1"},
        "a2": {"flags": [], "page": "p2"},
        "a3": {"flags": [], "scroll_to": 672},
        "a4": {"flags": ["page_unavailable"], "box": {"x": 160, "y": 2000, "w": 400, "h": 22}, "page": "p3"},
    },
}


def test_subtitles_to_words():
    words = parse_subtitles(SRT)
    assert [w["w"] for w in words][:4] == ["First", "I", "open", "Google."]
    assert words[0]["start_ms"] == 1000 and words[3]["end_ms"] <= 3000
    assert any(w["w"] == "AI" for w in words)  # tags stripped
    assert parse_subtitles("WEBVTT\n\n00:01.000 --> 00:02.500\nHello there\n")[1]["w"] == "there"


def test_scene_click_lands_before_page_changes():
    scene = build_scene(ACTIONS, CAPTURE, 15_000)
    tr = scene["tracks"]
    press_times = [p["t"] for p in tr["presses"]]
    shows = [e["t"] for e in tr["tab_page"] if e["page"] != "start"]
    assert len(shows) == 3
    for show in shows:  # every page change is preceded by a press
        assert any(p < show for p in press_times)
    typing = tr["typing"][0]
    assert typing["text"] == "google.com" and typing["t0"] >= press_times[0]
    assert tr["presses"][0]["x"] > ADDRESS["x"]


def test_cursor_is_continuous():
    tr = build_scene(ACTIONS, CAPTURE, 15_000)["tracks"]
    moves = tr["moves"]
    for a, b in zip(moves, moves[1:]):
        assert (a["x1"], a["y1"]) == (b["x0"], b["y0"])  # no teleports
        assert b["t0"] >= a["t1"] - 1e-6


def test_click_offscreen_target_scrolls_first_and_issues_reported():
    scene = build_scene(ACTIONS, CAPTURE, 15_000)
    scrolls = scene["tracks"]["scroll"]
    assert len(scrolls) == 2  # the spoken scroll, then an automatic one to reveal the link
    issue = next(i for i in scene["issues"] if i["action_id"] == "a4")
    assert "page_unavailable" in issue["flags"]


def test_generated_timeline_is_valid_and_flags_steps():
    beats = [{"id": "b1", "start_ms": 1000, "end_ms": 3000}, {"id": "b2", "start_ms": 3500, "end_ms": 14000}]
    take = {"id": "tg", "status": "ready", "duration_ms": 15_000}
    scene = build_scene(ACTIONS, CAPTURE, 15_000)
    tl = build_generated_timeline(beats, 15_000, take, ACTIONS, scene["issues"], fps=30)
    assert validate(tl, {"tg": take}) == []
    assert all(s["kind"] == "browser" and s["pieces"][0]["speed"] == 1.0 for s in tl["segments"])
    flagged = [s for s in tl["segments"] if s["needs_review"]]
    assert len(flagged) == 1 and "page_unavailable" in flagged[0]["flags"]


def test_results_land_right_after_the_word_not_seconds_later():
    from synccut.core.scene import LAND

    scene = build_scene(ACTIONS, CAPTURE, 15_000)
    shows = {e["page"]: e["t"] for e in scene["tracks"]["tab_page"] if e["page"] != "start"}
    # "open Google" at 1.5 s: painted ~0.22 s later (a touch more here: 1.5 s isn't enough lead-in
    # for a human-paced pointer move and typing, and nothing can start before 0:00)
    assert 0 <= shows["p1"] - (1500 + LAND) < 150
    search = scene["tracks"]["typing"][1]
    assert 3800 <= search["t0"] <= 4100  # the query is typed as it is said, from "search"
    assert shows["p2"] > search["t1"]  # results only after the last key and Enter
    assert scene["tracks"]["camera"] == []  # no zoom effect unless asked for
    assert scene["cursor"]["in"] < 0  # pointer on screen from the first frame


def test_linked_page_is_already_open_when_the_video_starts():
    actions = validate_actions([{"type": "navigate", "at_ms": 0, "url": "https://www.google.com/", "source": "page"}], 15_000)
    scene = build_scene(actions, {"pages": CAPTURE["pages"], "results": {actions[0]["id"]: {"flags": [], "page": "p1"}}}, 15_000)
    assert scene["tracks"]["tab_page"][0] == {"t": 0, "tab": "t0", "page": "p1"}
    assert scene["tracks"]["typing"] == [] and scene["issues"] == []


def test_linked_page_mentioned_early_is_open_from_the_first_frame():
    job = "https://www.google.com/"
    actions = validate_actions([{"type": "navigate", "at_ms": 2600, "url": job}], 15_000)
    capture = {"pages": CAPTURE["pages"], "results": {actions[0]["id"]: {"flags": [], "page": "p1"}}}
    assert build_scene(actions, capture, 15_000, opening_url=job)["tracks"]["tab_page"][0]["page"] == "p1"
    assert build_scene(actions, capture, 15_000)["tracks"]["typing"]  # without the link it is typed in as said


def test_new_window_and_switching_back():
    from synccut.core.actions import plan_with_rules
    from synccut.core.scene import window_rect

    words = [{"w": w, "start_ms": i * 400.0, "end_ms": i * 400.0 + 350} for i, w in enumerate(
        "First I open a new window then go to hubspot.com and now switch back to the first window".split())]
    plan = validate_actions(plan_with_rules(words), 20_000)
    assert [a["type"] for a in plan] == ["new_window", "navigate", "switch_window"]
    assert plan[2]["tab"] == 0

    capture = {"pages": {"p1": {"id": "p1", "url": "https://hubspot.com/", "title": "HubSpot", "image": "pages/p1.jpg",
                                "height": 900, "status": "ok", "favicon": None}},
               "results": {plan[1]["id"]: {"flags": [], "page": "p1"}}}
    scene = build_scene(plan, capture, 20_000)
    tr = scene["tracks"]
    assert [w["id"] for w in scene["windows"]] == ["w0", "w1"]
    assert [f["id"] for f in tr["front"]] == ["w0", "w1", "w0"]
    assert {t["id"]: t["win"] for t in scene["tabs"]} == {"t0": "w0", "t1": "w1"}
    assert tr["typing"][0]["tab"] == "t1"  # hubspot is typed into the new window's tab
    # opening a window is ⌘N (no pointer travel), but switching back clicks a visible part of window 0
    click = tr["presses"][-1]
    w0, w1 = window_rect(0), window_rect(1)
    inside = lambda r: r["x"] <= click["x"] <= r["x"] + r["w"] and r["y"] <= click["y"] <= r["y"] + r["h"]  # noqa: E731
    assert inside(w0) and not inside(w1)
    assert scene["issues"] == [] or all("rules_guess" in i["flags"] for i in scene["issues"])


def test_tabs_are_counted_per_window():
    actions = validate_actions([
        {"type": "new_tab", "at_ms": 1000}, {"type": "new_window", "at_ms": 3000},
        {"type": "switch_tab", "at_ms": 5000, "tab": 1},  # only one tab in the new window
    ], 10_000)
    scene = build_scene(actions, {"pages": {}, "results": {}}, 10_000)
    assert any("no_such_tab" in i["flags"] for i in scene["issues"])


def test_typing_is_human_paced():
    from synccut.core.scene import autocomplete_keys, keystrokes

    keys = keystrokes("HubSpot workflow automation", "a1")
    gaps = [b - a for a, b in zip(keys, keys[1:])]
    assert 120 <= sum(gaps) / len(gaps) <= 200  # 60-100 words a minute, not a burst
    assert min(gaps) > 70 and max(gaps) - min(gaps) > 60  # an uneven rhythm
    assert keystrokes("HubSpot workflow automation", "a1") == keys  # deterministic, so renders repeat exactly
    assert autocomplete_keys("hubspot.com") == 5  # "hubsp", then Chrome completes "ot.com"

    scene = build_scene(ACTIONS, CAPTURE, 15_000)
    nav = scene["tracks"]["typing"][0]
    assert nav["typed"] < len(nav["text"]) and nav["enter"] - nav["t1"] >= 200  # a glance at the suggestion


def test_skin_is_cut_from_a_screenshot(tmp_path):
    import subprocess
    from synccut.skin import CROPS, build_skin, load_skin

    shot = tmp_path / "screen.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=3840x2160",
                    "-frames:v", "1", str(shot)], check=True)  # a Retina-size screenshot
    build_skin(shot, tmp_path / "skins" / "default")
    for name in ["desktop", "desktop_nodock", *CROPS]:
        assert (tmp_path / "skins" / "default" / f"{name}.png").exists()
    skin = load_skin(tmp_path / "skins")
    scene = build_scene(ACTIONS, CAPTURE, 15_000, skin=skin)
    assert scene["skin"]["url"] == "/skins/default/" and scene["skin"]["colors"]["strip"]
    assert build_scene(ACTIONS, CAPTURE, 15_000)["skin"] is None
