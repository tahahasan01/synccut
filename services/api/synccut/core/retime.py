"""Fit a browser clip into a narration slot. Pure and deterministic.

Order of operations when the clip is too long:
1. cut idle (frozen) stretches, longest first, only as much as needed;
2. speed up uniformly, up to ``max_speed``;
3. keep the start and end of the clip and drop the middle (flagged).
A clip that is too short plays at 1x and then holds its last frame.
"""

from __future__ import annotations

Range = tuple[float, float]

LONG_HOLD_MS = 4000


def fit_clip(
    clip_in: float,
    clip_out: float,
    slot_ms: float,
    idle: list[Range] | tuple = (),
    *,
    max_speed: float = 1.75,
    idle_pad_ms: float = 150,
    min_idle_ms: float = 600,
) -> dict:
    flags: list[str] = []
    clip_ms = clip_out - clip_in
    if clip_ms <= 0 or slot_ms <= 0:
        return {"pieces": [], "hold_ms": max(slot_ms, 0), "flags": ["missing_footage"]}

    if clip_ms <= slot_ms:
        hold = slot_ms - clip_ms
        if hold > LONG_HOLD_MS:
            flags.append("long_hold")
        return {"pieces": [_piece(clip_in, clip_out, 1.0)], "hold_ms": hold, "flags": flags}

    active = _trim_idle([(clip_in, clip_out)], idle, clip_ms - slot_ms, idle_pad_ms, min_idle_ms)
    if len(active) > 1:
        flags.append("idle_trimmed")
    content = _total(active)

    if content <= slot_ms:
        return {
            "pieces": [_piece(a, b, 1.0) for a, b in active],
            "hold_ms": slot_ms - content,
            "flags": flags,
        }

    speed = content / slot_ms
    if speed <= max_speed:
        return {"pieces": [_piece(a, b, speed) for a, b in active], "hold_ms": 0, "flags": flags}

    budget = slot_ms * max_speed
    kept = _keep_ends(active, budget)
    flags.append("heavy_retime")
    return {"pieces": [_piece(a, b, max_speed) for a, b in kept], "hold_ms": 0, "flags": flags}


def _piece(a: float, b: float, speed: float) -> dict:
    return {"in_ms": round(a, 1), "out_ms": round(b, 1), "speed": round(speed, 4)}


def _total(ranges: list[Range]) -> float:
    return sum(b - a for a, b in ranges)


def _trim_idle(
    active: list[Range],
    idle: list[Range] | tuple,
    excess: float,
    pad: float,
    min_idle: float,
) -> list[Range]:
    """Remove up to ``excess`` ms of idle time, longest idle stretch first."""
    lo, hi = active[0][0], active[-1][1]
    cuts: list[Range] = []
    for a, b in idle:
        a, b = max(a, lo) + pad, min(b, hi) - pad
        if b - a >= min_idle - 2 * pad and b > a:
            cuts.append((a, b))
    cuts.sort(key=lambda r: r[1] - r[0], reverse=True)

    remaining = excess
    chosen: list[Range] = []
    for a, b in cuts:
        if remaining <= 0:
            break
        length = b - a
        if length > remaining:
            mid = (a + b) / 2
            a, b = mid - remaining / 2, mid + remaining / 2
            length = remaining
        chosen.append((a, b))
        remaining -= length

    result = active
    for cut in chosen:
        result = _subtract(result, cut)
    return result


def _subtract(ranges: list[Range], cut: Range) -> list[Range]:
    out: list[Range] = []
    ca, cb = cut
    for a, b in ranges:
        if cb <= a or ca >= b:
            out.append((a, b))
            continue
        if ca > a:
            out.append((a, ca))
        if cb < b:
            out.append((cb, b))
    return [(a, b) for a, b in out if b - a > 1]


def _keep_ends(ranges: list[Range], budget: float) -> list[Range]:
    """Keep the first and last ``budget / 2`` ms of content, dropping the middle."""
    half = budget / 2
    head: list[Range] = []
    need = half
    for a, b in ranges:
        if need <= 0:
            break
        take = min(b - a, need)
        head.append((a, a + take))
        need -= take
    tail: list[Range] = []
    need = half
    for a, b in reversed(ranges):
        if need <= 0:
            break
        take = min(b - a, need)
        tail.insert(0, (b - take, b))
        need -= take
    merged: list[Range] = []
    for a, b in head + tail:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged
