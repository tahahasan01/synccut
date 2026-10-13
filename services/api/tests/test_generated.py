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
    assert abs(shows["p1"] - (1500 + LAND)) < 1  # "open Google" at 1.5 s: page painted 0.22 s later
    assert abs(shows["p2"] - (4000 + LAND)) < 1
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
