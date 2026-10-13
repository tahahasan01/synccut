# Generated browser mode

> Replaces "record your browser" as the default path. Recording stays available as a per-project fallback.
> Status: building · 2026-10-13

## Goal

From the narration video alone, automatically produce browser visuals that act out what the speaker says, at the moment they say it, then composite them with the narration (PiP bottom-left, original audio) and export an MP4. The user never records their browser.

## Pipeline

```
narration video
  → audio → Whisper word timestamps            (or: import SRT/VTT subtitles)
  → steps (beats)                              (existing)
  → ACTION PLAN    Claude: narration → [{word_index, type, args}]   (rule-based fallback)
                   code: word_index → at_ms                         (AI never does time math)
  → PAGE CAPTURE   headless Chromium executes the plan on REAL sites:
                   full-page screenshot + title + link boxes per page state
  → SCENE          scene.json = timeline of actions + page assets
  → STAGE          stage.html: macOS-style browser window (generic, no Apple branding),
                   tabs, address bar, cursor, scroll, typing, camera. Pure function seek(t).
  → PREVIEW        stage in an iframe, driven by the narration <video> currentTime (no render)
  → RENDER         headless Chromium: for each frame n → seek(n/30) → screenshot
                   (unchanged frames reused) → ffmpeg → browser track = narration length
  → COMPOSE        existing renderer: browser track + narration PiP + narration audio → MP4
```

## Action types

| Type | Spoken trigger (examples) | On screen |
|---|---|---|
| `navigate` | "open Google", "go to upwork.com" | cursor clicks address bar, types, Enter, loading bar, real page |
| `search` | "search for AI engineering jobs" | types query in address bar, Enter, real results page (Google if allowed, else Bing; the URL shown is the real one) |
| `scroll` | "scroll down", "scroll to the requirements" | cursor to page, smooth scroll (by amount, to bottom, or to matching text) |
| `click` | "click the first result", "open the pricing page" | cursor travels to the real link, presses, next page loads |
| `new_tab` | "open a new tab" | new tab slides in, start page |
| `switch_tab` | "go back to the first tab" | tab switches, that tab's page shows |
| `back` | "go back" | previous page in that tab |

## Rules taken from the interactive-product-demo skill

- The click lands before the state it causes (press, then navigate).
- The cursor is continuous: it enters once, never teleports, parks between actions.
- Visible press: ripple ring + contact flash, colour chosen against the page surface.
- Cursor travel 700–950 ms; press ~190 ms; holds let the viewer read.
- Camera (optional, default on): gentle push-in 1.08–1.12 on the acting control, back to whole window for holds. Open and close on the whole window.
- Never letterbox: stage is authored at 1920×1080, the output size.

Not taken: visibility gating, 8–15 s loop/3-action limits, real-time CSS transitions (replaced by `seek(t)` for frame-exact sync).

## Honesty constraints

- Pages are real captures; nothing imitates a site with invented content.
- If a site can't be captured (login wall, bot check, offline), the step shows a neutral placeholder card naming the URL and is flagged for review. The user can upload a screenshot for that step or record that step instead.
- The browser frame is generic macOS-style (traffic lights, tabs, address bar), with no Apple or Safari branding.

## Look

macOS-style desktop, generic (no Apple logo, no real app icons, no Safari name): menu bar
("Browser · File · Edit · View · History · Bookmarks · Window · Help", Wi-Fi/battery/search/clock),
Sequoia-like wallpaper, a frosted dock, and a Safari-style window: one unified toolbar (window
controls, sidebar, back/forward, centred address field, share / new tab / tab overview) with the tab
strip underneath. Layout constants live in `synccut/core/scene.py` (`LAYOUT`) and drive both the
stage DOM and the capture viewport (1620×860), so captures are invalidated when the layout changes.

## Verified (2026-10-13, Playwright MCP + exports)

- New video → upload narration → import SRT → plan (phrase matching) → real page capture (HubSpot, Bing results) automatically.
- Actions tab: thumbnails, triggers, link targets; timing-only edit keeps the capture, content edit re-captures (click switched to the second result).
- Preview: live stage synced to the narration clock; cursor, ripple, camera push-in, PiP.
- Export: 20 s → 600/600 frames, 1920×1080, audio; ~3× real time to render.

## Known limits

- Export takes ~1.5× the video length (frames drawn in 4 parallel tabs, segments composited in parallel).
- Login-walled pages and bot checks become placeholders (flagged). Google search results are blocked for automation, so searches use Bing unless Google loads.
- Pages are static captures: animations/video inside a page don't play.
- Without a valid Anthropic API key, actions come from phrase matching (clear verbs work best: "open…", "go to…", "search for…", "scroll down…", "click…").

## Checklist

- [x] G-01 Actions: rule-based planner + Claude planner (schema, validation, fallback), unit tests
- [x] G-02 Subtitle import (SRT/VTT) as a transcription fallback
- [x] G-03 Page capture worker: execute plan on real sites, screenshots, link boxes, placeholders
- [x] G-04 Stage: browser window, tabs, address bar typing, loading, scroll, click, cursor, ripple, camera; `seek(t)`
- [x] G-05 Stage renderer: frame-exact capture → ffmpeg, frame reuse
- [x] G-06 Generated timeline + export path through the existing renderer
- [x] G-07 Web: Actions tab (edit times/args, re-plan, capture), Preview tab (live synced stage + PiP)
- [x] G-08 End-to-end test in the browser via Playwright MCP
