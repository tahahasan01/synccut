"""Browser actions planned from the narration.

An action is tied to the word that triggers it; its time is that word's start.
The rule-based planner here needs no AI and is the fallback for the Claude
planner (``synccut.ai_actions``).
"""

from __future__ import annotations

import bisect
import re

ACTION_TYPES = ("navigate", "search", "scroll", "click", "new_tab", "switch_tab", "new_window", "switch_window", "back")

KNOWN_SITES = {
    "google": "https://www.google.com/",
    "youtube": "https://www.youtube.com/",
    "linkedin": "https://www.linkedin.com/",
    "upwork": "https://www.upwork.com/",
    "fiverr": "https://www.fiverr.com/",
    "github": "https://github.com/",
    "gmail": "https://mail.google.com/",
    "twitter": "https://x.com/",
    "facebook": "https://www.facebook.com/",
    "instagram": "https://www.instagram.com/",
    "reddit": "https://www.reddit.com/",
    "amazon": "https://www.amazon.com/",
    "notion": "https://www.notion.so/",
    "hubspot": "https://www.hubspot.com/",
    "zapier": "https://zapier.com/",
    "make": "https://www.make.com/",
    "n8n": "https://n8n.io/",
    "airtable": "https://www.airtable.com/",
    "slack": "https://slack.com/",
    "figma": "https://www.figma.com/",
    "chatgpt": "https://chatgpt.com/",
    "wikipedia": "https://www.wikipedia.org/",
    "indeed": "https://www.indeed.com/",
    "glassdoor": "https://www.glassdoor.com/",
    "stack overflow": "https://stackoverflow.com/",
    "stackoverflow": "https://stackoverflow.com/",
    "typeform": "https://www.typeform.com/",
    "shopify": "https://www.shopify.com/",
    "stripe": "https://stripe.com/",
}

_SITE_NAMES = "|".join(sorted((re.escape(k) for k in KNOWN_SITES), key=len, reverse=True))
_DOMAIN = r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.(?:com|io|ai|co|org|net|dev|app|so|me|us|uk|de|info)(?:/[^\s,]*)?"
_STOP = r"(?=\s+(?:and|then|so|to see|which|where|because|on|in|here|now)\b|[.?!,;]|$)"

TLD_WORDS = {"com", "io", "ai", "co", "org", "net", "dev", "app", "so"}


def site_url(name: str) -> str:
    name = name.strip().lower().rstrip(".")
    if name in KNOWN_SITES:
        return KNOWN_SITES[name]
    if re.fullmatch(_DOMAIN, name):
        return name if name.startswith("http") else f"https://{name}"
    return ""


def normalize_words(words: list[dict]) -> list[dict]:
    """Join spoken domains ("make dot com" → "make.com"), keeping the first word's timing."""
    out: list[dict] = []
    i = 0
    while i < len(words):
        w = words[i]
        if (
            i + 2 < len(words)
            and words[i + 1]["w"].strip().lower() == "dot"
            and words[i + 2]["w"].strip(" .,!?").lower() in TLD_WORDS
        ):
            joined = w["w"].strip(" .,!?") + "." + words[i + 2]["w"].strip(" .,!?").lower()
            tail = words[i + 2]["w"].strip()[-1:] if words[i + 2]["w"].strip()[-1:] in ".,!?" else ""
            out.append({**w, "w": joined + tail, "end_ms": words[i + 2]["end_ms"], "src": i})
            i += 3
            continue
        out.append({**w, "src": i})
        i += 1
    return out


