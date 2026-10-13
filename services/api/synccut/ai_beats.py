"""Group narration sentences into action steps with Claude.

Claude only decides which consecutive sentences belong together and labels
each step. All timestamps are computed here from the word timings, so a bad
model answer can't produce an invalid timeline. Any failure falls back to the
rule-based beats.
"""

from __future__ import annotations

import logging

from .claude_client import ask_json, credential_kind
from .config import settings
from .core.beats import segment_beats

log = logging.getLogger("synccut.ai_beats")

INTENTS = ["navigate", "search", "type", "click", "scroll", "switch_tab", "back", "open_result", "explain"]

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_unit": {"type": "integer"},
                    "last_unit": {"type": "integer"},
                    "label": {"type": "string"},
                    "intent": {"type": "string", "enum": INTENTS},
                    "site": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["first_unit", "last_unit", "label", "intent", "site", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}

PROMPT = """This is the narration of a screen-recorded walkthrough video, split into numbered units.
The speaker recorded the narration first; they will record their browser separately, one step at a time,
following a teleprompter.

Group consecutive units into steps. Each step is one thing the viewer should see happen in the browser
(open a site, search, click a result, scroll a page, switch tabs), or "explain" when the speaker is only
talking (intro, credentials, closing). Every unit must belong to exactly one step, in order, with no gaps.
Prefer 3–12 second steps; never split a sentence.

For each step give:
- label: a short imperative teleprompter instruction for the browser action, max 8 words
  (e.g. "Open the client's Upwork job post"). For explain steps, summarise what is said.
- intent: one of the allowed values.
- site: the website or app involved, or "" if none is named.
- query: text the speaker searches for or types, or "".

Units:
{units}"""


def claude_beats(words: list[dict]) -> tuple[list[dict], str]:
    """Return (beats, source) where source is "claude" or "rules"."""
    rules = segment_beats(words)
    if credential_kind() is None or not words:
        return rules, "rules"
    units = segment_beats(words, min_ms=0, max_ms=12000)
    if len(units) < 2:
        return rules, "rules"
    try:
        steps = _ask_claude(units)
        return _steps_to_beats(steps, units), "claude"
    except Exception as exc:  # any failure → deterministic fallback, never a broken timeline
        log.warning("Claude beat extraction failed, using rule-based beats: %s", exc)
        return rules, "rules"


def _ask_claude(units: list[dict]) -> list[dict]:
    listing = "\n".join(
        f"[{i}] ({u['start_ms'] / 1000:.1f}s–{u['end_ms'] / 1000:.1f}s) {u['text']}"
        for i, u in enumerate(units)
    )
    return ask_json(PROMPT.format(units=listing), SCHEMA, effort="low")["steps"]


def _steps_to_beats(steps: list[dict], units: list[dict]) -> list[dict]:
    n = len(units)
    steps = sorted(steps, key=lambda s: s["first_unit"])
    beats: list[dict] = []
    expected = 0
    for step in steps:
        first, last = step["first_unit"], step["last_unit"]
        if first != expected or last < first or last >= n:
            raise ValueError(f"steps don't tile the units at unit {expected}")
        group = units[first : last + 1]
        beats.append({
            "id": f"b{len(beats) + 1}",
            "text": " ".join(u["text"] for u in group),
            "label": step["label"].strip()[:80],
            "intent": step["intent"],
            "site": step["site"].strip(),
            "query": step["query"].strip(),
            "start_ms": group[0]["start_ms"],
            "end_ms": group[-1]["end_ms"],
        })
        expected = last + 1
    if expected != n:
        raise ValueError(f"steps stop at unit {expected} of {n}")
    return beats
