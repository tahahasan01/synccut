"""Build the edit decision list (EDL): which footage fills each beat's slot.

The narration video is the master clock. Every segment boundary sits on the
output frame grid, and segments tile ``[0, total_frames)`` with no gaps.
"""

from __future__ import annotations

import time

from .retime import fit_clip

DEFAULT_LAYOUT = {
    "pip_corner": "bottom-left",
    "pip_width_pct": 0.22,
    "pip_visible": True,
    "camera_zoom": True,
}
LEAD_MS = 200
REVIEW_FLAGS = {"missing_footage", "heavy_retime", "auto_guess", "long_hold"}
REVIEW_BELOW = 0.7
MODE_CONFIDENCE = {"guided": 0.95, "play_along": 0.9}
SIGNIFICANT_EVENTS = {"navigation", "tab_activated", "tab_created", "submit", "history"}


def ms_to_frame(ms: float, fps: int) -> int:
    return int(round(ms * fps / 1000))


def frame_to_ms(frame: int, fps: int) -> float:
    return frame * 1000 / fps


def take_clips(take: dict, beat_ids: list[str]) -> dict[str, tuple[float, float]]:
    """Map beat id → (in_ms, out_ms) in take time, from the take's markers."""
    known = set(beat_ids)
    markers = sorted(
        (m for m in take.get("markers", []) if m["beat_id"] in known),
        key=lambda m: m["t_ms"],
    )
    duration = take["duration_ms"]
    clips: dict[str, tuple[float, float]] = {}
    for i, marker in enumerate(markers):
        start = max(0.0, marker["t_ms"])
        end = markers[i + 1]["t_ms"] if i + 1 < len(markers) else duration
        end = min(end, duration)
        if end > start:
            clips[marker["beat_id"]] = (start, end)
    return clips


def infer_markers(take: dict, beats: list[dict], master_duration_ms: float) -> list[dict]:
    """Free-form takes: place one marker per beat on browser events, by relative timing.

    Monotonic DP: pick increasing candidate times whose position in the take
    best matches each beat's relative position in the narration.
    """
    if not beats:
        return []
    duration = take["duration_ms"]
    cands = {0.0}
    for event in take.get("events", []):
        t = event.get("t_ms", -1)
        if event.get("type") in SIGNIFICANT_EVENTS and 0 < t < duration - 500:
            cands.add(float(t))
    if len(cands) < len(beats):
        for k in range(len(beats)):
            cands.add(duration * k / len(beats))
    times = sorted(cands)

    first = beats[0]["start_ms"]
    span = max(master_duration_ms - first, 1)
    targets = [(b["start_ms"] - first) / span for b in beats]
    rel = [t / max(duration, 1) for t in times]

    n_beats, n_cands = len(beats), len(times)
    inf = float("inf")
    cost = [[inf] * n_cands for _ in range(n_beats)]
    back = [[-1] * n_cands for _ in range(n_beats)]
    for j in range(n_cands):
        cost[0][j] = abs(rel[j] - targets[0])
    for i in range(1, n_beats):
        best, best_j = inf, -1
        for j in range(n_cands):
            if j > 0 and cost[i - 1][j - 1] < best:
                best, best_j = cost[i - 1][j - 1], j - 1
            if best_j >= 0:
                cost[i][j] = best + abs(rel[j] - targets[i])
                back[i][j] = best_j
    j = min(range(n_cands), key=lambda c: cost[-1][c])
    picks = [0] * n_beats
    for i in range(n_beats - 1, -1, -1):
        picks[i] = j
        j = back[i][j]
    return [{"beat_id": b["id"], "t_ms": times[picks[i]]} for i, b in enumerate(beats)]


def _clip_sources(takes: list[dict], beats: list[dict], master_duration_ms: float):
    """Per ready take (newest first): its clips and how much to trust them."""
    beat_ids = [b["id"] for b in beats]
    ready = [t for t in takes if t.get("status") == "ready"]
    ready.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    sources = []
    for take in ready:
        if take.get("mode") == "freeform" or not take.get("markers"):
            inferred = dict(take, markers=infer_markers(take, beats, master_duration_ms))
            sources.append((take, take_clips(inferred, beat_ids), 0.5, ["auto_guess"]))
        else:
            conf = MODE_CONFIDENCE.get(take.get("mode"), 0.8)
            sources.append((take, take_clips(take, beat_ids), conf, []))
    return sources


