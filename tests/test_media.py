"""Unit tests for the media layer — no real ffmpeg/ffprobe required (mocked)."""
import json
import types

import pytest

from tsconverter.media import hwaccel
from tsconverter.media import probe as probe_mod


def _fake_run(stdout="", stderr="", returncode=0):
    def run(cmd, *a, **k):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return run


FFPROBE_JSON = json.dumps({
    "format": {"format_name": "mov,mp4,m4a", "duration": "12.34"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
         "disposition": {"attached_pic": 0}},
        {"codec_type": "audio", "codec_name": "aac"},
    ],
})


def test_probe_parses_ffprobe_json(monkeypatch):
    monkeypatch.setattr(probe_mod, "FFPROBE_PATH", "ffprobe")
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run(FFPROBE_JSON))
    info = probe_mod.probe("x.mp4")
    assert info.source == "ffprobe"
    assert info.duration == pytest.approx(12.34)
    assert info.has_video and info.has_audio
    assert info.vcodec == "h264" and info.acodec == "aac"
    assert info.width == 1920 and info.height == 1080
    assert info.ok


def test_probe_skips_attached_cover_art(monkeypatch):
    j = json.dumps({"format": {"duration": "3.0"}, "streams": [
        {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
        {"codec_type": "audio", "codec_name": "mp3"},
    ]})
    monkeypatch.setattr(probe_mod, "FFPROBE_PATH", "ffprobe")
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run(j))
    info = probe_mod.probe("x.mp3")
    assert not info.has_video           # cover art is not real video
    assert info.has_audio and info.acodec == "mp3"
    assert info.ok


def test_probe_falls_back_to_ffmpeg_when_no_ffprobe(monkeypatch):
    monkeypatch.setattr(probe_mod, "FFPROBE_PATH", None)
    stderr = ("  Duration: 00:01:02.50, start: 0.000000, bitrate: 1 kb/s\n"
              "  Stream #0:0: Video: h264\n"
              "  Stream #0:1: Audio: aac\n")
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run("", stderr, returncode=1))
    info = probe_mod.probe("x.ts")
    assert info.source == "ffmpeg-fallback"
    assert info.duration == pytest.approx(62.5)
    assert info.has_video and info.has_audio


def test_hwaccel_lists_only_encoders_that_run(monkeypatch):
    hwaccel._WORKING_CACHE = None
    monkeypatch.setattr(hwaccel.platform, "system", lambda: "Windows")
    monkeypatch.setattr(hwaccel, "_encoder_runs", lambda enc: enc == "h264_qsv")
    assert hwaccel.working_hw_encoders(force=True) == ["h264_qsv"]
    assert hwaccel.best_h264_encoder() == "h264_qsv"


def test_hwaccel_falls_back_to_libx264_when_none_work(monkeypatch):
    hwaccel._WORKING_CACHE = None
    monkeypatch.setattr(hwaccel.platform, "system", lambda: "Windows")
    monkeypatch.setattr(hwaccel, "_encoder_runs", lambda enc: False)
    assert hwaccel.working_hw_encoders(force=True) == []
    assert hwaccel.best_h264_encoder() == "libx264"


def test_hwaccel_macos_includes_videotoolbox(monkeypatch):
    hwaccel._WORKING_CACHE = None
    monkeypatch.setattr(hwaccel.platform, "system", lambda: "Darwin")
    seen = []
    monkeypatch.setattr(hwaccel, "_encoder_runs", lambda enc: seen.append(enc) or True)
    assert hwaccel.working_hw_encoders(force=True) == ["h264_videotoolbox"]
