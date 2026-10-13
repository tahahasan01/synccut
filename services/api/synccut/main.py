"""SyncCut v0 API."""

from __future__ import annotations

import copy
import logging
import shutil
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import media, pipeline
from .claude_client import credential_kind
from .config import settings
from .core.actions import validate_actions
from .core.edl import validate
from .core.subtitles import parse_subtitles
from .core.timeline import DEFAULT_LAYOUT, apply_fit, finalize, take_clips
from .jobs import Jobs
from .netguard import BlockedURL, check_url
from .store import NotFound, Store, new_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = Store(settings.data_dir)
jobs = Jobs(store)
app = FastAPI(title="SyncCut API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.web_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Files under /media come from users and from captured third-party sites. Serve them as
# inert data: no MIME sniffing, and a sandboxed, script-free CSP if one is ever opened as
# a document. (They still load normally as <img>/<video> in the web app.)
MEDIA_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def harden_media(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/media/"):
        response.headers.update(MEDIA_HEADERS)
    else:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response
app.mount("/media", StaticFiles(directory=store.projects_dir), name="media")
app.mount("/stage", StaticFiles(directory=Path(__file__).parent / "stage"), name="stage")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


@app.on_event("startup")
def _recover() -> None:
    jobs.recover()


def _project(pid: str) -> dict:
    try:
        return store.get(pid)
    except NotFound:
        raise HTTPException(404, "Project not found")


def _update(pid: str, fn) -> dict:
    try:
        return store.update(pid, fn)
    except NotFound:
        raise HTTPException(404, "Project not found")


def _busy(project: dict, job_type: str) -> bool:
    return any(j["type"] == job_type and j["status"] in ("queued", "running") for j in project["jobs"])


# health ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def _whisper_status() -> dict:
    try:
        import faster_whisper  # noqa: F401
        return {"ok": True, "model": settings.whisper_model}
    except (ImportError, OSError) as exc:
        return {
            "ok": False,
            "error": "Local Whisper can't load. Install the Microsoft Visual C++ Redistributable "
                     "(`winget install Microsoft.VCRedist.2015+.x64`) and restart the API.",
            "detail": str(exc)[:300],
        }


@app.get("/api/health")
def health() -> dict:
    try:
        ffmpeg_ok = bool(media.run([media.FFMPEG, "-version"]).stdout)
    except Exception:
        ffmpeg_ok = False
    return {
        "ok": True,
        "ffmpeg": ffmpeg_ok,
        "whisper": _whisper_status(),
        "claude": {"configured": credential_kind() is not None, "credential": credential_kind(), "model": settings.claude_model},
    }


# projects --------------------------------------------------------------------


class ProjectIn(BaseModel):
    name: str = Field("", max_length=120)


def _summary(p: dict) -> dict:
    ready_render = next((r for r in p["renders"] if r["status"] == "ready" and r["preset"] == "final"), None)
    return {
        "id": p["id"],
        "name": p["name"],
        "updated_at": p["updated_at"],
        "has_master": bool(p["master"]),
        "beats": len(p["beats"]),
        "takes": len([t for t in p["takes"] if t["status"] == "ready"]),
        "exported": bool(ready_render),
        "share_slug": p["share"]["slug"] if p["share"].get("published") else None,
        "mode": p.get("mode", "generate"),
        "captured": bool(p.get("capture")),
        "synced": bool(p.get("timeline")),
        "duration_ms": ((p.get("master") or {}).get("probe") or {}).get("duration_ms"),
    }


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [_summary(p) for p in store.list()]


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn) -> dict:
    return store.create(body.name)


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _project(pid)


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, body: ProjectIn) -> dict:
    return _update(pid, lambda p: p.update(name=body.name.strip() or p["name"]))


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str) -> None:
    try:
        store.delete(pid)
    except NotFound:
        raise HTTPException(404, "Project not found")


# narration -------------------------------------------------------------------


@app.post("/api/projects/{pid}/master")
def upload_master(pid: str, file: UploadFile = File(...)) -> dict:
    project = _project(pid)
    if _busy(project, "analyze"):
        raise HTTPException(409, "The narration is still being analyzed.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type {ext or '(none)'}. Use MP4, MOV, WebM or MKV.")

    master_dir = store.project_dir(pid) / "master"
    if master_dir.exists():
        shutil.rmtree(master_dir)
    master_dir.mkdir(parents=True)
    dest = master_dir / f"original{ext}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out, 1 << 20)
    if dest.stat().st_size > settings.max_upload_mb * 1024 * 1024:
        dest.unlink()
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")

    def reset(p: dict) -> None:
        p["master"] = {"filename": file.filename, "path": f"master/original{ext}", "probe": None, "uploaded_at": time.time()}
        p["transcript"], p["beats"], p["beats_source"] = None, [], None
        p["timeline"], p["timeline_versions"] = None, []
        p["actions"], p["actions_source"], p["capture"], p["browser_video"] = [], None, None, None

    _update(pid, reset)
    _start_analyze(pid)
    return _project(pid)


