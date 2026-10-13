"""Job bodies: analyze narration, process a take, sync, render."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import hashlib
import json
from typing import Callable

from . import media
from .ai_actions import plan_actions
from .ai_beats import claude_beats
from .capture import capture_actions, capture_is_current
from .claude_client import credential_kind
from .config import settings
from .core.edl import validate
from .core.render import render_timeline
from .core.scene import build_scene
from .core.timeline import DEFAULT_LAYOUT, build_generated_timeline, build_timeline, ms_to_frame
from .jobs import JobContext
from .stage_render import render_stage
from .skin import load_skin
from .store import Store, new_id
from .transcribe import transcribe

log = logging.getLogger("synccut.pipeline")

MAX_TIMELINE_VERSIONS = 20


class PipelineError(RuntimeError):
    pass


def analyze_master(store: Store, ctx: JobContext, on_done: Callable[[], None] | None = None) -> None:
    _analyze_master(store, ctx)
    if on_done:
        on_done()


def save_transcript(store: Store, pid: str, result: dict) -> None:
    """Group the narration into steps and, in generated mode, plan the browser actions.

    Both are independent Claude calls on the same words, so they run in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor

    project = store.get(pid)
    duration = ((project.get("master") or {}).get("probe") or {}).get("duration_ms") or (
        result["words"][-1]["end_ms"] + 1000 if result["words"] else 0
    )
    generate = project.get("mode") == "generate"
    with ThreadPoolExecutor(max_workers=2) as pool:
        beats_job = pool.submit(claude_beats, result["words"])
        actions_job = pool.submit(plan_actions, result["words"], duration, project.get("page_url", "")) if generate else None
        beats, source = beats_job.result()
        actions, actions_source = actions_job.result() if actions_job else (None, None)

    def save(p: dict) -> None:
        p["transcript"] = result
        p["beats"] = beats
        p["beats_source"] = source
        p["timeline_stale"] = bool(p["takes"])
        if actions is not None:
            p["actions"], p["actions_source"] = actions, actions_source

    store.update(pid, save)


def _analyze_master(store: Store, ctx: JobContext) -> None:
    project = store.get(ctx.pid)
    pdir = store.project_dir(ctx.pid)
    master = project["master"]
    src = pdir / master["path"]

    ctx.progress(0.02, "Reading video", force=True)
    info = media.probe(src)
    if info["duration_ms"] <= 0:
        raise PipelineError("Could not read the video's duration.")
    if not info["has_audio"]:
        raise PipelineError("This video has no audio track, so there is no narration to sync to.")
    wav = pdir / "master" / "audio16k.wav"
    media.extract_wav(src, wav)

    def set_probe(p: dict) -> None:
        p["master"]["probe"] = info
        p["master"]["audio_path"] = "master/audio16k.wav"

    store.update(ctx.pid, set_probe)

    result = transcribe(wav, lambda f, m: ctx.progress(0.05 + 0.8 * f, m))
    if not result["words"]:
        raise PipelineError("No speech was found in the narration.")

    ctx.progress(0.88, "Splitting narration into steps" + (" with Claude" if credential_kind() else ""), force=True)
    save_transcript(store, ctx.pid, result)


# generated browser mode -----------------------------------------------------------


