"""Split a word-timed transcript into beats: one sentence or spoken step each."""

from __future__ import annotations

SENTENCE_END = (".", "?", "!")


def segment_beats(
    words: list[dict],
    *,
    pause_ms: int = 700,
    min_ms: int = 1500,
    max_ms: int = 15000,
) -> list[dict]:
    """Group words into beats.

    A beat ends at sentence punctuation or at a pause of at least ``pause_ms``.
    Beats shorter than ``min_ms`` are merged into a neighbour, and beats longer
    than ``max_ms`` are split at their largest internal pause.

    ``words`` items look like ``{"w": "hello", "start_ms": 0, "end_ms": 300}``.
    """
    words = [w for w in words if w.get("w", "").strip()]
    if not words:
        return []

    groups: list[list[dict]] = []
    current: list[dict] = []
    for i, word in enumerate(words):
        current.append(word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends_sentence = word["w"].strip().endswith(SENTENCE_END)
        long_pause = nxt is not None and nxt["start_ms"] - word["end_ms"] >= pause_ms
        if nxt is None or ends_sentence or long_pause:
            groups.append(current)
            current = []

    groups = _merge_short(groups, min_ms)
    split: list[list[dict]] = []
    for group in groups:
        split.extend(_split_long(group, max_ms))

    return [
        {
            "id": f"b{i + 1}",
            "text": " ".join(w["w"].strip() for w in group).strip(),
            "start_ms": int(group[0]["start_ms"]),
            "end_ms": int(group[-1]["end_ms"]),
        }
        for i, group in enumerate(split)
    ]


def _duration(group: list[dict]) -> int:
    return group[-1]["end_ms"] - group[0]["start_ms"]


def _merge_short(groups: list[list[dict]], min_ms: int) -> list[list[dict]]:
    merged: list[list[dict]] = []
    carry: list[dict] = []
    for group in groups:
        group = carry + group
        carry = []
        if _duration(group) < min_ms:
            carry = group
        else:
            merged.append(group)
    if carry:
        if merged:
            merged[-1] = merged[-1] + carry
        else:
            merged.append(carry)
    return merged


def _split_long(group: list[dict], max_ms: int) -> list[list[dict]]:
    if _duration(group) <= max_ms or len(group) < 2:
        return [group]
    gaps = [group[i + 1]["start_ms"] - group[i]["end_ms"] for i in range(len(group) - 1)]
    # Prefer a gap after a comma when gaps are similar, otherwise the largest gap.
    best = max(
        range(len(gaps)),
        key=lambda i: (gaps[i] + (150 if group[i]["w"].strip().endswith(",") else 0)),
    )
    return _split_long(group[: best + 1], max_ms) + _split_long(group[best + 1 :], max_ms)