def _start_prepare(pid: str, replan: bool) -> dict:
    return jobs.start(pid, "prepare", lambda ctx: pipeline.prepare(store, ctx, replan), "Plan actions & capture pages")


def _after_transcript(pid: str) -> None:
    """In generated mode the browser plan follows the transcript automatically."""
    if store.get(pid).get("mode") == "generate":
        # save_transcript already planned the actions (in parallel with the steps),
        # so this only plans again if that found nothing.
        _start_prepare(pid, replan=False)


def _start_analyze(pid: str) -> dict:
    return jobs.start(
        pid, "analyze", lambda ctx: pipeline.analyze_master(store, ctx, on_done=lambda: _after_transcript(pid)), "Analyze narration"
    )


@app.post("/api/projects/{pid}/analyze")
def reanalyze(pid: str) -> dict:
    project = _project(pid)
    if not project["master"]:
        raise HTTPException(400, "Upload a narration video first.")
    if _busy(project, "analyze"):
        raise HTTPException(409, "Already analyzing.")
    return _start_analyze(pid)


@app.post("/api/projects/{pid}/subtitles")
async def import_subtitles(pid: str, file: UploadFile = File(...)) -> dict:
    """Use an SRT/VTT file instead of transcribing (e.g. when Whisper isn't available)."""
    project = _project(pid)
    if not project["master"] or not (project["master"].get("probe")):
        raise HTTPException(400, "Upload the narration video first.")
    if _busy(project, "analyze"):
        raise HTTPException(409, "The narration is still being analyzed.")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    words = parse_subtitles(text)
    if not words:
        raise HTTPException(422, "No timed captions found. Use an .srt or .vtt file.")
    result = {"words": words, "text": " ".join(w["w"] for w in words), "language": "en", "model": f"subtitles:{file.filename}"}

    # Respond at once; Claude runs as a job so the request (and the event loop) never waits on it.
    def run(ctx) -> None:
        ctx.progress(0.15, "Grouping steps and planning browser actions" + (" with Claude" if credential_kind() else ""), force=True)
        pipeline.save_transcript(store, pid, result)
        _after_transcript(pid)

    jobs.start(pid, "analyze", run, "Read subtitles")
    return _project(pid)


# generated browser mode ----------------------------------------------------------


class ModeIn(BaseModel):
    mode: Literal["generate", "record"]


@app.put("/api/projects/{pid}/mode")
def set_mode(pid: str, body: ModeIn) -> dict:
    return _update(pid, lambda p: p.update(mode=body.mode))


class PageIn(BaseModel):
    url: str = Field("", max_length=2000)

    @field_validator("url")
    @classmethod
    def public_web_url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and "://" not in v:
            v = f"https://{v}"
        v = web_url_or_error(v)
        if v:
            try:
                check_url(v)
            except BlockedURL as exc:
                raise ValueError(str(exc))
        return v


@app.put("/api/projects/{pid}/page")
def set_page(pid: str, body: PageIn) -> dict:
    """The page the video is about: the user's site, or the job posting they're replying to.
    Changing it re-plans the browser actions when there is already a transcript."""
    project = _project(pid)
    if project.get("page_url", "") == body.url:
        return project
    updated = _update(pid, lambda p: p.update(page_url=body.url, page_shot=None))  # a screenshot belongs to its link
    if updated.get("transcript") and updated.get("mode") == "generate" and not _busy(updated, "prepare"):
        _start_prepare(pid, replan=True)
        updated = _project(pid)
    return updated


MAX_SHOT_BYTES = 25 * 1024 * 1024


