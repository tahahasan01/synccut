# SyncCut — Production Plan (v2)

> Working name. Replaces the v1 product plan. Engineering architecture, build plan and checklist: [BUILD_PLAN.md](BUILD_PLAN.md).
> Status: draft for review · Owner: engineering · Last updated: 2026-10-13

---

## 0. Summary

**Product:** The user records a talking-head/narration video once. Later they record their browser in a separate session. The system works out which browser action belongs to which spoken sentence, retimes the browser footage to fit the narration, and renders an MP4: browser footage full-frame, original video picture-in-picture bottom-left, original audio kept.

**What changed from v1, and why:**

| # | v1 | v2 | Why |
|---|----|----|-----|
| 1 | AI matching is the only way to sync | **Three recording modes.** *Play-along* (narration plays while the user browses), *Guided* (teleprompter of beats, hotkey to advance) and *Free-form* (AI-only alignment) | Matching two independent recordings is hard to get right every time. When the user follows the script while recording, sync becomes near-deterministic. AI then handles drift and corrections instead of guessing from scratch |
| 2 | "Synchronize" was undefined | **Explicit retiming model:** trim idle time, change speed (capped), hold last frame, jump-cut. The narration video is the master clock and is never retimed | This is what "sync" actually means in code. Without it the engine can't be built or tested |
| 3 | Timeline was implied | **The Edit Decision List (EDL) is the core contract.** It's versioned JSON, and the render is a pure function of (assets, EDL) | Lets AI, the editor and the renderer evolve independently. Enables re-sync without data loss, caching and golden tests |
| 4 | Local storage first | **S3-compatible object storage from day one** (MinIO locally, R2/S3 in prod) with presigned multipart uploads | Video files run to gigabytes. Routing them through the API server and migrating later is expensive. MinIO costs nothing in dev |
| 5 | Voice commands in MVP | **Deferred to v1.1.** MVP uses keyboard shortcuts | Reliable natural-language browser control is a product in itself. A live mic adds privacy and capture complexity, and it doesn't improve sync quality |
| 6 | Build order: capture → AI → render | **Build order: EDL + render → capture → AI → editor** | A hand-written EDL rendering correctly is the walking skeleton. Everything else plugs into it |
| 7 | Not covered | Variable-frame-rate (VFR) normalization, a single clock source, chunked crash-safe upload, input masking, segment-level render caching, golden-set evaluation in CI | Without these, a demo can't become a product |

---

## 1. Product definition

### 1.1 Problem
Recording camera and screen at the same time is stressful, and every mistake means a full retake or manual editing. Creators of sales videos (e.g. Loom-style Upwork pitches), tutorials and product walkthroughs want to record the talking part once and the screen part whenever they like, including redoing one screen action without redoing the narration.

### 1.2 Target users (MVP)
- **Primary: freelancers/agencies doing outreach at volume** (e.g. Upwork proposals). They want a personal-looking 1–5 min walkthrough per prospect without re-recording themselves every time. Pattern: record the narration **once as a template**, then record a short browser take per prospect (their job post, their site, a relevant demo) and export one video per prospect.
- Secondary: educators and creators making 5–30 minute browser tutorials.

> Implication: the product is a **one narration → many takes → many exports** pipeline, not a one-off editor. The data model already supports this (a project has N takes). Templates are a near-term follow-up (§14).

### 1.3 Principles
1. **The original video is immutable and is the master clock.** Output duration = original duration.
2. **Use real footage only.** The system never generates or fakes browser visuals.
3. **Flag, don't fake.** Below the confidence threshold, a segment goes to review instead of being shipped silently wrong.
4. **AI proposes, deterministic code decides.** The model outputs matches and labels. All timestamp math, retiming and rendering is plain, testable code.
5. **Every step can be re-run.** Re-syncing never destroys user edits (locked segments are preserved).

### 1.4 Non-goals (MVP)
Desktop or non-Chrome capture, multi-user collaboration, AI-generated visuals, advanced transitions, automatic B-roll, mobile.

---

## 2. User workflow (revised)

