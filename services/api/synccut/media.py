"""Thin wrappers around ffmpeg/ffprobe."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

FFMPEG = os.environ.get("SYNCCUT_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("SYNCCUT_FFPROBE", "ffprobe")


class MediaError(RuntimeError):
    pass


def run(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise MediaError(f"{Path(args[0]).name} failed ({proc.returncode}): {tail}")
    return proc


def ffmpeg(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    return run([FFMPEG, "-hide_banner", "-nostdin", "-y", *args], timeout=timeout)


def _rate(value: str | None) -> float:
    if not value or value in ("0/0", "0"):
        return 0.0
    num, _, den = value.partition("/")
    return float(num) / float(den or 1)


def probe(path: str | Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(out.stdout)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError("no video stream found")

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(side["rotation"])
    rotation = rotation or int((video.get("tags") or {}).get("rotate", 0) or 0)
    if abs(rotation) % 180 == 90:  # ffmpeg auto-rotates on decode, so display size is swapped
        width, height = height, width

    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    return {
        "duration_ms": round(duration * 1000, 1),
        "width": width,
        "height": height,
        "fps": round(_rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")), 3),
        "video_codec": video.get("codec_name"),
        "has_audio": audio is not None,
        "nb_frames": int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
    }


def extract_wav(src: str | Path, dst: str | Path) -> None:
    ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst))


def normalize_take(src: str | Path, dst: str | Path, fps: int = 30) -> None:
    """Screen recordings are variable frame rate; convert to constant fps H.264."""
    ffmpeg(
        "-fflags", "+genpts", "-i", str(src),
        "-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", str(fps),
        "-an", "-movflags", "+faststart", str(dst),
    )


_FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*([\d.]+)")


def detect_freezes(path: str | Path, duration_ms: float, min_s: float = 0.6) -> list[list[float]]:
    """Stretches where the screen doesn't change at all (page loads, waiting).

    The noise threshold is deliberately strict: on a 1080p screen, typing one
    character or moving the cursor changes well under 0.1% of the picture, and
    that must not count as idle.
    """
    proc = run([
        FFMPEG, "-hide_banner", "-nostdin", "-i", str(path),
        "-vf", f"freezedetect=n=0.0001:d={min_s}", "-an", "-f", "null", "-",
    ])
    starts = [float(m) * 1000 for m in _FREEZE_START.findall(proc.stderr)]
    ends = [float(m) * 1000 for m in _FREEZE_END.findall(proc.stderr)]
    ranges = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration_ms
        ranges.append([round(start, 1), round(end, 1)])
    return ranges


def concat_chunks(chunks: list[Path], dst: Path) -> None:
    """MediaRecorder timeslice chunks are pieces of one WebM stream: join the bytes."""
    with open(dst, "wb") as out:
        for chunk in chunks:
            with open(chunk, "rb") as f:
                while block := f.read(1 << 20):
                    out.write(block)