@app.post("/api/projects/{pid}/page/screenshot")
async def upload_page_screenshot(pid: str, file: UploadFile = File(...)) -> dict:
    """A screenshot of the linked page, for sites that can't be captured (login walls, bot checks).
    Only verified PNG/JPEG/WebP images are accepted; the stored copy is re-encoded as JPEG."""
    from .capture import raster_type
    from .core.scene import VIEW_W

    project = _project(pid)
    if not project.get("page_url"):
        raise HTTPException(400, "Save the page link first.")
    body = await file.read(MAX_SHOT_BYTES + 1)
    if len(body) > MAX_SHOT_BYTES:
        raise HTTPException(413, "That screenshot is over 25 MB.")
    if raster_type(body) not in ("png", "jpg", "webp"):
        raise HTTPException(422, "Use a PNG, JPEG or WebP screenshot.")
    pdir = store.project_dir(pid) / "page"
    pdir.mkdir(parents=True, exist_ok=True)
    original = pdir / "upload.bin"
    original.write_bytes(body)
    out = pdir / "shot.jpg"
    try:
        # Scale to the browser's page width so it looks like the page rendered in that window.
        media.ffmpeg("-i", str(original), "-frames:v", "1", "-vf", f"scale={VIEW_W}:-2:flags=lanczos", "-q:v", "2", str(out), timeout=60)
        info = media.probe(out)
    except Exception:
        raise HTTPException(422, "Couldn't read that image.")
    finally:
        original.unlink(missing_ok=True)
    shot = {"path": "page/shot.jpg", "height": info["height"], "uploaded_at": time.time()}
    updated = _update(pid, lambda p: p.update(page_shot=shot))
    if updated.get("transcript") and updated.get("mode") == "generate" and not _busy(updated, "prepare"):
        _start_prepare(pid, replan=False)
        updated = _project(pid)
    return updated


@app.delete("/api/projects/{pid}/page/screenshot")
def delete_page_screenshot(pid: str) -> dict:
    (store.project_dir(pid) / "page" / "shot.jpg").unlink(missing_ok=True)
    updated = _update(pid, lambda p: p.update(page_shot=None))
    if updated.get("transcript") and updated.get("mode") == "generate" and not _busy(updated, "prepare"):
        _start_prepare(pid, replan=False)
        updated = _project(pid)
    return updated


class PrepareIn(BaseModel):
    replan: bool = False


@app.post("/api/projects/{pid}/prepare")
def start_prepare(pid: str, body: PrepareIn) -> dict:
    project = _project(pid)
    if not project.get("transcript"):
        raise HTTPException(400, "The narration needs a transcript first.")
    if _busy(project, "prepare"):
        raise HTTPException(409, "Already preparing the browser.")
    return _start_prepare(pid, body.replan)


class ActionIn(BaseModel):
    id: str | None = None
    type: Literal["navigate", "search", "scroll", "click", "new_tab", "switch_tab", "new_window", "switch_window", "back"]
    at_ms: float = Field(ge=0)
    url: str = Field("", max_length=2000)
    query: str = Field("", max_length=300)
    target: str = Field("", max_length=200)
    tab: int = 0
    spoken: str = Field("", max_length=300)
    source: str | None = None
    confidence: float = 1.0


class ActionsIn(BaseModel):
    actions: list[ActionIn] = Field(max_length=300)


@app.put("/api/projects/{pid}/actions")
def put_actions(pid: str, body: ActionsIn) -> dict:
    project = _project(pid)
    duration = (project["master"] or {}).get("probe", {}) or {}
    actions = validate_actions([a.model_dump() for a in body.actions], duration.get("duration_ms", 10**9))
    return _update(pid, lambda p: p.update(actions=actions, actions_source="user"))


@app.get("/api/projects/{pid}/scene")
def get_scene(pid: str) -> dict:
    project = _project(pid)
    scene = pipeline.scene_for(store, pid, project)
    if scene is None:
        raise HTTPException(404, "No captured pages yet.")
    return scene


class BeatIn(BaseModel):
    id: str | None = None
    text: str = ""
    label: str = ""
    intent: str = "explain"
    site: str = ""
    query: str = ""
    start_ms: float
    end_ms: float


class BeatsIn(BaseModel):
    beats: list[BeatIn]


@app.put("/api/projects/{pid}/beats")
def put_beats(pid: str, body: BeatsIn) -> dict:
    beats = sorted((b.model_dump() for b in body.beats), key=lambda b: b["start_ms"])
    for i, beat in enumerate(beats):
        if beat["end_ms"] <= beat["start_ms"]:
            raise HTTPException(422, f"Step {i + 1} ends before it starts.")
        if i and beat["start_ms"] < beats[i - 1]["start_ms"]:
            raise HTTPException(422, "Steps must be in order.")
        beat["id"] = beat["id"] or new_id("b")

    def apply(p: dict) -> None:
        p["beats"] = beats
        p["timeline_stale"] = bool(p["timeline"])

    return _update(pid, apply)


