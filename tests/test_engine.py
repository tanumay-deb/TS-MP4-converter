"""End-to-end engine tests: convert() returns a ConversionResult and never
mutates a Job. Skipped where ffmpeg can't run."""
import subprocess

import pytest

import converter as c
from tsconverter.media.ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH
from tsconverter.models import ConversionRequest, JobStatus, Mode


def _ffmpeg_ok() -> bool:
    try:
        p = subprocess.run([FFMPEG_PATH, "-hide_banner", "-version"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=20)
        return p.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not runnable")


def _make_clip(path):
    subprocess.run(
        [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=128x96:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
        creationflags=CREATE_NO_WINDOW, check=True,
    )


def test_convert_returns_done_result_and_writes_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    src = tmp_path / "clip.mkv"
    _make_clip(src)

    events = []
    result = c.Converter(prefer_hw=False).convert(
        ConversionRequest(src=src, out_dir=tmp_path / "out", mode=Mode.AUTO),
        on_progress=events.append,
    )

    assert result.status == JobStatus.DONE
    assert result.ok
    assert result.out_path and result.out_path.exists()
    assert result.out_path.suffix == ".mp4"
    assert result.duration > 0.5
    assert result.log_path and result.log_path.exists()
    assert any(e.stage == "Remuxing" for e in events)


def test_convert_to_wav_is_audio_only(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    src = tmp_path / "clip.mkv"
    _make_clip(src)

    result = c.Converter(prefer_hw=False).convert(
        ConversionRequest(src=src, out_dir=tmp_path / "out",
                          mode=Mode.REENCODE, out_format="wav"),
    )
    assert result.status == JobStatus.DONE
    assert result.out_path and result.out_path.suffix == ".wav"
    assert result.used_encoder == "pcm_s16le"


def test_convert_missing_source_fails_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()

    result = c.Converter(prefer_hw=False).convert(
        ConversionRequest(src=tmp_path / "does_not_exist.ts",
                          out_dir=tmp_path / "out", mode=Mode.REMUX),
    )

    assert result.status == JobStatus.FAILED
    assert result.error
    assert result.out_path is None or not result.out_path.exists()
