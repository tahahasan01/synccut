"""SRT / WebVTT import: a fallback for when local transcription isn't available."""

from __future__ import annotations

import re

_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_CUE = re.compile(rf"({_TIME.pattern})\s*-->\s*({_TIME.pattern})")


def _ms(match: re.Match, offset: int) -> float:
    h, m, s, frac = (match.group(offset + i) for i in range(4))
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def parse_subtitles(text: str) -> list[dict]:
    """Return word timings. Each cue's time is shared across its words by word length."""
    words: list[dict] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        m = _CUE.search(lines[i])
        if not m:
            i += 1
            continue
        start, end = _ms(m, 2), _ms(m, 7)
        i += 1
        cue: list[str] = []
        while i < len(lines) and lines[i].strip():
            cue.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
            i += 1
        tokens = " ".join(cue).split()
        if not tokens or end <= start:
            continue
        total = sum(len(t) + 1 for t in tokens)
        t = start
        for token in tokens:
            dur = (end - start) * (len(token) + 1) / total
            words.append({"w": token, "start_ms": round(t), "end_ms": round(t + dur * 0.9)})
            t += dur
    return words