# takes -----------------------------------------------------------------------


class TakeIn(BaseModel):
    mode: Literal["guided", "play_along", "freeform"] = "guided"
    start_beat_idx: int = 0


@app.post("/api/projects/{pid}/takes", status_code=201)
def create_take(pid: str, body: TakeIn) -> dict:
    project = _project(pid)
    if not project["beats"]:
        raise HTTPException(400, "Analyze the narration before recording.")
    take = {
        "id": new_id("t"),
        "mode": body.mode,
        "start_beat_idx": max(0, min(body.start_beat_idx, len(project["beats"]) - 1)),
        "status": "recording",
        "created_at": time.time(),
        "path": None,
        "duration_ms": 0,
        "markers": [],
        "events": [],
        "idle": [],
        "error": None,
    }
    (store.project_dir(pid) / "takes" / take["id"] / "chunks").mkdir(parents=True)
    _update(pid, lambda p: p["takes"].append(take))
    return take


def _take(project: dict, tid: str) -> dict:
    take = next((t for t in project["takes"] if t["id"] == tid), None)
    if take is None:
        raise HTTPException(404, "Take not found")
    return take


@app.put("/api/projects/{pid}/takes/{tid}/chunks/{seq}", status_code=204)
async def upload_chunk(pid: str, tid: str, seq: int, request: Request) -> None:
    take = _take(_project(pid), tid)
    if take["status"] != "recording":
        raise HTTPException(409, "This take is no longer recording.")
    data = await request.body()
    (store.project_dir(pid) / "takes" / tid / "chunks" / f"{seq:06d}.webm").write_bytes(data)


class MarkerIn(BaseModel):
    beat_id: str
    epoch_ms: float


class CompleteIn(BaseModel):
    rec_start_epoch_ms: float
    markers: list[MarkerIn] = []
    events: list[dict] = []


@app.post("/api/projects/{pid}/takes/{tid}/complete")
def complete_take(pid: str, tid: str, body: CompleteIn) -> dict:
    project = _project(pid)
    take = _take(project, tid)
    if take["status"] != "recording":
        raise HTTPException(409, "This take was already completed.")
    beat_ids = {b["id"] for b in project["beats"]}
    t0 = body.rec_start_epoch_ms
    markers = [
        {"beat_id": m.beat_id, "t_ms": round(m.epoch_ms - t0, 1)}
        for m in body.markers
        if m.beat_id in beat_ids and m.epoch_ms >= t0 - 1000
    ]
    events = []
    for event in body.events[:20000]:
        epoch = event.get("epoch_ms")
        if isinstance(epoch, (int, float)) and epoch >= t0 - 1000:
            events.append({**{k: v for k, v in event.items() if k != "epoch_ms"}, "t_ms": round(epoch - t0, 1)})

    def apply(p: dict) -> None:
        for t in p["takes"]:
            if t["id"] == tid:
                t.update(status="processing", markers=markers, events=events, rec_start_epoch_ms=t0)

    _update(pid, apply)

    def run(ctx) -> None:
        try:
            pipeline.process_take(store, ctx, tid)
        except Exception as exc:
            def fail(p: dict) -> None:
                for t in p["takes"]:
                    if t["id"] == tid and t["status"] != "ready":
                        t.update(status="failed", error=str(exc))
            store.update(pid, fail)
            raise

    return jobs.start(pid, "take", run, "Process recording")


@app.delete("/api/projects/{pid}/takes/{tid}", status_code=204)
def delete_take(pid: str, tid: str) -> None:
    project = _project(pid)
    _take(project, tid)
    used = project["timeline"] and any(s.get("take_id") == tid for s in project["timeline"]["segments"])

    def apply(p: dict) -> None:
        p["takes"] = [t for t in p["takes"] if t["id"] != tid]
        if used:
            p["timeline_stale"] = True

    _update(pid, apply)
    shutil.rmtree(store.project_dir(pid) / "takes" / tid, ignore_errors=True)


# timeline --------------------------------------------------------------------


@app.post("/api/projects/{pid}/sync")
def start_sync(pid: str) -> dict:
    project = _project(pid)
    if _busy(project, "sync"):
        raise HTTPException(409, "Already syncing.")
    return jobs.start(pid, "sync", lambda ctx: pipeline.sync(store, ctx), "Sync")


class ClipIn(BaseModel):
    in_ms: float
    out_ms: float