```
1. Create project ──► 2. Upload narration video ──► 3. Analyze (transcribe, extract beats)
                                                             │
            ┌────────────────────────────────────────────────┘
            ▼
4. Record browser take(s) in a chosen mode:
   • Play-along: narration audio plays (headphones) and the beat teleprompter scrolls
   • Guided:     teleprompter shows the next beat; press Alt+Shift+N to advance
   • Free-form:  just browse
            │   (multiple takes allowed; re-record one action without redoing the rest)
            ▼
5. Auto-sync ──► EDL v1 (segments with confidence; low-confidence segments flagged)
            ▼
6. Review editor: preview, swap clip, nudge, trim, set fill, face-only, lock ──► EDL vN
            ▼
7. Export MP4 (render job) ──► download / share link
```

**Beats** are the unit of work: a span of narration that carries one intent ("Now I'll search for machine learning jobs"). Beats come from the transcript in step 3, which is why the teleprompter can show them in step 4.

**Fallbacks when footage is missing:** for a beat with no matching browser action, the user can show the narrator full-screen ("face-only"), hold the previous browser frame, or record a new take for just that beat.

---

## 3. System architecture

```
┌──────────────────────────┐        ┌──────────────────────────────┐
│ Chrome Extension (MV3)   │        │ Web App (Next.js, Vercel)    │
│ • recorder (offscreen)   │◄──────►│ • projects, upload, editor   │
│ • content scripts        │ pair   │ • preview player             │
│ • teleprompter window    │ token  │ • export UI                  │
└──────┬───────────┬───────┘        └──────┬───────────────┬───────┘
       │ events    │ video chunks          │ REST + SSE    │ presigned
       │ (HTTPS)   │ (presigned multipart) │               │ multipart upload
       ▼           ▼                       ▼               ▼
┌───────────────────────────┐      ┌───────────────────────────────┐
│ API (FastAPI)             │      │ Object storage (S3 / R2;      │
│ auth, projects, sessions, │─────►│ MinIO locally)                │
│ jobs, EDL CRUD, SSE       │      │ masters, takes, proxies,      │
└───────┬───────────────────┘      │ events.ndjson.gz, renders     │
        │ enqueue                  └───────────────▲───────────────┘
        ▼                                          │
┌───────────────────┐   ┌──────────────────────────┴──────────────┐
│ Redis (broker,    │◄─►│ Workers (Celery; separate queues)       │
│ progress pub/sub) │   │ ingest │ asr │ sync │ render            │
└───────────────────┘   │ ffmpeg, ASR client, LLM client          │
┌───────────────────┐   └─────────────────────────────────────────┘
│ Postgres (source  │◄── all job/project/EDL state
│ of truth)         │
└───────────────────┘
External: ASR provider (pluggable) · LLM provider (Claude) · Sentry · OTel
```

### 3.1 Stack decisions

| Layer | Choice | Notes |
|---|---|---|
| Web | Next.js (App Router), TypeScript, Tailwind + shadcn/ui, TanStack Query, Zustand (editor state) | Deployed on Vercel |
| Extension | MV3, TypeScript, **WXT** framework | Hot reload and cross-browser builds. Shares types with web |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic | Python because ffmpeg/ASR/ML tooling lives there |
| Jobs | Celery + Redis, job state mirrored in Postgres | Separate queues so a 20-min render can't starve ASR. Move to Temporal only if orchestration grows |
| DB | Postgres 16 (managed: Neon / RDS) | JSONB for EDL and probe data |
| Storage | S3-compatible: MinIO (dev), Cloudflare R2 or S3 (prod) | R2 has no egress fees, which matters for video |
| ASR | Pluggable interface. Default: hosted API with word timestamps. Alt: self-hosted faster-whisper/WhisperX on GPU | Start hosted (no GPU ops). Switch based on cost and volume |
| LLM | Claude (Sonnet-class) with JSON-schema structured output | Used only for beat extraction and candidate scoring |
| Media | FFmpeg 7.x, ffprobe | Pinned version in the worker image |
| Auth | Clerk or Auth.js (decide in Phase 0) | Extension pairs via a short-lived token |
| Observability | Sentry (web, extension, API, workers), OpenTelemetry traces, structured JSON logs | Job dashboards: queue depth, durations, failure rate |
| Hosting (API/workers) | Containers (Fly.io / Railway / ECS) | Renders are long and CPU-heavy, with large scratch disks. **Don't run them as serverless functions** |

### 3.2 Repository layout (monorepo)