def apply_fit(segment: dict, take: dict | None, fps: int) -> dict:
    """Recompute pieces/hold for a segment from its kind, take and clip."""
    slot_ms = frame_to_ms(segment["end_f"] - segment["start_f"], fps)
    segment["pieces"], segment["hold_ms"] = [], 0
    fit_flags: list[str] = []
    if segment["kind"] == "browser" and take and segment.get("clip"):
        clip = segment["clip"]
        clip_in = max(0.0, clip["in_ms"])
        clip_out = min(take["duration_ms"], clip["out_ms"])
        fit = fit_clip(clip_in, clip_out, slot_ms, take.get("idle", []))
        segment["pieces"], segment["hold_ms"], fit_flags = fit["pieces"], fit["hold_ms"], fit["flags"]
        if not segment["pieces"]:
            segment["kind"] = "hold"
            segment["hold_at_ms"] = clip_in
    if segment["kind"] == "hold" and take:
        last_frame = max(0.0, take["duration_ms"] - 100)
        segment["hold_at_ms"] = min(max(0.0, segment.get("hold_at_ms") or 0.0), last_frame)
    kept = [f for f in segment.get("flags", []) if f not in {"heavy_retime", "long_hold", "idle_trimmed"}]
    segment["flags"] = kept + [f for f in fit_flags if f not in kept]
    return segment


def finalize(segment: dict) -> dict:
    conf = segment.get("base_confidence", 1.0)
    if "heavy_retime" in segment["flags"]:
        conf -= 0.3
    if "long_hold" in segment["flags"]:
        conf -= 0.1
    segment["confidence"] = round(max(0.0, min(1.0, conf)), 2)
    segment["needs_review"] = bool(
        not segment.get("locked")
        and (segment["confidence"] < REVIEW_BELOW or REVIEW_FLAGS & set(segment["flags"]))
    )
    return segment


def build_timeline(
    beats: list[dict],
    master_duration_ms: float,
    takes: list[dict],
    *,
    fps: int = 30,
    layout: dict | None = None,
    previous: dict | None = None,
    lead_ms: float = LEAD_MS,
) -> dict:
    total_frames = ms_to_frame(master_duration_ms, fps)
    takes_by_id = {t["id"]: t for t in takes}
    sources = _clip_sources(takes, beats, master_duration_ms)
    locked = {
        s["beat_id"]: s
        for s in (previous or {}).get("segments", [])
        if s.get("locked") and s.get("beat_id")
    }

    # Beat slots on the frame grid; zero-length slots are skipped.
    slots: list[tuple[dict, int]] = []
    last_f = 0
    for beat in beats:
        f = max(last_f, ms_to_frame(max(0.0, beat["start_ms"] - lead_ms), fps))
        f = min(f, total_frames)
        if slots and f == slots[-1][1]:
            continue
        slots.append((beat, f))
        last_f = f

    segments: list[dict] = []

    def add(segment: dict) -> None:
        segment["id"] = f"s{len(segments) + 1}"
        segments.append(finalize(segment))

    if not slots or slots[0][1] > 0:
        first_end = slots[0][1] if slots else total_frames
        if first_end > 0:
            add(_face(None, 0, first_end, base=1.0, flags=[]))

    last_browser: dict | None = None
    for i, (beat, start_f) in enumerate(slots):
        end_f = slots[i + 1][1] if i + 1 < len(slots) else total_frames
        if end_f <= start_f:
            continue

        if beat["id"] in locked:
            prior = locked[beat["id"]]
            segment = {
                **{k: prior.get(k) for k in ("kind", "take_id", "clip", "hold_at_ms", "flags")},
                "beat_id": beat["id"],
                "start_f": start_f,
                "end_f": end_f,
                "base_confidence": 1.0,
                "locked": True,
                "origin": "user",
            }
            segment["flags"] = list(segment.get("flags") or [])
            apply_fit(segment, takes_by_id.get(segment.get("take_id")), fps)
        else:
            segment = None
            for take, clips, conf, flags in sources:
                if beat["id"] in clips:
                    clip_in, clip_out = clips[beat["id"]]
                    segment = {
                        "kind": "browser",
                        "beat_id": beat["id"],
                        "start_f": start_f,
                        "end_f": end_f,
                        "take_id": take["id"],
                        "clip": {"in_ms": round(clip_in, 1), "out_ms": round(clip_out, 1)},
                        "flags": list(flags),
                        "base_confidence": conf,
                        "locked": False,
                        "origin": "auto",
                    }
                    apply_fit(segment, take, fps)
                    break
            if segment is None:
                segment = _missing(beat["id"], start_f, end_f, last_browser)
                apply_fit(segment, takes_by_id.get(segment.get("take_id")), fps)

        if segment["kind"] == "browser" and segment["pieces"]:
            last_browser = segment
        add(segment)

    return {
        "version": (previous or {}).get("version", 0) + 1,
        "fps": fps,
        "total_frames": total_frames,
        "master_duration_ms": master_duration_ms,
        "layout": dict(layout or (previous or {}).get("layout") or DEFAULT_LAYOUT),
        "segments": segments,
        "created_at": time.time(),
        "origin": "auto",
    }