class SegmentPatch(BaseModel):
    kind: Literal["face", "browser", "hold"] | None = None
    take_id: str | None = None
    clip: ClipIn | None = None
    hold_at_ms: float | None = None
    locked: bool | None = None


def _newest_ready_take(project: dict) -> dict | None:
    ready = [t for t in project["takes"] if t["status"] == "ready"]
    return max(ready, key=lambda t: t["created_at"]) if ready else None


def _commit_timeline(pid: str, project: dict, timeline: dict) -> dict:
    errors = validate(timeline, {t["id"]: t for t in project["takes"]})
    if errors:
        raise HTTPException(422, "; ".join(errors[:5]))
    timeline["origin"] = "user"
    timeline["created_at"] = time.time()
    return pipeline.save_timeline(store, pid, timeline)


@app.patch("/api/projects/{pid}/timeline/segments/{sid}")
def patch_segment(pid: str, sid: str, body: SegmentPatch) -> dict:
    project = _project(pid)
    if not project["timeline"]:
        raise HTTPException(400, "Sync first.")
    timeline = copy.deepcopy(project["timeline"])
    seg = next((s for s in timeline["segments"] if s["id"] == sid), None)
    if seg is None:
        raise HTTPException(404, "Segment not found")
    takes = {t["id"]: t for t in project["takes"] if t["status"] == "ready"}

    if body.take_id is not None and body.take_id not in takes:
        raise HTTPException(422, "That take isn't ready.")
    content_change = any(v is not None for v in (body.kind, body.take_id, body.clip, body.hold_at_ms))
    kind = body.kind or seg["kind"]

    if kind == "face":
        seg.update(kind="face", take_id=None, clip=None)
    else:
        take = takes.get(body.take_id or seg.get("take_id") or "") or _newest_ready_take(project)
        if take is None:
            raise HTTPException(422, "Record a browser take first.")
        if kind == "browser":
            clip = body.clip.model_dump() if body.clip else None
            if clip is None and (seg["kind"] != "browser" or take["id"] != seg.get("take_id")):
                found = take_clips(take, [b["id"] for b in project["beats"]]).get(seg.get("beat_id") or "")
                clip = {"in_ms": found[0], "out_ms": found[1]} if found else {"in_ms": 0.0, "out_ms": take["duration_ms"]}
            seg.update(kind="browser", take_id=take["id"], clip=clip or seg["clip"])
        else:
            at = body.hold_at_ms
            if at is None:
                at = seg.get("hold_at_ms")
            if at is None and seg.get("pieces"):
                at = seg["pieces"][-1]["out_ms"]
            seg.update(kind="hold", take_id=take["id"], hold_at_ms=at or 0.0)

    if content_change:
        seg["flags"] = [f for f in seg.get("flags", []) if f not in ("missing_footage", "auto_guess")]
        seg["base_confidence"] = 1.0
        seg["origin"] = "user"
    seg["locked"] = body.locked if body.locked is not None else (True if content_change else seg.get("locked", False))
    apply_fit(seg, takes.get(seg.get("take_id") or ""), timeline["fps"])
    finalize(seg)
    return _commit_timeline(pid, project, timeline)


class LayoutPatch(BaseModel):
    pip_corner: Literal["top-left", "top-right", "bottom-left", "bottom-right"] | None = None
    pip_width_pct: float | None = Field(None, ge=0.1, le=0.45)
    pip_visible: bool | None = None
    pip_shape: Literal["circle", "rect"] | None = None
    camera_zoom: bool | None = None


@app.patch("/api/projects/{pid}/timeline/layout")
def patch_layout(pid: str, body: LayoutPatch) -> dict:
    project = _project(pid)
    changes = body.model_dump(exclude_none=True)
    project = _update(pid, lambda p: p.update(layout={**DEFAULT_LAYOUT, **(p.get("layout") or {}), **changes}))
    if not project["timeline"]:
        return project
    timeline = copy.deepcopy(project["timeline"])
    timeline["layout"] = {**DEFAULT_LAYOUT, **timeline.get("layout", {}), **changes}
    return _commit_timeline(pid, project, timeline)


@app.post("/api/projects/{pid}/timeline/undo")
def undo_timeline(pid: str) -> dict:
    project = _project(pid)
    if not project["timeline_versions"]:
        raise HTTPException(400, "Nothing to undo.")

    def apply(p: dict) -> None:
        p["timeline"] = p["timeline_versions"].pop()

    return _update(pid, apply)