PATTERNS: list[tuple[str, re.Pattern]] = [
    ("new_window", re.compile(r"\b(?:open|opening|opens|pull up)\s+(?:up\s+)?(?:a\s+|another\s+)?(?:new\s+)?(?:browser\s+|chrome\s+)?window\b")),
    ("switch_window", re.compile(
        r"\b(?:switch|switching|go|going|jump|head|move)\s+(?:back\s+)?(?:over\s+)?to\s+(?:the\s+)?"
        r"(?P<which>first|second|third|previous|other|last|original|old|main)\s+(?:browser\s+)?window\b")),
    ("new_tab", re.compile(r"\b(?:open|opening|opens)\s+(?:up\s+)?(?:a\s+)?new\s+tab\b")),
    ("switch_tab", re.compile(
        r"\b(?:switch|switching|go|going|jump|head)\s+(?:back\s+)?(?:over\s+)?to\s+(?:the\s+)?"
        r"(?P<which>first|second|third|previous|other|last|original|old)\s+tab\b")),
    ("click", re.compile(
        r"\b(?:open|click|clicking|click on|tap|select|choose)\s+(?:on\s+)?(?:the\s+)?"
        r"(?P<target>first|second|third|top)\s+(?:result|link)\b")),
    ("search", re.compile(
        r"\b(?:search|searching|searched|google|googling|look up|looking up|type in|typing in)\s+"
        r"(?:for\s+|up\s+)?(?P<query>(?!the\s+(?:first|second)\b)[^.?!,;]{2,70}?)" + _STOP)),
    ("navigate", re.compile(
        r"\b(?:open|opening|opens|go to|going to|goes to|head over to|head to|navigate to|visit|visiting|pull up|bring up|load)\s+"
        r"(?:up\s+)?(?:the\s+)?(?P<site>" + _DOMAIN + r"|" + _SITE_NAMES + r")\b")),
    ("scroll", re.compile(
        r"\b(?:scroll|scrolling|scrolls|scrolled)\b\s*"
        r"(?P<dir>all the way down|back up|down|up)?"
        r"(?:\s*to\s+(?!(?:see|find|check|look|read|get|show|view|make)\b)(?:the\s+)?(?P<to>[a-z0-9' ]{3,40}?)" + _STOP + r")?")),
    ("click", re.compile(
        r"\b(?:click|clicking|clicks|tap|press|hit)\s+(?:on\s+)?(?:the\s+)?(?P<target>[a-z0-9' ]{2,40}?)"
        r"(?:\s+(?:button|link|tab|menu))?" + _STOP)),
    ("back", re.compile(r"\bgo(?:ing)?\s+back\b(?!\s+(?:up|to))")),
]


# "your job post", "my site", "our app": the page the user linked to the project.
PAGE_REFERENCE = re.compile(
    r"\b(?:open|opening|go to|going to|head over to|head to|visit|visiting|pull up|pulling up|bring up|load|navigate to|"
    r"check out|checking out|look at|looking at|looked at|read|reading|went through|going through|go through|saw|"
    r"here'?s|here is|this is)\s+(?:up\s+)?(?:my|our|your|the|this)\s+(?:own\s+)?"
    r"(?P<noun>job posting|job post|job listing|job description|posting|listing|job|project|brief|website|site|web app|"
    r"app|dashboard|store|shop|profile|portfolio|landing page|homepage|home page|page)\b")


def plan_with_rules(words: list[dict], page_url: str = "") -> list[dict]:
    """Find browser actions in the narration with phrase patterns.

    page_url is the link the user gave the project (their site, or the job posting
    they're replying to); references like "your job post" open it."""
    norm = normalize_words([w for w in words if w.get("w", "").strip()])
    if not norm:
        return []
    starts, parts, pos = [], [], 0
    for w in norm:
        token = w["w"].strip().lower()
        starts.append(pos)
        parts.append(token)
        pos += len(token) + 1
    text = " ".join(parts)

    found: list[tuple[int, int, str, re.Match]] = []
    patterns = PATTERNS + ([("page", PAGE_REFERENCE)] if page_url else [])
    for kind, pattern in patterns:
        for m in pattern.finditer(text):
            if any(not (m.end() <= a or m.start() >= b) for a, b, _, _ in found):
                continue  # an earlier, more specific pattern already claimed this phrase
            found.append((m.start(), m.end(), kind, m))
    found.sort(key=lambda f: f[0])

    actions: list[dict] = []
    for start, end, kind, m in found:
        idx = max(0, bisect.bisect_right(starts, start) - 1)
        action = _build(kind, m) if kind != "page" else {"type": "navigate", "url": page_url, "query": "", "target": "", "tab": 0}
        if action is None:
            continue
        action.update(
            id=f"a{len(actions) + 1}",
            at_ms=float(norm[idx]["start_ms"]),
            word_index=norm[idx]["src"],
            spoken=text[start:end],
            source="rules",
            confidence=0.6,
        )
        actions.append(action)
    return actions


