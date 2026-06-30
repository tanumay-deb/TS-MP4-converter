"""Thumbnail extraction (best-effort, cached). Skipped where ffmpeg can't run."""
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


def test_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_CACHE_DIR", tmp_path / "thumbs")
    assert thumbnail.extract_thumbnail(tmp_path / "nope.mp4") is None