```
/apps/web            Next.js app
/apps/extension      WXT MV3 extension
/packages/schemas    JSON Schema = single source of truth (EDL, events, beats, API DTOs)
                     → codegen: TS types (json-schema-to-typescript) + Pydantic (datamodel-codegen)
/packages/ui         shared React components
/services/api        FastAPI app
/services/worker     Celery app + task entrypoints
/services/core       pure Python lib: edl/, sync/, ffmpeg_graph/, media/ (no I/O, heavily tested)
/fixtures            golden projects (media + events + ground-truth alignment)
/infra               docker-compose (postgres, redis, minio, api, worker), IaC later
```

pnpm + Turborepo for JS, uv for Python. CI runs lint, type-check, unit tests, golden sync eval and golden render tests.

---

## 4. Core data contracts

### 4.1 Entities (Postgres)

- `users`, `projects` (status machine below)
- `assets`: id, project_id, kind (`master | take | proxy | audio | render | thumb_sprite | waveform`), storage_key, sha256, probe (JSONB), created_at
- `takes`: id, project_id, mode (`play_along | guided | freeform`), media_asset_id, events_key, clock (JSONB: media start epoch, measured offset), status
- `transcripts`: project_id, provider, words (JSONB: `[{w, start_ms, end_ms, conf}]`)
- `beats`: id, project_id, idx, start_ms, end_ms, text, intent (JSONB)
- `episodes`: id, take_id, idx, start_ms, end_ms, type, entities (JSONB), keyframe_keys
- `timelines`: id, project_id, version, parent_version, author (`auto | user`), edl (JSONB), created_at. **Append-only.**
- `renders`: id, timeline_id, status, output_asset_id, settings_hash
- `jobs`: id, type, status (`queued | running | succeeded | failed | cancelled`), attempts, progress, input_hash, error, timestamps
- `audit_log`

**Project status:** `draft → master_ready → analyzed → has_takes → synced → exported`. The status is derived from children, not written ad hoc.

### 4.2 Browser event (NDJSON, one per line, gzip in object storage)

```json
{"take_id":"tk_1","seq":142,"t_ms":15234.5,"type":"click",
 "tab_id":812,"window_id":3,"frame_id":0,
 "url":"https://www.google.com/search?q=machine+learning+jobs",
 "title":"machine learning jobs - Google Search",
 "target":{"role":"link","name":"Machine Learning Jobs - Indeed","selector":"#rso a:nth-of-type(1)","bbox":[312,418,640,24]},
 "viewport":{"w":1903,"h":969,"dpr":1}}
```

- `t_ms` is relative to the take's first video frame (see §5.3).
- Types: `tab_activated, tab_created, tab_closed, window_focus, navigation_committed, page_loaded, history_back, history_forward, click, input, submit, scroll, key_shortcut, beat_marker`.
- `input` events carry `value_masked` by default (`"•••••"` + length). Plaintext is allowed only for search boxes the user opts in, and **never** for `type=password`, `autocomplete=cc-*`, or fields matching OTP/SSN patterns.

### 4.3 EDL (the central contract)

```json
{
  "schema": "edl/1",
  "version": 3,
  "master": {"asset_id":"as_master","duration_ms":184200},
  "output": {"width":1920,"height":1080,"fps":30},
  "layout": {
    "pip": {"corner":"bottom-left","width_pct":0.22,"margin_px":32,"radius_px":24,"visible":true},
    "browser_fit": "contain",
    "background": "#0F0F10"
  },
  "audio": {"master_gain_db":0,"browser":{"enabled":false,"gain_db":-18},"loudnorm_lufs":-14},
  "segments": [
    {"id":"sg_01","out":[0,6400],"kind":"face","origin":"auto"},
    {"id":"sg_02","out":[6400,14100],"kind":"browser","beat_id":"bt_02",
     "source":{"take_id":"tk_1","pieces":[
        {"in":[12030,15200],"speed":1.0},
        {"in":[16900,19870],"speed":1.12}
     ]},
     "fill":{"type":"hold_last_frame"},
     "confidence":0.91,"flags":[],"locked":false,"origin":"auto"},
    {"id":"sg_03","out":[14100,21000],"kind":"hold","source":{"take_id":"tk_1","at":19870},
     "flags":["missing_footage"],"origin":"auto"}
  ]
}
```

