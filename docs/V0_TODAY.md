# SyncCut v0 — One-Day Build

> Scope for the first working version. Production architecture stays in [BUILD_PLAN.md](BUILD_PLAN.md); v0 deliberately swaps infrastructure for local equivalents so the full user flow works end to end today.

## What v0 does

1. **Upload narration video** → local Whisper transcribes with word timings → narration split into **beats** (one sentence or step each, editable).
2. **Record the browser** from the web app (`getDisplayMedia`), in one of three modes:
   - **Guided:** floating teleprompter (Document Picture-in-Picture) shows the current beat. Press **Next** (or `Alt+Shift+N` via the extension) as you start each beat.
   - **Play-along:** narration plays while you browse, and beat markers are placed automatically.
   - **Free-form:** just browse. Beats are mapped to navigation/tab events by timing (flagged for review).
   - Can **start at any beat**, so you can redo one step without re-recording the rest (newest take wins).
3. **Auto-sync:** each beat's slot in the narration is filled with its browser clip. Idle/frozen stretches are trimmed (`freezedetect`), then the clip is sped up to at most 1.75×, then the middle is cut. Short clips hold the last frame. Missing clips fall back to a freeze or to the face full-screen. Everything is flagged when uncertain.
4. **Review:** segment list with flags. Change kind (browser / hold / face), adjust clip in/out, pick the take, PiP corner/size/visibility. Draft render preview.
5. **Export:** final 1080p30 MP4 (H.264 + AAC, faststart), original audio only.
6. **Share page** `/v/<slug>`, under **your own branding**: video, message, proof (rating, profile link, portfolio) and an embedded booking calendar (Calendly / Cal.com), with no contact details shown.

**Out of scope (deliberately):** impersonating Loom or any other brand, automated Upwork proposal sending, auth/billing, cloud deploy.

## v0 architecture

```
apps/web (Next.js :3000) ──REST/poll──► services/api (FastAPI :8000)
  recorder · teleprompter · review ·       projects.json store · thread-pool jobs
  share page                               ffmpeg · faster-whisper · sync/retime/render
        ▲  window events                   data/projects/<id>/... (local files)
apps/extension (MV3, unpacked)
  tab/nav/click events (only while recording, inputs masked) · Alt+Shift+N hotkey
```

| Production (BUILD_PLAN) | v0 stand-in |
|---|---|
| Postgres | `project.json` per project (locked writes) |
| Redis + Celery | in-process `ThreadPoolExecutor`, job state in project.json, UI polls |
| S3 / R2 | `data/` folder served by FastAPI |
| Hosted ASR | faster-whisper (CPU, `base.en` default, `SYNCCUT_WHISPER_MODEL` to change) |
| Claude beat extraction + matching | sentence/pause segmentation, plus timing-based DP for free-form |
| Auth | none (local only) |

The pure logic (`synccut/core`: beats, timeline/retime, EDL validation, ffmpeg graph) has the same shape as the production design, so it carries over.

## Checklist

- [x] V0-01 Repo skeleton, .gitignore, README with run steps
- [x] V0-02 API: project store, job runner, media serving, CORS
- [x] V0-03 Ingest master: probe, 16 kHz WAV, transcribe, beats (Claude with rule-based fallback). *Transcription itself is untested on this machine: blocked until the VC++ runtime is installed.*
- [x] V0-04 Takes: chunked upload, complete → CFR mp4, freeze detection, events/markers saved
- [x] V0-05 Core: beats segmentation, retime solver, timeline builder (guided / play-along / free-form), EDL validator, with unit tests
- [x] V0-06 Renderer: per-segment compose (face / browser / hold + rounded PiP), concat, mux audio, ffprobe assertions, with test
- [x] V0-07 Web: projects list, project page (upload → steps → record → review → export → share)
- [x] V0-08 Web: recorder + Document-PiP teleprompter + play-along. *Builds and type-checks; needs a manual run in Chrome (screen capture can't be automated here).*
- [x] V0-09 Extension: event capture, masking, hotkey, bridge to app. *Needs a manual load in Chrome.*
- [x] V0-10 Share page + brand settings
- [x] V0-11 End-to-end API run with synthetic media (upload → steps → chunked WebM take → sync → edits → 1080p render → share): passed; README written

## Known gaps after today

- Whisper needs the Microsoft Visual C++ Redistributable on Windows.
- Claude step grouping needs a Console API key (`sk-ant-api03-…`); OAuth tokens are rejected.
- Not yet exercised in a real browser: screen capture, teleprompter window, extension hotkey/events.
- Single-user, local only: no auth, no deploy. Share links work only on this machine until deployed.
