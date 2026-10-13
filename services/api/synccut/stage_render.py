"""Render the stage to video, frame-exactly: frame n is stage.seek(n / fps).

Speed: frames are split into contiguous chunks rendered in parallel (one browser
tab each), screenshots go through CDP with ``optimizeForSpeed``, unchanged frames
are reused, and the chunk files are joined without re-encoding.
"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .capture import chromium_executable
from .media import FFMPEG, MediaError, ffmpeg

ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def _workers(total_frames: int) -> int:
    configured = os.environ.get("SYNCCUT_RENDER_WORKERS")
    if configured:
        return max(1, int(configured))
    by_cpu = max(1, (os.cpu_count() or 2) // 2)
    by_length = max(1, total_frames // 150)  # not worth splitting a few seconds
    return min(4, by_cpu, by_length)


def _render_chunk(browser, stage_url: str, start: int, end: int, fps: int, out: Path, progress: Callable[[int], None]) -> int:
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-nostdin", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
         *ENCODE, "-r", str(fps), "-g", str(fps * 2), "-video_track_timescale", str(fps * 512), str(out)],
        stdin=subprocess.PIPE, stderr=log,
    )
    unique = 0
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page.goto(stage_url, wait_until="load", timeout=60000)
        page.wait_for_function("document.documentElement.dataset.ready === '1' || !!document.documentElement.dataset.error", timeout=120000)
        error = page.evaluate("document.documentElement.dataset.error || ''")
        if error:
            raise MediaError(f"stage failed to load: {error}")
        cdp = page.context.new_cdp_session(page)
        previous_sig, frame = None, b""
        for n in range(start, end):
            sig = page.evaluate("t => window.stage.seek(t)", n * 1000 / fps)
            if sig != previous_sig:
                shot = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 90, "optimizeForSpeed": True})
                frame = base64.b64decode(shot["data"])
                previous_sig = sig
                unique += 1
            proc.stdin.write(frame)
            progress(1)
        proc.stdin.close()
        code = proc.wait(timeout=600)
    except Exception:
        proc.kill()
        raise
    finally:
        page.close()
    if code != 0:
        log.seek(0)
        tail = log.read().decode(errors="replace").strip().splitlines()[-6:]
        raise MediaError("ffmpeg failed while encoding the browser video: " + " | ".join(tail))
    return unique


def render_stage(
    stage_url: str,
    total_frames: int,
    fps: int,
    out_path: Path,
    progress: Callable[[float, str], None],
) -> dict:
    from playwright.sync_api import sync_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workers = _workers(total_frames)
    bounds = [round(total_frames * i / workers) for i in range(workers + 1)]
    chunks = [out_path.with_name(f"{out_path.stem}.part{i}.mp4") for i in range(workers)]
    done = [0]
    lock = threading.Lock()
    started = time.monotonic()

    def tick(n: int) -> None:
        with lock:
            done[0] += n
            if done[0] % 15 == 0:
                progress(done[0] / total_frames, f"Drawing browser frame {done[0]} of {total_frames}")

    errors: list[BaseException] = []
    uniques = [0] * workers

    def run(i: int) -> None:
        # Playwright's sync API is bound to the thread that started it: one instance per worker.
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=chromium_executable(), headless=True)
                try:
                    uniques[i] = _render_chunk(browser, stage_url, bounds[i], bounds[i + 1], fps, chunks[i], tick)
                finally:
                    browser.close()
        except BaseException as exc:  # surfaced after join
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        for c in chunks:
            c.unlink(missing_ok=True)
        raise errors[0]

    if workers == 1:
        chunks[0].replace(out_path)
    else:
        listing = out_path.with_suffix(".txt")
        listing.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in chunks), encoding="utf-8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out_path))
        listing.unlink(missing_ok=True)
        for c in chunks:
            c.unlink(missing_ok=True)
    progress(1.0, "Browser video ready")
    return {"frames": total_frames, "unique_frames": sum(uniques), "workers": workers,
            "seconds": round(time.monotonic() - started, 1)}