**Invariants (enforced by a validator in `core/edl`, run on every write):**
1. Segments tile `[0, master.duration_ms]` exactly, with no gaps or overlaps.
2. Every boundary is snapped to the output frame grid. Total frames = `round(duration × fps)`, so there is no A/V drift.
3. For each browser segment: `Σ(piece_duration / speed) + hold ≤ out_duration` and the remainder is filled per `fill`.
4. `0.5 ≤ speed ≤ 4.0`. Any speed above the "comfort cap" (default 1.75×, or 3× while typing) adds a `heavy_retime` flag.
5. Source ranges lie within the take's duration.

Segment kinds: `browser` (pieces + fill), `hold` (freeze a frame), `face` (narrator full-screen, no PiP).

---

## 5. Browser extension

### 5.1 Capture strategy
- **MVP: window capture** via `getDisplayMedia` from an extension recorder page or offscreen document (`DISPLAY_MEDIA` reason), with the user picking the Chrome window. This captures tab switches naturally, including the tab strip, which viewers find useful. Request `frameRate: 30`, ideal 1920×1080, and `audio` only if the user enables browser audio.
- **Spike in Phase 0: tab-follow capture.** Use `chrome.tabCapture` per active tab, composited onto an `OffscreenCanvas` → `captureStream` → one continuous recording without browser chrome. Ship it only if re-targeting on tab switch works without a user gesture per tab.
- **Recording presets.** Before capture, offer to resize the window (`chrome.windows.update`) to a 16:9 viewport so output needs no letterboxing.
- **Teleprompter** opens in its own small popup window. It is not part of the captured window, so it never appears in the footage. In play-along mode it also plays the narration audio (headphones recommended. Mic capture is off, so nothing leaks).

### 5.2 Recording pipeline
- `MediaRecorder` → WebM (VP9 + Opus if audio), `timeslice` = 2 s.
- Chunks are buffered to **5 MB S3 multipart parts** and uploaded with presigned part URLs from the API. Every chunk is also written to **OPFS** until the server acknowledges it. After a crash, tab close or network loss, the take resumes or completes on restart.
- Hard limits (MVP): 30 min per take, 10 takes per project.
- A visible recording indicator plus extension badge, a pause/resume control, and auto-stop if the captured window closes.

### 5.3 Clock (one source of truth)
- All timestamps use **epoch ms with sub-ms precision**: `performance.timeOrigin + performance.now()`, computed in each context (content scripts, service worker, recorder).
- The recorder notes the epoch of the first frame using `requestVideoFrameCallback` on a monitoring `<video>` element (more accurate than the `MediaRecorder.onstart` event).
- **Sync flash calibration:** at take start, a content script shows a 2-frame full-viewport marker. Ingest detects it in the video, measures the real offset between event clock and video, and stores it in `takes.clock`. Target: residual error ≤ 1 frame.
- The server converts all events to `t_ms` relative to the first frame.