# renders ---------------------------------------------------------------------


class RenderIn(BaseModel):
    preset: Literal["draft", "final"] = "final"


@app.post("/api/projects/{pid}/renders", status_code=201)
def start_render(pid: str, body: RenderIn) -> dict:
    project = _project(pid)
    generated = project.get("mode") == "generate"
    if generated and not project.get("capture"):
        raise HTTPException(400, "Capture the browser pages on the Actions tab first.")
    if not generated and not project["timeline"]:
        raise HTTPException(400, "Sync first.")
    if _busy(project, "render") or _busy(project, "prepare"):
        raise HTTPException(409, "Wait for the running job to finish.")
    rid = new_id("r")
    record = {
        "id": rid, "preset": body.preset, "status": "rendering", "path": None,
        "timeline_version": (project["timeline"] or {}).get("version"), "created_at": time.time(), "error": None,
    }
    _update(pid, lambda p: p["renders"].insert(0, record))

    def run(ctx) -> None:
        try:
            pipeline.render(store, ctx, rid, body.preset)
        except Exception as exc:
            def fail(p: dict) -> None:
                for r in p["renders"]:
                    if r["id"] == rid:
                        r.update(status="failed", error=str(exc))
            store.update(pid, fail)
            raise

    jobs.start(pid, "render", run, f"Render ({body.preset})")
    return record


# share page ------------------------------------------------------------------


class ShareIn(BaseModel):
    published: bool = False
    title: str = Field("", max_length=140)
    message: str = Field("", max_length=2000)
    cta_label: str = Field("Book a call", max_length=40)
    render_id: str | None = None


@app.put("/api/projects/{pid}/share")
def put_share(pid: str, body: ShareIn) -> dict:
    project = _project(pid)
    if body.published:
        render_id = body.render_id or next(
            (r["id"] for r in project["renders"] if r["status"] == "ready" and r["preset"] == "final"), None
        )
        if not render_id:
            raise HTTPException(400, "Export the final video before publishing the share page.")
    else:
        render_id = body.render_id

    def apply(p: dict) -> None:
        p["share"].update(body.model_dump(), render_id=render_id)

    return _update(pid, apply)


@app.get("/api/share/{slug}")
def get_share(slug: str) -> dict:
    try:
        project = store.find_by_slug(slug)
    except NotFound:
        raise HTTPException(404, "Not found")
    share = project["share"]
    render = next((r for r in project["renders"] if r["id"] == share.get("render_id") and r["status"] == "ready"), None)
    if not share.get("published") or not render:
        raise HTTPException(404, "Not found")
    return {
        "title": share["title"] or project["name"],
        "message": share["message"],
        "cta_label": share["cta_label"],
        "video_path": f"{project['id']}/{render['path']}",
        "poster_path": f"{project['id']}/{render['poster_path']}" if render.get("poster_path") else None,
        "brand": store.get_brand(),
    }


class BrandIn(BaseModel):
    name: str = Field("", max_length=80)
    headline: str = Field("", max_length=140)
    avatar_url: str = Field("", max_length=500)
    accent: str = Field("#4F46E5", pattern=r"^#[0-9a-fA-F]{6}$")
    booking_url: str = Field("", max_length=500)
    profile_url: str = Field("", max_length=500)
    rating_text: str = Field("", max_length=120)
    portfolio: list[dict] = Field(default_factory=list, max_length=12)

    @field_validator("avatar_url", "booking_url", "profile_url")
    @classmethod
    def _web_url(cls, value: str) -> str:
        return web_url_or_error(value)


def web_url_or_error(value: str) -> str:
    """Links shown on share pages must be http(s): a javascript: or data: URL in an
    href or iframe src would run script on the share page."""
    value = (value or "").strip()
    if value and urlparse(value).scheme.lower() not in ("http", "https"):
        raise ValueError("Use a full web address starting with https://")
    return value


@app.get("/api/brand")
def get_brand() -> dict:
    return store.get_brand()


@app.put("/api/brand")
def put_brand(body: BrandIn) -> dict:
    portfolio = []
    for item in body.portfolio:
        url = str(item.get("url", ""))[:500].strip()
        if not url:
            continue
        try:
            url = web_url_or_error(url)
        except ValueError as exc:
            raise HTTPException(422, f"Portfolio link “{url[:60]}”: {exc}")
        portfolio.append({"title": str(item.get("title", ""))[:80], "url": url})
    return store.put_brand({**body.model_dump(), "portfolio": portfolio})
