"""Render an EDL to MP4.

Each segment is composed on its own (browser footage + PiP, or face
full-screen), encoded with identical settings, cached by content hash, then
joined with the concat demuxer and muxed with the narration audio.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from ..media import MediaError, ffmpeg, probe

PRESETS = {
    "draft": {"width": 960, "height": 540, "crf": 30, "x264": "veryfast"},
    "final": {"width": 1920, "height": 1080, "crf": 20, "x264": "veryfast"},
}
BACKGROUND = "0x0F0F10"
CACHE_TAG = "seg-v1"

Progress = Callable[[float, str], None]


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def pip_geometry(layout: dict, master: dict, width: int, height: int) -> dict:
    if layout.get("pip_shape", "circle") == "circle":
        # The speaker as a round avatar: a centred square crop of their video.
        d = _even(width * float(layout.get("pip_width_pct", 0.22)) * 0.65)
        margin = max(12, round(width / 48))
        corner = layout.get("pip_corner", "bottom-left")
        x = f"{margin}" if "left" in corner else f"W-w-{margin}"
        y = f"{margin}" if corner.startswith("top") else f"H-h-{margin}"
        return {"w": d, "h": d, "radius": d // 2, "x": x, "y": y, "circle": True}
    pip_w = _even(width * float(layout.get("pip_width_pct", 0.22)))
    aspect = (master["height"] / master["width"]) if master.get("width") else 9 / 16
    pip_h = _even(pip_w * aspect)
    margin = max(8, round(width / 60))
    radius = max(4, round(min(pip_w, pip_h) * 0.1))
    corner = layout.get("pip_corner", "bottom-left")
    x = f"{margin}" if "left" in corner else f"W-w-{margin}"
    y = f"{margin}" if corner.startswith("top") else f"H-h-{margin}"
    return {"w": pip_w, "h": pip_h, "radius": radius, "x": x, "y": y}


def make_mask(path: Path, w: int, h: int, r: int) -> None:
    """Rounded-rectangle alpha mask for the PiP."""
    expr = (
        f"255*lte(hypot(max(0,max({r}-X,X-({w}-1-{r}))),"
        f"max(0,max({r}-Y,Y-({h}-1-{r})))),{r})"
    )
    ffmpeg("-f", "lavfi", "-i", f"color=c=white:s={w}x{h},format=gray",
           "-vf", f"geq=lum='{expr}'", "-frames:v", "1", str(path))


def segment_args(seg: dict, *, fps: int, preset: dict, layout: dict, pip: dict,
                 master_path: Path, take_path: Path | None, mask_path: Path, out: Path) -> list[str]:
    width, height = preset["width"], preset["height"]
    frames = seg["end_f"] - seg["start_f"]
    start_s = seg["start_f"] / fps
    dur_s = frames / fps
    pad_s = f"{dur_s + 1:.3f}"
    fit = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={BACKGROUND},setsar=1")

    args = ["-ss", f"{start_s:.3f}", "-t", f"{dur_s + 1:.3f}", "-i", str(master_path)]
    kind = seg["kind"]
    if kind == "face":
        graph = f"[0:v]fps={fps},{fit},tpad=stop_mode=clone:stop_duration={pad_s},format=yuv420p[v]"
    else:
        if take_path is None:
            raise MediaError(f"segment {seg['id']}: take footage missing")
        if kind == "browser":
            pieces = seg["pieces"]
            base = min(p["in_ms"] for p in pieces) / 1000
            span = max(p["out_ms"] for p in pieces) / 1000 - base
            args += ["-ss", f"{base:.3f}", "-t", f"{span + 0.5:.3f}", "-i", str(take_path)]
            parts = []
            for k, p in enumerate(pieces):
                a, b = p["in_ms"] / 1000 - base, p["out_ms"] / 1000 - base
                parts.append(f"[1:v]trim=start={a:.3f}:end={b:.3f},"
                             f"setpts=(PTS-STARTPTS)/{p['speed']}[p{k}]")
            joined = "".join(f"[p{k}]" for k in range(len(pieces)))
            graph = ";".join(parts) + (
                f";{joined}concat=n={len(pieces)}:v=1:a=0,fps={fps},"
                f"tpad=stop_mode=clone:stop_duration={pad_s},{fit}[bg]"
            )
        else:  # hold
            args += ["-ss", f"{seg['hold_at_ms'] / 1000:.3f}", "-i", str(take_path)]
            graph = (f"[1:v]trim=end_frame=1,setpts=PTS-STARTPTS,"
                     f"tpad=stop_mode=clone:stop_duration={pad_s},fps={fps},{fit}[bg]")

        if layout.get("pip_visible", True):
            crop = "crop=min(iw\\,ih):min(iw\\,ih)," if pip.get("circle") else ""  # square, centred on the speaker
            args += ["-loop", "1", "-i", str(mask_path)]
            graph += (
                f";[0:v]fps={fps},{crop}scale={pip['w']}:{pip['h']},setsar=1,"
                f"tpad=stop_mode=clone:stop_duration={pad_s},format=yuva420p[pc]"
                f";[2:v]format=gray,scale={pip['w']}:{pip['h']}[m]"
                f";[pc][m]alphamerge[pip]"
                f";[bg][pip]overlay=x={pip['x']}:y={pip['y']}:shortest=1,format=yuv420p[v]"
            )
        else:
            graph += ";[bg]format=yuv420p[v]"

    return args + [
        "-filter_complex", graph, "-map", "[v]", "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", preset["x264"], "-crf", str(preset["crf"]),
        "-pix_fmt", "yuv420p", "-r", str(fps), "-video_track_timescale", str(fps * 512),
        "-an", str(out),
    ]


def _fingerprint(path: Path | None) -> str | None:
    if path is None:
        return None
    st = path.stat()
    return f"{path.resolve()}:{st.st_size}:{st.st_mtime_ns}"


def segment_key(seg: dict, **context) -> str:
    spec = {k: seg.get(k) for k in ("kind", "start_f", "end_f", "pieces", "hold_at_ms")}
    blob = json.dumps({"tag": CACHE_TAG, "seg": spec, **context}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def render_timeline(
    edl: dict,
    *,
    master_path: Path,
    master_probe: dict,
    take_paths: dict[str, Path],
    out_path: Path,
    work_dir: Path,
    cache_dir: Path,
    preset_name: str = "final",
    progress: Progress | None = None,
) -> dict:
    preset = PRESETS[preset_name]
    fps = edl["fps"]
    layout = edl["layout"]
    work_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    report = progress or (lambda f, m: None)

    pip = pip_geometry(layout, master_probe, preset["width"], preset["height"])
    mask_path = cache_dir / f"mask_{pip['w']}x{pip['h']}_r{pip['radius']}.png"
    if not mask_path.exists():
        make_mask(mask_path, pip["w"], pip["h"], pip["radius"])

    segments = edl["segments"]
    files: list[Path] = []
    todo: list[tuple[dict, Path | None, Path]] = []
    for seg in segments:
        take_path = take_paths.get(seg.get("take_id")) if seg["kind"] != "face" else None
        key = segment_key(
            seg, master=_fingerprint(master_path), take=_fingerprint(take_path),
            preset=preset, fps=fps, pip=pip if layout.get("pip_visible", True) else None,
        )
        out = cache_dir / f"{key}.mp4"
        files.append(out)
        if not out.exists():
            todo.append((seg, take_path, out))

    def build(item: tuple[dict, Path | None, Path]) -> None:
        seg, take_path, out = item
        tmp = out.with_name(out.stem + ".tmp.mp4")
        ffmpeg(*segment_args(seg, fps=fps, preset=preset, layout=layout, pip=pip,
                             master_path=master_path, take_path=take_path, mask_path=mask_path, out=tmp))
        tmp.replace(out)

    # Segments are independent, so encode several at once (each ffmpeg is itself multi-threaded,
    # so a small pool is enough to keep the CPU busy between short segments).
    from concurrent.futures import ThreadPoolExecutor, as_completed

    finished = len(segments) - len(todo)
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(todo)))) as pool:
        for future in as_completed([pool.submit(build, item) for item in todo]):
            future.result()
            finished += 1
            report(finished / (len(segments) + 1), f"Rendered segment {finished}/{len(segments)}")

    list_file = work_dir / "segments.txt"
    list_file.write_text(
        "".join("file '" + f.resolve().as_posix().replace("'", r"'\''") + "'\n" for f in files),
        encoding="utf-8",
    )
    video_only = work_dir / "video.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(video_only))

    total_s = edl["total_frames"] / fps
    ffmpeg("-i", str(video_only), "-i", str(master_path), "-map", "0:v", "-map", "1:a:0?",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{total_s:.3f}", "-movflags", "+faststart", str(out_path))
    video_only.unlink(missing_ok=True)

    result = probe(out_path)
    frame_s = 1 / fps
    if result.get("nb_frames") is not None and abs(result["nb_frames"] - edl["total_frames"]) > 1:
        raise MediaError(f"output has {result['nb_frames']} frames, expected {edl['total_frames']}")
    if abs(result["duration_ms"] / 1000 - total_s) > frame_s + 0.05:
        raise MediaError(f"output lasts {result['duration_ms']} ms, expected {total_s * 1000:.0f} ms")
    report(1.0, "Done")
    return result