def prepare(store: Store, ctx: JobContext, replan: bool) -> None:
    """Plan browser actions from the narration (if asked or none yet), then capture the pages."""
    project = store.get(ctx.pid)
    if not project.get("transcript") or not project["master"] or not project["master"].get("probe"):
        raise PipelineError("The narration needs a transcript first.")
    duration = project["master"]["probe"]["duration_ms"]
    actions = project.get("actions") or []
    if replan or not actions:
        ctx.progress(0.02, "Planning browser actions" + (" with Claude" if credential_kind() else ""), force=True)
        actions, source = plan_actions(project["transcript"]["words"], duration, project.get("page_url", ""))
        store.update(ctx.pid, lambda p: p.update(actions=actions, actions_source=source))
    if not actions:
        raise PipelineError("No browser actions were found in the narration. Add them by hand on the Actions tab.")

    current = load_capture(store, ctx.pid, project)
    shots = page_screenshots(store, ctx.pid, project)
    if capture_is_current(current, actions, shots):
        ctx.progress(1.0, "Pages already captured", force=True)
        return

    run = new_id("c")
    out_dir = store.project_dir(ctx.pid) / "capture" / run / "pages"
    capture = capture_actions(actions, out_dir, lambda f, m: ctx.progress(0.08 + 0.9 * f, m), shots)
    (out_dir.parent / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    old = (project.get("capture") or {}).get("run")

    def save(p: dict) -> None:
        p["capture"] = {"run": run, "captured_at": time.time(), "pages": len(capture["pages"])}

    store.update(ctx.pid, save)
    if old and old != run:
        _rmtree(store.project_dir(ctx.pid) / "capture" / old)


def load_capture(store: Store, pid: str, project: dict) -> dict | None:
    run = (project.get("capture") or {}).get("run")
    if not run:
        return None
    path = store.project_dir(pid) / "capture" / run / "capture.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def page_screenshots(store: Store, pid: str, project: dict) -> dict[str, dict]:
    """The user's screenshot of their linked page, keyed by its URL, for capture to use instead of loading it."""
    shot, url = project.get("page_shot"), project.get("page_url")
    if not shot or not url:
        return {}
    return {url: {"path": store.project_dir(pid) / shot["path"], "height": shot["height"], "uploaded_at": shot["uploaded_at"]}}


def _wall_clock_ms(ts: float | None) -> float:
    """Local wall-clock time as milliseconds since the epoch *as if it were UTC*, so the
    stage can show the menu-bar clock with plain UTC getters and stay deterministic."""
    import calendar
    from datetime import datetime

    if not ts:
        return 0
    return calendar.timegm(datetime.fromtimestamp(ts).timetuple()) * 1000.0


def scene_for(store: Store, pid: str, project: dict) -> dict | None:
    capture = load_capture(store, pid, project)
    if capture is None or not project["master"] or not project["master"].get("probe"):
        return None
    layout = {**DEFAULT_LAYOUT, **(project.get("layout") or {})}
    scene = build_scene(project.get("actions") or [], capture, project["master"]["probe"]["duration_ms"],
                        camera=bool(layout.get("camera_zoom", False)), fps=settings.fps,
                        clock_ms=_wall_clock_ms((project.get("capture") or {}).get("captured_at")),
                        opening_url=project.get("page_url") or "",
                        skin=load_skin(settings.data_dir / "skins"),
                        dock=bool(layout.get("show_dock", True)))
    scene["stale"] = not capture_is_current(capture, project.get("actions") or [], page_screenshots(store, pid, project))
    return scene


def _generated_take(store: Store, ctx: JobContext, project: dict, progress: Callable[[float, str], None]) -> dict:
    """Draw the browser video for the current scene, reusing the last one if the scene is unchanged."""
    scene = scene_for(store, ctx.pid, project)
    if scene is None:
        raise PipelineError("Capture the pages on the Actions tab first.")
    if scene["stale"]:
        raise PipelineError("Actions changed since the pages were captured. Capture them again first.")
    key = hashlib.sha256(json.dumps(scene, sort_keys=True).encode()).hexdigest()[:24]
    existing = project.get("browser_video") or {}
    take = next((t for t in project["takes"] if t["id"] == existing.get("take_id")), None)
    if take and existing.get("scene_hash") == key and (store.project_dir(ctx.pid) / take["path"]).exists():
        progress(1.0, "Browser video unchanged")
        return take

    tid = existing.get("take_id") or new_id("t")
    rel = f"takes/{tid}/browser_{key[:8]}.mp4"
    out = store.project_dir(ctx.pid) / rel
    total = ms_to_frame(project["master"]["probe"]["duration_ms"], settings.fps)
    run = project["capture"]["run"]
    base = settings.api_base
    stage_url = (f"{base}/stage/index.html?mode=render&scene={base}/api/projects/{ctx.pid}/scene"
                 f"&assets={base}/media/{ctx.pid}/capture/{run}/")
    stats = render_stage(stage_url, total, settings.fps, out, progress)
    info = media.probe(out)
    take = {
        "id": tid, "mode": "generated", "start_beat_idx": 0, "status": "ready", "created_at": time.time(),
        "path": rel, "duration_ms": info["duration_ms"], "width": info["width"], "height": info["height"],
        "markers": [], "events": [], "idle": [], "error": None, "stats": stats,
    }
    old_path = take_path_of(project, tid)

    def save(p: dict) -> None:
        p["takes"] = [t for t in p["takes"] if t["id"] != tid] + [take]
        p["browser_video"] = {"scene_hash": key, "take_id": tid}

    store.update(ctx.pid, save)
    if old_path and old_path != rel:
        (store.project_dir(ctx.pid) / old_path).unlink(missing_ok=True)
    return take


def take_path_of(project: dict, tid: str) -> str | None:
    return next((t.get("path") for t in project["takes"] if t["id"] == tid), None)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def process_take(store: Store, ctx: JobContext, take_id: str) -> None:
    pdir = store.project_dir(ctx.pid)
    tdir = pdir / "takes" / take_id
    chunks = sorted((tdir / "chunks").glob("*.webm"))
    if not chunks:
        raise PipelineError("No video was received for this take.")

    ctx.progress(0.05, "Joining recording", force=True)
    raw = tdir / "raw.webm"
    media.concat_chunks(chunks, raw)
    ctx.progress(0.15, "Converting to constant frame rate", force=True)
    out = tdir / "take.mp4"
    media.normalize_take(raw, out, settings.fps)
    info = media.probe(out)
    ctx.progress(0.7, "Finding idle stretches", force=True)
    idle = media.detect_freezes(out, info["duration_ms"])

    def ready(p: dict) -> None:
        for take in p["takes"]:
            if take["id"] == take_id:
                take.update(
                    status="ready", path=f"takes/{take_id}/take.mp4", duration_ms=info["duration_ms"],
                    width=info["width"], height=info["height"], idle=idle, error=None,
                )

    store.update(ctx.pid, ready)
    for chunk in chunks:
        chunk.unlink(missing_ok=True)
    raw.unlink(missing_ok=True)

    ctx.progress(0.85, "Syncing to narration", force=True)
    sync(store, ctx)


def sync(store: Store, ctx: JobContext) -> None:
    project = store.get(ctx.pid)
    if not project["master"] or not project["master"].get("probe"):
        raise PipelineError("Upload and analyze the narration video first.")
    if not project["beats"]:
        raise PipelineError("The narration has no steps yet.")

    timeline = build_timeline(
        project["beats"],
        project["master"]["probe"]["duration_ms"],
        project["takes"],
        fps=settings.fps,
        previous=project["timeline"],
    )
    errors = validate(timeline, {t["id"]: t for t in project["takes"]})
    if errors:
        raise PipelineError("Generated timeline is invalid: " + "; ".join(errors[:5]))
    save_timeline(store, ctx.pid, timeline)


def save_timeline(store: Store, pid: str, timeline: dict) -> dict:
    def apply(p: dict) -> None:
        if p["timeline"]:
            p["timeline_versions"] = (p["timeline_versions"] + [p["timeline"]])[-MAX_TIMELINE_VERSIONS:]
            timeline["version"] = max(timeline["version"], p["timeline"]["version"] + 1)
        p["timeline"] = timeline
        p["timeline_stale"] = False

    return store.update(pid, apply)


def render(store: Store, ctx: JobContext, render_id: str, preset: str) -> None:
    project = store.get(ctx.pid)
    pdir = store.project_dir(ctx.pid)
    started = time.time()
    compose_from = 0.0
    if project.get("mode") == "generate":
        compose_from = 0.75
        take = _generated_take(store, ctx, project, lambda f, m: ctx.progress(compose_from * f, m))
        project = store.get(ctx.pid)
        scene = scene_for(store, ctx.pid, project) or {"issues": []}
        timeline = build_generated_timeline(
            project["beats"], project["master"]["probe"]["duration_ms"], take, project.get("actions") or [],
            scene["issues"], fps=settings.fps, layout={**DEFAULT_LAYOUT, **(project.get("layout") or {})},
            previous=project["timeline"],
        )
        errors = validate(timeline, {t["id"]: t for t in project["takes"]})
        if errors:
            raise PipelineError("Generated timeline is invalid: " + "; ".join(errors[:5]))
        project = save_timeline(store, ctx.pid, timeline)
    timeline = project["timeline"]
    if not timeline:
        raise PipelineError("Nothing to render yet: sync first.")
    takes = {t["id"]: t for t in project["takes"]}
    errors = validate(timeline, takes)
    if errors:
        raise PipelineError("Timeline is invalid: " + "; ".join(errors[:5]))

    out_rel = f"renders/{render_id}.mp4"
    out = pdir / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    result = render_timeline(
        timeline,
        master_path=pdir / project["master"]["path"],
        master_probe=project["master"]["probe"],
        take_paths={tid: pdir / t["path"] for tid, t in takes.items() if t.get("path")},
        out_path=out,
        work_dir=pdir / "renders" / f"{render_id}_work",
        cache_dir=store.cache_dir / "segments",
        preset_name=preset,
        progress=lambda f, m: ctx.progress(compose_from + (1 - compose_from) * f, m),
    )
    _cleanup(pdir / "renders" / f"{render_id}_work")
    poster_rel = f"renders/{render_id}.jpg"
    try:
        # A third of the way in, the browser is on a real page and the speaker is mid-sentence.
        media.poster(out, pdir / poster_rel, (result.get("duration_ms") or 0) / 1000 * 0.35)
    except Exception as exc:  # a missing poster only means the player shows frame 0
        log.warning("Poster frame failed: %s", exc)
        poster_rel = None

    def done(p: dict) -> None:
        for r in p["renders"]:
            if r["id"] == render_id:
                r.update(status="ready", path=out_rel, poster_path=poster_rel, probe=result, seconds=round(time.time() - started, 1),
                         timeline_version=timeline["version"])

    store.update(ctx.pid, done)


def _cleanup(directory: Path) -> None:
    for f in directory.glob("*"):
        f.unlink(missing_ok=True)
    directory.rmdir() if directory.exists() else None
