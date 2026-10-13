"""Renders synthetic media through the real ffmpeg pipeline."""

import shutil

import pytest

from synccut.core.render import render_timeline
from synccut.core.timeline import build_timeline
from synccut.media import detect_freezes, ffmpeg, probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i", "sine=f=440:d=6",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "master.mp4"))
    # 16:10 at 24 fps: mismatched shape and frame rate on purpose
    ffmpeg("-f", "lavfi", "-i", "testsrc=s=720x450:r=24:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(d / "take.mp4"))
    return d


def test_cursor_movement_is_not_idle(tmp_path):
    # a 12x20 "cursor" moves for 3 s on a 1080p screen, then nothing moves for 3 s
    clip = tmp_path / "cursor.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=white:s=1920x1080:r=30:d=6", "-f", "lavfi", "-i", "color=c=black:s=12x20:r=30:d=6",
           "-filter_complex", "[0:v][1:v]overlay=x='200+min(t,3)*400':y=500", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip))
    idle = detect_freezes(clip, 6000)
    assert len(idle) == 1 and idle[0][0] >= 2900


def test_render_exact_frames(media_dir, tmp_path):
    master_probe = probe(media_dir / "master.mp4")
    take = {
        "id": "t1", "mode": "guided", "status": "ready", "created_at": 1, "duration_ms": 10_000,
        "markers": [{"beat_id": "b1", "t_ms": 0}, {"beat_id": "b2", "t_ms": 2000}],
        "events": [], "idle": [], "path": "take.mp4",
    }
    beats = [
        {"id": "b1", "text": "one", "start_ms": 1000, "end_ms": 3000},
        {"id": "b2", "text": "two", "start_ms": 3000, "end_ms": 6000},
    ]
    tl = build_timeline(beats, master_probe["duration_ms"], [take], fps=30)
    kinds = [s["kind"] for s in tl["segments"]]
    assert kinds == ["face", "browser", "browser"]

    out = tmp_path / "out.mp4"
    result = render_timeline(
        tl, master_path=media_dir / "master.mp4", master_probe=master_probe,
        take_paths={"t1": media_dir / "take.mp4"}, out_path=out,
        work_dir=tmp_path / "work", cache_dir=tmp_path / "cache", preset_name="draft",
    )
    assert result["width"] == 960 and result["height"] == 540
    assert result["nb_frames"] == tl["total_frames"]
    assert result["has_audio"]

    # second render reuses every cached segment
    cached = sorted((tmp_path / "cache").glob("*.mp4"))
    render_timeline(
        tl, master_path=media_dir / "master.mp4", master_probe=master_probe,
        take_paths={"t1": media_dir / "take.mp4"}, out_path=tmp_path / "out2.mp4",
        work_dir=tmp_path / "work2", cache_dir=tmp_path / "cache", preset_name="draft",
    )
    assert sorted((tmp_path / "cache").glob("*.mp4")) == cached