### 5.4 Events
- `chrome.tabs`, `chrome.windows` and `chrome.webNavigation` for tab, window and navigation events (these work even where content scripts can't run).
- Content scripts (`all_frames: true`) for click, input, submit and scroll. Scroll and input are throttled or debounced. Targets use the accessible role/name plus a short selector and bounding box (the bbox powers future auto-zoom).
- Batched POST every 2 s with seq numbers. The server dedupes by `(take_id, seq)`.
- Known blind spots to surface in the UI: `chrome://` pages, the Chrome Web Store, the built-in PDF viewer, and cross-origin iframes that block injection. Navigation and tab events still exist for these, but there are no clicks.

### 5.5 Pairing and auth
The web app calls the extension (`externally_connectable`, restricted to our domain) with a short-lived pairing token. The extension exchanges it for a scoped, refreshable session token that is valid only for takes/events/upload endpoints.

### 5.6 Permissions and Chrome Web Store
Permissions: `tabs`, `webNavigation`, `scripting`, `offscreen`, `storage`, host `<all_urls>`. Broad host access triggers a stricter review. Budget **1–3 weeks** for review, and have a privacy policy plus a single-purpose description ready. Distribute an unpacked or unlisted build to beta users before that.

---

## 6. Ingest and media normalization (worker: `ingest`)

For every uploaded master and take:
1. `ffprobe`, then validate container, codecs, duration and size limits (MVP: ≤ 30 min, ≤ 4 GB). Reject with a clear message.
2. **Normalize to a constant-frame-rate mezzanine.** Screen recordings are **variable frame rate**, and skipping this causes most sync bugs. Takes become H.264 CFR at output fps. The master is kept at its native fps (≤ 60).
3. Build **proxies**: 540p with a short GOP (every 15 frames) for snappy scrubbing in the editor.
4. Extract audio for ASR: 16 kHz mono WAV.
5. Generate editor assets: thumbnail sprite, waveform peaks JSON.
6. For takes: detect the sync flash, compute the clock offset, rebase event timestamps, then build **episodes** (§7.2) and the **activity curve** (per-frame visual change score) used for idle trimming.

Every task is idempotent: the output key is derived from `sha256(input) + task_version`, and the task skips if the output exists.

---

## 7. Sync engine (`services/core/sync`, worker: `sync`)

Pipeline: **Transcript → Beats · Events → Episodes · Score · Align · Retime · Flag → EDL**

### 7.1 Beats (from narration)
- ASR with word-level timestamps.
- An LLM splits the transcript into beats using a **closed intent vocabulary**: `navigate, search, type, click, scroll, switch_tab, back, open_result, explain (no action)`. It extracts entities (site/domain, query text, target label). The output is validated against JSON Schema and retried on failure. Results are cached by `hash(transcript, prompt_version, model)`.
- Beats are shown to the user (teleprompter, editor lane) and are editable: split, merge, change intent.

### 7.2 Episodes (from browser take)
Deterministic grouping of raw events into semantic actions:
- A navigation commit opens a new episode ending at `page_loaded` + settle.
- An input burst (gap < 1.5 s) followed by `submit` becomes one `search`/`type` episode.
- Consecutive scroll events (gap < 1 s) become one `scroll` episode.
- Tab activation becomes a `switch_tab` episode.
- In guided/play-along modes, `beat_marker` events become hard episode boundaries tagged with `beat_id`.

Each episode has `[start,end]`, a type, entities (domain, title, query, clicked label), and a keyframe at the end.

### 7.3 Scoring `s(beat, episode-span)`
Weighted sum, with weights tuned on the golden set:
- **Type compatibility** (lookup table)
- **Entity match:** fuzzy match of query text, domain and target label (rapidfuzz)
- **Semantic score:** LLM judgment, **only for the top-K (≤ 5) candidates per beat** to control cost
- **Visual evidence (optional):** OCR of the episode-end keyframe contains the query or title. Used only to break ties
- **Mode prior:** in play-along mode, a strong prior that the episode's time ≈ the beat's time. In guided mode, the beat_marker tag is near-certain

### 7.4 Global alignment
**Monotonic dynamic programming** (DTW/Needleman-Wunsch-style) over beats × episodes:
- A beat may map to a **span of consecutive episodes** (e.g. "search for ML jobs" = navigate + type + submit + results).
- Skips are allowed. An unmatched beat becomes `missing_footage`; an unmatched episode is dropped (off-script browsing).
- Order is preserved by default. Out-of-order recording is handled by the user in the editor, or by recording a dedicated take.
- **Locked segments are fixed anchors** on re-sync. The DP runs only between them.
- Multiple takes: candidates come from all takes. A newer take wins ties, which supports "redo just this action".

### 7.5 Retiming (pure, deterministic)
Target window for beat *i* = `[beat_i.start − lead, beat_{i+1}.start − lead]` (default lead 200 ms, so the action appears as it's spoken). Given the source clip duration *C* and window *W*:
1. `C ≤ W`: play at 1×, then fill with `hold_last_frame`. If the hold exceeds 4 s, suggest "face" for the remainder.
2. `C > W`: **trim idle ranges** (activity score below threshold for > 500 ms: spinners, blank loading, mouse wandering) →
3. still `> W`: **uniform speed-up** up to the comfort cap (1.75×; 3× inside typing episodes) →
4. still `> W`: jump-cut the middle of the longest remaining piece and add the `heavy_retime` flag.

### 7.6 Confidence and flags
`confidence = f(match score, retime severity, clock-calibration quality)`. A segment is flagged when confidence < τ (default 0.7), or for `missing_footage`, `heavy_retime`, `order_violation` or `low_clock_quality`. Flagged segments are listed in the editor, and export warns if any remain unreviewed.

### 7.7 Quality targets (measured on the golden set in CI)
| Mode | Correct beat→episode match | Median timing error | Silent errors* |
|---|---|---|---|
| Play-along | ≥ 97% | ≤ 150 ms | ≤ 1% |
| Guided | ≥ 95% | ≤ 250 ms | ≤ 2% |
| Free-form | ≥ 80% | ≤ 400 ms | ≤ 5% |

\*Wrong match with confidence ≥ τ. **This is the metric that matters most**, because it measures what the user won't catch.

---

## 8. Rendering (`services/core/ffmpeg_graph`, worker: `render`)

**Strategy: per-segment composition, then concat, then mux audio.**
1. For each segment, build a small ffmpeg graph that outputs the **fully composed** video for that segment: browser pieces (`trim`, `setpts=(PTS-STARTPTS)/speed`, `concat`, `tpad=stop_mode=clone` for holds), scaled `contain` into 1920×1080 on the background, and the master's matching range scaled to the PiP with a rounded-corner alpha mask, overlaid at bottom-left. `face` segments show the master full-frame.
   - All segments share identical encode params: libx264 `-preset medium -crf 20`, `yuv420p`, CFR, same timebase, and an IDR at segment start.
   - Output is cached by `hash(segment spec + asset hashes + layout + encoder version)`. **After an edit, re-export re-renders only the changed segments.**
2. Join the segments with the concat demuxer (`-c copy`).
3. Audio track: master audio (+ optional browser audio retimed per the same EDL, mixed at `gain_db`), then `loudnorm` to −14 LUFS, encoded as AAC 48 kHz 192 kbps.
4. Mux with `-movflags +faststart`.
5. **Post-render assertions** (ffprobe): video duration = audio duration = master duration ± 1 frame, expected fps/resolution/codec, no missing frames. Fail the job if any assertion fails.

Segments are independent, so they can render in parallel across workers later.

---

## 9. Review editor (web)

**Lanes:** transcript words + waveform · beats (intent chips) · segments (colored by confidence, flagged ones highlighted) · source take filmstrip.

**Preview:** a client-side compositor using two `<video>` elements on proxies, driven by the EDL. Each piece is seeked and given a `playbackRate`, holds are a paused frame, and the PiP is a CSS overlay. The preview is frame-approximate, so for an exact check there is a **"Draft render"** (540p, fast preset) that reuses the same server pipeline.

**Segment actions:** pick from the alternative candidates the matcher already ranked (top 3) · drag edges to nudge · edit source in/out · change speed or fill · convert to face-only or hold · lock · "re-record this beat" (opens the extension in guided mode with only that beat).

**Global:** PiP corner/size/visibility, browser-audio toggle and gain, re-sync (preserves locks), version history with restore (timelines are append-only), export.

**State:** Zustand store holding the EDL draft. Every change runs through the same validator compiled from the JSON Schema (plus invariant checks mirrored in TS). Autosave is debounced and creates a new `timelines` version with `author=user`.

---

## 10. API surface (FastAPI, OpenAPI → generated TS client)

```
POST   /projects                          GET /projects/{id}
POST   /projects/{id}/uploads             → presigned multipart init (master)
POST   /uploads/{id}/parts  · /complete
POST   /projects/{id}/takes               → take + upload session (extension)
POST   /takes/{id}/events:batch           (idempotent by seq)
POST   /takes/{id}/complete
GET    /projects/{id}/beats               PATCH /beats/{id}
POST   /projects/{id}/sync                → job
GET    /projects/{id}/timelines?version=  POST /projects/{id}/timelines (new version)
POST   /timelines/{id}/renders            → job (draft | final)
GET    /jobs/{id}                         GET /projects/{id}/events  (SSE: job progress)
POST   /extension/pair                    DELETE /projects/{id} (hard delete + storage purge)
```

Conventions: `Idempotency-Key` header on all POSTs that start jobs, cursor pagination, RFC 7807 error bodies, per-user rate limits and quotas (minutes processed per month).

---

## 11. Security and privacy

- **Data minimization:** no keystroke logging. Inputs are masked by default with a hard denylist for passwords/cards/OTP. No cookies, storage or DOM snapshots are collected. Mic is off unless voice features (v1.1) are enabled.
- **The narrator's face and voice are personal data.** Encrypt at rest (provider SSE), use TLS everywhere, presigned URLs with ≤ 15 min TTL, and private buckets only.
- **Retention:** raw takes and proxies are auto-deleted 30 days after export (configurable). Exports are kept until the user deletes them. "Delete project" purges storage synchronously and is audited.
- **Third-party processors:** ASR and LLM providers are configured for zero or limited data retention where available, and listed in the privacy policy. Only text (transcript, event entities) goes to the LLM, never video frames by default.
- **Tenant isolation:** every query is scoped by `user_id` at the repository layer, with tests for IDOR on every endpoint.
- **Extension hardening:** strict CSP, no remote code, `externally_connectable` locked to our origin, and the token stored in `chrome.storage.session`.
- **Visible capture state** at all times (badge, window indicator, teleprompter header).
- **Later:** a blur/redaction tool for sensitive regions (emails, client names on Upwork pages). The event bboxes make semi-automatic redaction feasible.

---

## 12. Infrastructure and operations

- **Environments:** local (docker-compose: postgres, redis, minio, api, worker) · preview (per-PR web on Vercel, shared staging backend) · staging · prod.
- **Worker sizing:** render workers on CPU-optimized instances with ≥ 50 GB ephemeral scratch disk, concurrency 1–2 per instance. Autoscale on queue depth. ASR is hosted to begin with, so no GPUs.
- **Reliability:** job retries with exponential backoff (max 3). Poison jobs move to a dead-letter queue and alert. A heartbeat plus a stuck-job reaper. Graceful worker shutdown requeues in-flight work.
- **Observability:** one trace ID flows from the browser through API to worker. Dashboards cover queue depth, p50/p95 per stage, render success rate, sync flag rate and cost per exported minute. Alerts fire on failure rate > 2% or queue wait > 5 min.
- **Cost controls:** LLM only on top-K candidates, plus caching. Proxies replace originals in the editor. Segment render cache. Per-plan minute quotas.
- **Backups:** Postgres PITR. Object storage versioning on the exports bucket.

---

## 13. Testing strategy

| Level | What | Tooling |
|---|---|---|
| Unit | EDL validator, retiming solver, DP alignment, episode builder, ffmpeg graph builder (string snapshot) | pytest, hypothesis (property tests: tiling invariant, frame snapping) |
| Golden sync eval | 20–30 fixture projects across all modes (ground-truth alignments hand-labeled). Reports match accuracy, timing error and silent-error rate. **CI fails on regression** | custom harness in `/fixtures` |
| Golden render | Render fixture EDLs, then assert ffprobe properties and compare sampled frames by SSIM against references | pytest + ffmpeg |
| API / integration | Endpoints with real Postgres/MinIO in containers. IDOR tests | pytest + testcontainers |
| Extension E2E | Load the unpacked extension in Chromium, run a scripted browsing session, assert the event log and uploaded take | Playwright |
| Web E2E | Upload → sync → edit → export happy path, plus flagged-segment fix | Playwright |
| Resilience | Kill a worker mid-render, drop network mid-upload, close the tab mid-take | scripted chaos tests in staging |
| Media matrix | Masters at 24/25/29.97/30/60 fps, portrait/landscape, VFR phone video, 1 min vs 30 min | golden render suite |

---

## 14. Roadmap

Estimates assume **one senior full-stack dev**. With two devs (one frontend/extension, one backend/media), expect roughly 60% of the calendar time. These are rough figures to be revisited after Phase 0.

| Phase | Scope | Exit criteria | Est. |
|---|---|---|---|
| **0. Foundations + spikes** | Monorepo, CI, docker-compose, auth choice, schemas package + codegen. Spikes: window vs tab-follow capture, clock/flash calibration accuracy, ffmpeg per-segment render from a **hand-written EDL** | Hand-written EDL + two files → correct MP4. Measured clock offset ≤ 1 frame. Capture approach decided | 1.5 wk |
| **1. Media core** | Presigned multipart upload, ingest/normalize/proxies, EDL validator, render worker (segments, concat, audio, assertions), SSE progress, download | Golden render suite green across the fps/aspect matrix | 2 wk |
| **2. Capture extension** | Recorder, chunked upload + OPFS recovery, events + masking, pairing, takes, presets, teleprompter, play-along and guided modes, beat markers | 20-min take with 10+ tab switches: no lost chunks after a forced crash, event offset ≤ 100 ms | 2.5 wk |
| **3. Sync engine** | ASR adapter, beat extraction, episodes, scoring, DP alignment, retiming, flags, golden-set harness | Meets §7.7 targets for play-along and guided. Free-form ≥ 70% (improved later) | 3 wk |
| **4. Review editor** | Lanes, preview compositor, segment actions, layout and audio controls, versions, re-sync with locks, draft render, re-record a single beat | A test user fixes 3 flagged segments and exports in < 5 min without help | 2.5 wk |
| **5. Hardening + beta** | Quotas, rate limits, retention jobs, Sentry/OTel dashboards, security review, privacy policy, Web Store submission, onboarding | 10 beta users, render success ≥ 98%, no P1 bugs open for 1 week | 2 wk |
| | | **Total MVP** | **~13.5 wk** |

### Post-MVP (prioritize with beta data)
0. **Outreach pack** (highest priority if the primary persona holds):
   - **Templates:** clone a project's narration, beats and layout. Record only the new take, and auto-sync with that template's locked segments as anchors. Target: a new prospect video in under 3 minutes of user time.
   - **Per-prospect text overlays** (prospect name/company title card, lower third). Use text only, **no voice cloning or lip-sync changes**: the narrator's real footage stays real (principle 2).
   - **Hosted share page** on the user's own (sub)domain with their own branding: video player, view analytics (play, watch %), and a CTA or embedded booking widget. **Don't copy Loom's or any other brand's UI or name.** It's a trademark and trust risk, and in our case an impersonation risk. Leave platform-ToS questions (e.g. Upwork off-platform contact) to the user, with a setting to hide contact info.
1. **Voice commands** (fixed grammar first: "open Google", "search for …", "scroll down", "next tab"). Uses Web Speech API or streaming ASR in the offscreen doc, with mic audio never mixed into output.
2. **Auto-zoom and cursor emphasis** on clicks, using the event bboxes (Screen Studio-style).
3. **Redaction / blur** of sensitive regions.
4. **Autopilot takes:** generate an action plan from the beats and run it with Playwright in a recorded browser, timed to the narration. Fully automatic footage for public sites (logins remain manual).
5. Burned-in captions from the transcript, intro/outro cards, brand kit.
6. Parallel segment rendering, hardware encoding.
7. Desktop app (Tauri) for non-Chrome capture and local-only processing.

---

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Free-form alignment is unreliable | Core promise fails | Play-along/guided modes as the default path, flag-don't-fake policy, silent-error metric in CI, cheap re-record of a single beat |
| VFR / clock drift causes visible desync | Output looks broken | CFR normalization at ingest, flash calibration, frame-grid snapping, post-render assertions |
| Chrome capture API limits (tab switching, gestures, MV3 lifetimes) | Capture gaps | Window capture for MVP, Phase-0 spike for tab-follow, offscreen document keeps recorder alive, OPFS buffering |
| Web Store review delay or rejection | Launch slip | Minimal permissions, clear single purpose, privacy policy ready, unlisted beta channel early |
| Sensitive data in footage/events | Trust and legal exposure | Masking by default, no video sent to LLMs, retention auto-delete, redaction on roadmap |
| Render cost/time on long videos | Slow UX, cost overrun | Segment cache, draft renders on proxies, quotas, parallel segments later |
| LLM output variance | Non-reproducible sync | Closed vocabulary, schema validation, caching by input hash, LLM limited to scoring (DP decides) |
| Website differs between narration and recording (logins, A/B layouts) | Mismatched visuals | Match on semantics, not pixels. User can re-record a beat. Visual evidence used only as a tiebreaker |

---

## 16. Open decisions (needed before Phase 0)

1. **Hosted SaaS or local-first?** This plan assumes hosted (web + extension + cloud workers). If privacy or upload size dominates, a desktop app (Tauri + local ffmpeg) changes the architecture significantly.
2. **Primary use case and length.** The reference video points to short outreach videos (1–5 min, high volume), and this plan now leans that way. Confirm, because it drives limits, render infra, editor depth, and whether the Outreach pack (§14) moves into the MVP.
   - Out of scope either way: proposal writing, call notes and SOW generation (the other parts of that video's system). They're separate products. Integrate with them later if needed instead of rebuilding them.
3. **Is play-along acceptable as the default recording mode?** It's the biggest lever on sync quality.
4. **Auth provider and billing** (Clerk vs Auth.js; Stripe now or later).
5. **Team size and target launch date**, which recalibrate §14.