def _build(kind: str, m: re.Match) -> dict | None:
    base = {"type": kind, "url": "", "query": "", "target": "", "tab": 0}
    if kind == "navigate":
        url = site_url(m.group("site"))
        return {**base, "url": url} if url else None
    if kind == "search":
        query = re.sub(r"^(?:the|a|an)\s+", "", m.group("query").strip())
        return {**base, "query": query} if len(query) >= 2 else None
    if kind == "scroll":
        direction = (m.group("dir") or "down").strip()
        to = (m.group("to") or "").strip()
        if to in ("bottom", "end", "bottom of the page"):
            target = "bottom"
        elif to in ("top", "top of the page"):
            target = "top"
        elif to:
            target = to
        else:
            target = {"all the way down": "bottom", "back up": "top"}.get(direction, direction)
        return {**base, "target": target}
    if kind == "click":
        target = m.group("target").strip()
        if target in ("first", "top", "second", "third"):
            target = f"{'first' if target == 'top' else target} result"
        if target in ("it", "that", "this", "here", "there", "on"):
            return None
        return {**base, "target": target}
    if kind == "switch_window":
        which = m.group("which")
        index = {"first": 0, "original": 0, "old": 0, "main": 0, "second": 1, "third": 2}.get(which, -1)
        return {**base, "tab": index}
    if kind == "switch_tab":
        which = m.group("which")
        tab = {"first": 0, "original": 0, "old": 0, "second": 1, "third": 2}.get(which, -1)
        return {**base, "tab": tab}
    return base


def validate_actions(actions: list[dict], duration_ms: float) -> list[dict]:
    """Normalise and sort user- or AI-supplied actions; drop unusable ones."""
    clean = []
    for a in actions:
        if a.get("type") not in ACTION_TYPES:
            continue
        a = {
            "type": a["type"],
            "at_ms": float(min(max(0.0, a.get("at_ms", 0.0)), max(duration_ms - 500, 0))),
            "url": str(a.get("url") or "").strip(),
            "query": str(a.get("query") or "").strip(),
            "target": str(a.get("target") or "").strip(),
            "tab": int(a.get("tab") or 0),
            "spoken": str(a.get("spoken") or ""),
            "source": a.get("source") or "user",
            "confidence": float(a.get("confidence", 1.0)),
            "id": a.get("id") or "",
        }
        if a["type"] == "navigate":
            a["url"] = a["url"] if a["url"].startswith("http") else site_url(a["url"]) or (f"https://{a['url']}" if "." in a["url"] else "")
            if not a["url"]:
                continue
        if a["type"] == "search" and not a["query"]:
            continue
        if a["type"] == "scroll" and not a["target"]:
            a["target"] = "down"
        if a["type"] == "click" and not a["target"]:
            continue
        clean.append(a)
    clean.sort(key=lambda a: a["at_ms"])
    for i, a in enumerate(clean):
        a["id"] = a["id"] or f"a{i + 1}"
    seen: set[str] = set()
    for i, a in enumerate(clean):
        if a["id"] in seen:
            a["id"] = f"a{i + 1}_{len(seen)}"
        seen.add(a["id"])
    return clean


def open_page_first(actions: list[dict], page_url: str) -> list[dict]:
    """With a linked page, the video opens on it unless the narration already does."""
    if not page_url or any(a["type"] == "navigate" and a["url"] == page_url for a in actions):
        return actions
    opening = {"id": "a0", "type": "navigate", "at_ms": 0.0, "url": page_url, "query": "", "target": "", "tab": 0,
               "spoken": "", "source": "page", "confidence": 1.0}
    return [opening] + actions


def content_key(action: dict) -> tuple:
    """What a page capture depends on: everything except timing."""
    return (action["type"], action["url"], action["query"], action["target"], action["tab"])
