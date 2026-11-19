"""Thumbnail extraction (best-effort, cached). Skipped where ffmpeg can't run."""
import struct
import subprocess

import pytest

from tsconverter.media import thumbnail
from tsconverter.media.ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH


def _ffmpeg_ok() -> bool:
    try:
        return subprocess.run([FFMPEG_PATH, "-hide_banner", "-version"],
                              capture_output=True, creationflags=CREATE_NO_WINDOW,
                              timeout=20).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not runnable")


def _clip(path, audio_only=False):
    cmd = [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error"]
    if audio_only:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(path)]
    else:
        cmd += ["-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                "-frames:v", "10", "-c:v", "libx264", str(path)]
    subprocess.run(cmd, creationflags=CREATE_NO_WINDOW, check=True)


def test_extract_thumbnail_writes_png_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    src = tmp_path / "clip.mp4"
    _clip(src)

    png = thumbnail.extract_thumbnail(src, width=160)
    assert png and png.exists() and png.suffix == ".png" and png.stat().st_size > 0
    # second call hits the cache and returns the same path
    assert thumbnail.extract_thumbnail(src, width=160) == png


def test_audio_only_has_no_thumbnail(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    src = tmp_path / "audio.m4a"
    _clip(src, audio_only=True)
    assert thumbnail.extract_thumbnail(src) is None


def test_height_bounds_portrait_into_row_box(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    src = tmp_path / "portrait.mp4"
    subprocess.run([FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=1:size=90x160:rate=10",
                    "-frames:v", "10", "-c:v", "libx264", str(src)],
                   creationflags=CREATE_NO_WINDOW, check=True)
    png = thumbnail.extract_thumbnail(src, width=80, height=45)
    w, h = struct.unpack(">II", png.read_bytes()[16:24])   # PNG IHDR width/height
    assert w <= 80 and h <= 45
    # width-only call is a different cache entry (unbounded height)
    assert thumbnail.extract_thumbnail(src, width=80) != png


def _ts(path, gop=None):
    """4s 160x90 .ts; default x264 GOP (250) means one keyframe, at frame 0."""
    subprocess.run([FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15", "-t", "4",
                    *(["-g", str(gop)] if gop else []),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   creationflags=CREATE_NO_WINDOW, check=True)


def _dims(png):
    return struct.unpack(">II", png.read_bytes()[16:24])   # PNG IHDR width/height


def test_ts_single_keyframe_falls_back_to_first_frame(tmp_path, monkeypatch):
    # The 20% seek lands past the only keyframe: nothing decodes, so retry from 0.
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    src = tmp_path / "short.ts"
    _ts(src)
    png = thumbnail.extract_thumbnail(src, width=80, height=45)
    assert png and _dims(png) == (80, 45)


def test_junk_prefixed_ts_gets_real_frame(tmp_path, monkeypatch):
    # A 1x1 PNG glued in front of the stream: without the header skip ffmpeg
    # demuxes it as png_pipe and the thumbnail fails (or is that 1x1 dot).
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    clean, dot, fake = tmp_path / "clean.ts", tmp_path / "dot.png", tmp_path / "fake.ts"
    _ts(clean, gop=5)
    subprocess.run([FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=black:s=1x1", "-frames:v", "1", str(dot)],
                   creationflags=CREATE_NO_WINDOW, check=True)
    fake.write_bytes(dot.read_bytes() + clean.read_bytes())
    png = thumbnail.extract_thumbnail(fake, width=80, height=45)
    assert png and _dims(png) == (80, 45)


def test_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    assert thumbnail.extract_thumbnail(tmp_path / "nope.mp4") is None