ISSUE_FLAGS = {"page_unavailable", "target_not_found", "late", "not_captured", "scroll_text_not_found", "no_such_tab", "not_a_link"}


def build_generated_timeline(
    beats: list[dict],
    master_duration_ms: float,
    take: dict,
    actions: list[dict],
    issues: list[dict],
    *,
    fps: int = 30,
    layout: dict | None = None,
    previous: dict | None = None,
    lead_ms: float = LEAD_MS,
) -> dict:
    """Generated browser footage is already in sync, so every step plays 1:1.

    Segments still follow the steps so the review can flag a step whose actions
    had problems, or switch a step to the narrator full-screen.
    """
    total_frames = ms_to_frame(master_duration_ms, fps)
    bounds = [0]
    for beat in beats:
        f = min(max(bounds[-1], ms_to_frame(max(0.0, beat["start_ms"] - lead_ms), fps)), total_frames)
        if f > bounds[-1]:
            bounds.append(f)
    if bounds[-1] < total_frames:
        bounds.append(total_frames)
    beat_at = {}
    for beat in beats:
        f = ms_to_frame(max(0.0, beat["start_ms"] - lead_ms), fps)
        beat_at.setdefault(min(max(f, 0), total_frames), beat["id"])

    flags_by_action = {i["action_id"]: [f for f in i["flags"] if f in ISSUE_FLAGS] for i in issues}
    face_locked = {
        s["beat_id"] for s in (previous or {}).get("segments", []) if s.get("locked") and s.get("kind") == "face" and s.get("beat_id")
    }

    segments = []
    for start_f, end_f in zip(bounds, bounds[1:]):
        beat_id = beat_at.get(start_f)
        t0, t1 = frame_to_ms(start_f, fps), frame_to_ms(end_f, fps)
        flags = sorted({f for a in actions if t0 <= a["at_ms"] < t1 for f in flags_by_action.get(a["id"], [])})
        if beat_id in face_locked:
            seg = _face(beat_id, start_f, end_f, base=1.0, flags=[])
            seg.update(locked=True, origin="user")
        else:
            seg = {
                "kind": "browser", "beat_id": beat_id, "start_f": start_f, "end_f": end_f, "take_id": take["id"],
                "clip": {"in_ms": round(t0, 3), "out_ms": round(t1, 3)},
                "pieces": [{"in_ms": round(t0, 3), "out_ms": round(t1, 3), "speed": 1.0}],
                "hold_ms": 0, "flags": flags, "base_confidence": 0.5 if flags else 1.0, "locked": False, "origin": "auto",
            }
        seg["id"] = f"s{len(segments) + 1}"
        segments.append(finalize(seg))

    return {
        "version": (previous or {}).get("version", 0) + 1,
        "fps": fps,
        "total_frames": total_frames,
        "master_duration_ms": master_duration_ms,
        "layout": dict(layout or (previous or {}).get("layout") or DEFAULT_LAYOUT),
        "segments": segments,
        "created_at": time.time(),
        "origin": "auto",
        "generated": True,
    }


def _face(beat_id, start_f, end_f, *, base, flags) -> dict:
    return {
        "kind": "face",
        "beat_id": beat_id,
        "start_f": start_f,
        "end_f": end_f,
        "take_id": None,
        "clip": None,
        "pieces": [],
        "hold_ms": 0,
        "flags": flags,
        "base_confidence": base,
        "locked": False,
        "origin": "auto",
    }


def _missing(beat_id, start_f, end_f, last_browser: dict | None) -> dict:
    if last_browser is None:
        return _face(beat_id, start_f, end_f, base=0.5, flags=["missing_footage"])
    return {
        "kind": "hold",
        "beat_id": beat_id,
        "start_f": start_f,
        "end_f": end_f,
        "take_id": last_browser["take_id"],
        "clip": None,
        "hold_at_ms": last_browser["pieces"][-1]["out_ms"],
        "pieces": [],
        "hold_ms": 0,
        "flags": ["missing_footage"],
        "base_confidence": 0.3,
        "locked": False,
        "origin": "auto",
    }
