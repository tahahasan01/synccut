"""EDL invariants. Run on every timeline write and before every render."""

from __future__ import annotations

KINDS = {"face", "browser", "hold"}
CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}
SPEED_RANGE = (0.5, 4.0)
TOLERANCE_MS = 50


def validate(edl: dict, takes_by_id: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    segments = edl.get("segments", [])
    total = edl.get("total_frames", 0)

    if total > 0 and not segments:
        errors.append("timeline has no segments")
    expected_start = 0
    for seg in segments:
        sid = seg.get("id", "?")
        if seg["start_f"] != expected_start:
            errors.append(f"{sid}: starts at frame {seg['start_f']}, expected {expected_start} (gap or overlap)")
        if seg["end_f"] <= seg["start_f"]:
            errors.append(f"{sid}: empty or negative length")
        expected_start = seg["end_f"]

        kind = seg.get("kind")
        if kind not in KINDS:
            errors.append(f"{sid}: unknown kind {kind!r}")
            continue
        if kind == "face":
            continue

        take = takes_by_id.get(seg.get("take_id"))
        if take is None or take.get("status") != "ready":
            errors.append(f"{sid}: take {seg.get('take_id')!r} is missing or not ready")
            continue
        duration = take["duration_ms"]
        if kind == "hold":
            at = seg.get("hold_at_ms")
            if at is None or not 0 <= at <= duration:
                errors.append(f"{sid}: hold frame {at} is outside the take (0–{duration} ms)")
            continue
        if not seg.get("pieces"):
            errors.append(f"{sid}: browser segment has no footage")
        for piece in seg.get("pieces", []):
            if not (0 <= piece["in_ms"] < piece["out_ms"] <= duration + TOLERANCE_MS):
                errors.append(f"{sid}: piece {piece['in_ms']}–{piece['out_ms']} ms is outside the take")
            if not SPEED_RANGE[0] <= piece["speed"] <= SPEED_RANGE[1]:
                errors.append(f"{sid}: speed {piece['speed']} outside {SPEED_RANGE}")

    if segments and expected_start != total:
        errors.append(f"timeline ends at frame {expected_start}, narration has {total} frames")

    layout = edl.get("layout", {})
    if layout.get("pip_corner") not in CORNERS:
        errors.append(f"layout: unknown PiP corner {layout.get('pip_corner')!r}")
    if not 0.1 <= float(layout.get("pip_width_pct", 0)) <= 0.45:
        errors.append("layout: PiP width must be between 10% and 45%")
    return errors
