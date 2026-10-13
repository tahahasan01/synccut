"""Plan browser actions from the narration with Claude.

Claude only picks the trigger word (by index) and the action. Times come from
that word's timestamp, and every field is validated; on any failure the
rule-based planner is used instead.
"""

from __future__ import annotations

import logging

from .claude_client import ask_json, credential_kind
from .config import settings
from .core.actions import ACTION_TYPES, open_page_first, plan_with_rules, validate_actions

log = logging.getLogger("synccut.ai_actions")

SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word_index": {"type": "integer"},
                    "type": {"type": "string", "enum": list(ACTION_TYPES)},
                    "url": {"type": "string"},
                    "query": {"type": "string"},
                    "target": {"type": "string"},
                    "tab": {"type": "integer"},
                    "spoken": {"type": "string"},
                },
                "required": ["word_index", "type", "url", "query", "target", "tab", "spoken"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["actions"],
    "additionalProperties": False,
}

PROMPT = """This is the narration of a screen-share video. A browser on screen will be animated to act out
what the speaker describes, at the moment they say it. Each word has an index in square brackets.

List the browser actions the narration implies, in order. Only include actions the speaker actually
describes or clearly implies ("here's your job post" right after mentioning Upwork implies navigating there);
do not invent extra steps. For each action:

- word_index: the index of the word where the action should start (usually the verb, e.g. "open", "search", "scroll").
- type: navigate | search | scroll | click | new_tab | switch_tab | new_window | switch_window | back
  (new_window only when they say "window"; a tab is a tab. At most 3 windows.)
- url: for navigate, a full https URL of a real public page. Use the site's main URL unless the speaker names
  a specific page. Leave "" for other types.
- query: for search, the exact search text. "" otherwise.
- target: for scroll: "down", "up", "bottom", "top", or a short phrase of text on the page to scroll to
  (e.g. "requirements"). For click: the visible link or button text, or "first result" / "second result".
  "" otherwise.
- tab: for switch_tab, the 0-based tab index within the current window, or -1 for "the previous tab".
  For switch_window, the 0-based window index (0 = the first window), or -1 for "the other/previous window".
  0 otherwise.
- spoken: the few words that trigger the action, copied from the narration.

{page}Narration:
{words}"""

PAGE_NOTE = """The speaker linked this page to the video: {url}
It is their website or the job posting they are replying to. When they refer to it without naming another
site ("your job post", "the listing", "my site", "our app"), navigate to exactly this URL.

"""


def plan_actions(words: list[dict], duration_ms: float, page_url: str = "") -> tuple[list[dict], str]:
    """Return (actions, source) where source is "claude" or "rules"."""
    rules = open_page_first(validate_actions(plan_with_rules(words, page_url), duration_ms), page_url)
    if credential_kind() is None or not words:
        return rules, "rules"
    try:
        raw = _ask_claude(words, page_url)
        actions = []
        for a in raw:
            i = a["word_index"]
            if not 0 <= i < len(words):
                raise ValueError(f"word_index {i} out of range")
            actions.append({**a, "at_ms": float(words[i]["start_ms"]), "source": "claude", "confidence": 0.9})
        return open_page_first(validate_actions(actions, duration_ms), page_url), "claude"
    except Exception as exc:
        log.warning("Claude action planning failed, using rule-based plan: %s", exc)
        return rules, "rules"


def _ask_claude(words: list[dict], page_url: str = "") -> list[dict]:
    listing = " ".join(f"[{i}]{w['w']}" for i, w in enumerate(words))
    page = PAGE_NOTE.format(url=page_url) if page_url else ""
    return ask_json(PROMPT.format(words=listing, page=page), SCHEMA, effort="low")["actions"]
