from synccut.core.beats import segment_beats
from synccut.core.edl import validate
from synccut.core.retime import fit_clip
from synccut.core.timeline import build_timeline, infer_markers, take_clips


def words_from(text_and_times):
    return [{"w": w, "start_ms": s, "end_ms": e} for w, s, e in text_and_times]


# beats -------------------------------------------------------------------------


def test_beats_split_on_sentences_and_merge_short():
    words = words_from([
        ("Hi.", 0, 300),                      # too short alone → merged forward
        ("I", 400, 500), ("open", 500, 800), ("Google.", 800, 2000),
        ("Then", 2500, 2800), ("I", 2800, 2900), ("search", 2900, 3400), ("jobs.", 3400, 4500),
    ])
    beats = segment_beats(words)
    assert [b["text"] for b in beats] == ["Hi. I open Google.", "Then I search jobs."]
    assert beats[0]["start_ms"] == 0 and beats[1]["end_ms"] == 4500


def test_beats_split_on_long_pause():
    words = words_from([("first", 0, 1000), ("part", 1000, 2000), ("second", 3500, 4500), ("part", 4500, 5600)])
    assert len(segment_beats(words, pause_ms=700)) == 2


def test_beats_split_overlong():
    words = words_from([(f"w{i}", i * 1000, i * 1000 + 800) for i in range(30)])
    assert all(b["end_ms"] - b["start_ms"] <= 15000 for b in segment_beats(words, pause_ms=10_000))


# retime ------------------------------------------------------------------------


def test_short_clip_holds():
    fit = fit_clip(1000, 3000, 5000)
    assert fit["pieces"] == [{"in_ms": 1000, "out_ms": 3000, "speed": 1.0}]
    assert fit["hold_ms"] == 3000


def test_long_hold_flagged():
    assert "long_hold" in fit_clip(0, 1000, 8000)["flags"]


def test_idle_trimmed_before_speedup():
    fit = fit_clip(0, 10_000, 8000, idle=[(4000, 7000)])
    total = sum(p["out_ms"] - p["in_ms"] for p in fit["pieces"])
    assert abs(total - 8000) < 1
    assert all(p["speed"] == 1.0 for p in fit["pieces"])
    assert "idle_trimmed" in fit["flags"]


def test_speedup_within_cap():
    fit = fit_clip(0, 12_000, 8000)
    assert fit["pieces"][0]["speed"] == 1.5 and fit["hold_ms"] == 0


def test_heavy_retime_keeps_ends():
    fit = fit_clip(0, 60_000, 10_000, max_speed=1.75)
    assert "heavy_retime" in fit["flags"]
    assert fit["pieces"][0]["in_ms"] == 0 and fit["pieces"][-1]["out_ms"] == 60_000
    content = sum(p["out_ms"] - p["in_ms"] for p in fit["pieces"])
    assert abs(content / 1.75 - 10_000) < 1


def test_empty_clip_missing():
    assert fit_clip(5000, 5000, 3000)["flags"] == ["missing_footage"]


# timeline ----------------------------------------------------------------------

BEATS = [
    {"id": "b1", "text": "intro", "start_ms": 500, "end_ms": 3000},
    {"id": "b2", "text": "open google", "start_ms": 3200, "end_ms": 6000},
    {"id": "b3", "text": "search", "start_ms": 6200, "end_ms": 9500},
]


def make_take(tid="t1", mode="guided", markers=None, duration=12_000, created=1.0, events=None):
    return {
        "id": tid, "mode": mode, "status": "ready", "created_at": created, "duration_ms": duration,
        "markers": markers if markers is not None else [
            {"beat_id": "b1", "t_ms": 0}, {"beat_id": "b2", "t_ms": 3000}, {"beat_id": "b3", "t_ms": 7000},
        ],
        "events": events or [], "idle": [],
    }


def test_take_clips_from_markers():
    clips = take_clips(make_take(), ["b1", "b2", "b3"])
    assert clips == {"b1": (0, 3000), "b2": (3000, 7000), "b3": (7000, 12000)}


def test_timeline_tiles_and_validates():
    take = make_take()
    tl = build_timeline(BEATS, 10_000, [take], fps=30)
    segs = tl["segments"]
    assert segs[0]["kind"] == "face" and segs[0]["start_f"] == 0  # pre-roll before the first beat
    assert segs[-1]["end_f"] == tl["total_frames"] == 300
    assert validate(tl, {"t1": take}) == []
    assert {s["kind"] for s in segs[1:]} == {"browser"}


def test_missing_beat_holds_previous_frame():
    take = make_take(markers=[{"beat_id": "b1", "t_ms": 0}, {"beat_id": "b2", "t_ms": 3000}])
    tl = build_timeline(BEATS, 10_000, [take], fps=30)
    last = tl["segments"][-1]
    assert last["kind"] == "hold" and "missing_footage" in last["flags"] and last["needs_review"]
    assert validate(tl, {"t1": take}) == []


def test_newer_take_wins_for_redone_beat():
    old = make_take("t_old", created=1.0)
    redo = make_take("t_new", markers=[{"beat_id": "b2", "t_ms": 500}], duration=4000, created=2.0)
    tl = build_timeline(BEATS, 10_000, [old, redo], fps=30)
    by_beat = {s["beat_id"]: s for s in tl["segments"] if s["beat_id"]}
    assert by_beat["b2"]["take_id"] == "t_new"
    assert by_beat["b3"]["take_id"] == "t_old"


def test_locked_segment_survives_resync():
    take = make_take()
    tl = build_timeline(BEATS, 10_000, [take], fps=30)
    seg = next(s for s in tl["segments"] if s["beat_id"] == "b2")
    seg.update(kind="face", take_id=None, clip=None, locked=True)
    again = build_timeline(BEATS, 10_000, [take], fps=30, previous=tl)
    seg2 = next(s for s in again["segments"] if s["beat_id"] == "b2")
    assert seg2["kind"] == "face" and seg2["locked"] and again["version"] == tl["version"] + 1


def test_freeform_infers_monotonic_markers():
    events = [{"type": "navigation", "t_ms": 3500}, {"type": "submit", "t_ms": 8000}, {"type": "click", "t_ms": 9000}]
    take = make_take(mode="freeform", markers=[], events=events)
    markers = infer_markers(take, BEATS, 10_000)
    times = [m["t_ms"] for m in markers]
    assert times == sorted(times) and len(set(times)) == 3
    tl = build_timeline(BEATS, 10_000, [take], fps=30)
    assert all("auto_guess" in s["flags"] for s in tl["segments"] if s["kind"] == "browser")


def test_validate_catches_gap():
    take = make_take()
    tl = build_timeline(BEATS, 10_000, [take], fps=30)
    tl["segments"][1]["start_f"] += 1
    assert any("gap or overlap" in e for e in validate(tl, {"t1": take}))
