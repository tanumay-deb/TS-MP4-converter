"""End-to-end engine tests: convert() returns a ConversionResult and never
mutates a Job. Skipped where ffmpeg can't run."""
import io
import subprocess
import threading
from pathlib import Path

import pytest

import converter as c
from tsconverter.media import handlers as H
from tsconverter.media.ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH
from tsconverter.models import ConflictPolicy, ConversionRequest, JobStatus, Mode


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


def _convert(src, out_dir, **kw):
    return c.Converter(prefer_hw=kw.pop("prefer_hw", False)).convert(
        ConversionRequest(src=src, out_dir=out_dir, **kw))


def test_parallel_jobs_with_the_same_name_get_separate_outputs(tmp_path, monkeypatch):
    # clip.ts in two folders -> one output folder, converted at the same time.
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    srcs = []
    for d in ("mon", "tue"):
        (tmp_path / d).mkdir()
        srcs.append(tmp_path / d / "clip.ts")
        _make_clip(srcs[-1])
    results = [None, None]
    threads = [threading.Thread(target=lambda i=i: results.__setitem__(
        i, _convert(srcs[i], tmp_path / "out", mode=Mode.AUTO))) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert [r.status for r in results] == [JobStatus.DONE, JobStatus.DONE]
    assert {r.out_path.name for r in results} == {"clip.mp4", "clip (1).mp4"}
    assert all(r.out_path.exists() for r in results)


def test_overwrite_never_replaces_an_output_made_earlier_in_the_batch(tmp_path, monkeypatch):
    # clip.ts in two folders -> one output folder, one after the other, Overwrite on.
    # With "delete source after success" the first video would be gone for good.
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    conv = c.Converter(prefer_hw=False)
    outs = []
    for d in ("mon", "tue"):
        (tmp_path / d).mkdir()
        _make_clip(tmp_path / d / "clip.ts")
        outs.append(conv.convert(ConversionRequest(
            src=tmp_path / d / "clip.ts", out_dir=tmp_path / "out",
            conflict=ConflictPolicy.OVERWRITE)).out_path)
    assert [p.name for p in outs] == ["clip.mp4", "clip (1).mp4"]
    conv.end_batch(outs)
    r = conv.convert(ConversionRequest(src=tmp_path / "mon" / "clip.ts", out_dir=tmp_path / "out",
                                       conflict=ConflictPolicy.OVERWRITE))
    assert r.out_path.name == "clip.mp4"         # a new batch overwrites again
    conv.end_batch([r.out_path])


def _make_tv_clip(path):
    """H.264 + AC-3 5.1(side) in MPEG-TS, like an HD TV recording."""
    subprocess.run(
        [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=128x96:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-filter_complex", "[1:a]aformat=channel_layouts=5.1(side)[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "ac3", "-f", "mpegts",
         str(path)], creationflags=CREATE_NO_WINDOW, check=True)


def test_tv_surround_audio_converts_to_opus_and_webm(tmp_path, monkeypatch):
    # AC-3 "5.1(side)" (common in TV recordings) made libopus fail every time.
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "tv.ts"
    _make_tv_clip(src)
    for fmt in ("opus", "webm"):
        r = _convert(src, tmp_path / "out", mode=Mode.AUTO, out_format=fmt)
        assert r.status == JobStatus.DONE, (fmt, r.error)


def test_ac3_tv_audio_fast_copies_auto_makes_aac(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "tv.ts"
    _make_tv_clip(src)
    # Fast (remux only) used to fail on every AC-3/MP2 recording.
    fast = _convert(src, tmp_path / "fast", mode=Mode.REMUX)
    assert fast.status == JobStatus.DONE and fast.used_encoder == "remux", fast.error
    # Auto keeps its plays-everywhere output: AC-3 is not copied into MP4 or "M4A / AAC".
    auto = _convert(src, tmp_path / "auto", mode=Mode.AUTO)
    assert auto.status == JobStatus.DONE and auto.used_encoder != "remux"
    m4a = _convert(src, tmp_path / "auto", mode=Mode.AUTO, out_format="m4a")
    assert m4a.status == JobStatus.DONE and m4a.used_encoder == "aac"


def test_disk_full_fails_clearly_without_retries_or_leftovers(tmp_path, monkeypatch):
    # A full disk used to trigger the re-encode fallback, which could swap a lossless
    # copy for a smaller, worse file (even over an existing one), or retry for minutes.
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    runs = []

    class FullDiskFfmpeg:            # writes part of the output, then runs out of space
        returncode = -28

        def __init__(self, cmd, **kw):
            runs.append(cmd)
            Path(cmd[-1]).write_bytes(b"x" * 5000)
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO(
                "[out#0/mp4 @ 01] Error writing trailer: No space left on device\n")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

    monkeypatch.setattr(c.subprocess, "Popen", FullDiskFfmpeg)
    monkeypatch.setattr(H, "best_h264_encoder",
                        lambda prefer_hw=True: "h264_fakehw" if prefer_hw else "libx264")
    src = tmp_path / "clip.ts"
    src.write_bytes(b"\0" * 1000)
    for mode in (Mode.AUTO, Mode.REENCODE):
        runs.clear()
        r = _convert(src, tmp_path / "out", mode=mode, duration=10.0, prefer_hw=True)
        assert r.status == JobStatus.FAILED and r.disk_full, mode
        assert r.error.startswith("Not enough free space"), r.error
        assert len(runs) == 1, mode                          # no re-encode or CPU retry
        assert list((tmp_path / "out").iterdir()) == []      # partial file removed


def test_names_outside_the_windows_code_page_convert(tmp_path, monkeypatch):
    # ffprobe prints the file name as UTF-8; read as cp1252 it failed on "●", so probing
    # found nothing: no length, and a good output was reported as "Verify failed".
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "clip ●● 日本.mkv"
    _make_clip(src)
    r = _convert(src, tmp_path / "out", mode=Mode.AUTO)
    assert r.status == JobStatus.DONE, r.error
    assert r.duration > 0.5


class _ScriptedFfmpeg:
    """Prints [(pause_s, line)] progress lines, then exits 0. kill() stops it."""
    def __init__(self, script):
        self.returncode = None
        self._done = threading.Event()
        self.stderr = iter(())

        def lines():
            for pause, line in script:
                if self._done.wait(pause):          # killed
                    return
                yield line + "\n"
            self.returncode = 0
            self._done.set()
        self.stdout = lines()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.returncode

    def kill(self):
        self.returncode = 1
        self._done.set()


def _run_scripted(monkeypatch, script):
    monkeypatch.setattr(c.subprocess, "Popen", lambda cmd, **kw: _ScriptedFfmpeg(script))
    ctx = c._Ctx(ConversionRequest(src=Path("x.ts"), out_dir=Path("."), duration=10.0))
    c.Converter()._run(["ffmpeg"], ctx, lambda: None, threading.Event(),
                       stage="Remuxing", stall_timeout=1.0)


def test_silence_while_finishing_is_not_a_stall(monkeypatch):
    # After the last frame +faststart rewrites the whole file and prints nothing; for
    # 3 GB on a busy disk that took over 45s, and the job was killed "Stalled at 100%".
    _run_scripted(monkeypatch, [(0.05, "out_time_ms=5000000"), (0.05, "out_time_ms=10000000"),
                                (2.5, "progress=end")])


def test_reports_without_progress_are_a_stall(monkeypatch):
    script = [(0.05, "out_time_ms=5000000")] + [(0.1, "out_time_ms=5000000")] * 30
    with pytest.raises(c.ConversionError, match="Stalled"):
        _run_scripted(monkeypatch, script)


def test_failed_overwrite_keeps_the_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "clip.ts"
    src.write_bytes(b"not a video" * 1000)
    old = tmp_path / "clip.mp4"
    old.write_bytes(b"last week's good conversion")
    r = _convert(src, tmp_path, mode=Mode.AUTO, conflict=ConflictPolicy.OVERWRITE)
    assert r.status == JobStatus.FAILED
    assert old.read_bytes() == b"last week's good conversion"


def test_skip_policy_reports_skipped_not_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "clip.mkv"
    _make_clip(src)
    (tmp_path / "clip.mp4").write_bytes(b"x")
    r = _convert(src, tmp_path, conflict=ConflictPolicy.SKIP)
    assert r.status == JobStatus.SKIPPED and r.error is None


def test_overwrite_never_replaces_the_source(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    src = tmp_path / "clip.mp4"
    _make_clip(src)
    before = src.read_bytes()
    r = _convert(src, tmp_path, mode=Mode.REENCODE, conflict=ConflictPolicy.OVERWRITE)
    assert r.status == JobStatus.DONE and r.out_path.name == "clip (1).mp4"
    assert src.read_bytes() == before


def test_failed_gpu_encode_retries_on_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(H, "best_h264_encoder",
                        lambda prefer_hw=True: "h264_fakehw" if prefer_hw else "libx264")
    src = tmp_path / "clip.mkv"
    _make_clip(src)
    r = _convert(src, tmp_path / "out", mode=Mode.REENCODE, prefer_hw=True)
    assert r.status == JobStatus.DONE and r.used_encoder == "libx264"


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
