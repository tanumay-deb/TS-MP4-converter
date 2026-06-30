"""TS → MP4 conversion engine. No UI dependencies."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# Binary resolution, probing and HW detection now live in the tsconverter
# package. Re-exported here so existing `from converter import ...` users keep
# working during the incremental refactor.
from tsconverter.media import hwaccel
from tsconverter.media.ffmpeg import (  # noqa: F401  (re-exported)
    CREATE_NO_WINDOW,
    FFMPEG_PATH,
    FFPROBE_PATH,
)
from tsconverter.media.probe import probe as probe_media
from tsconverter.models import (  # noqa: F401  (re-exported for compatibility)
    CancelledError,
    ConflictPolicy,
    ConversionError,
    ConversionRequest,
    ConversionResult,
    Job,
    JobStatus,
    MODE_LABELS,
    Mode,
    ProgressEvent,
)

_CTX_PREFIX_RE = re.compile(r"^\[[^\]]+@\s*[0-9a-fx]+\]\s*", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def get_logs_dir() -> Path:
    """Resolve the ./logs/ folder next to the app.

    For a PyInstaller --onefile build, that's next to the .exe.
    For source runs, it's next to converter.py. Falls back to a temp dir
    if the app folder is read-only.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    candidate = base / "logs"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        # Confirm we can actually write here (read-only install location?)
        probe = candidate / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "TSConverter_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def write_log(log_lines, src_stem: str) -> Optional[Path]:
    """Flush log lines to ./logs/<stem>_<timestamp>.log. Returns the path or None."""
    if not log_lines:
        return None
    try:
        logs_dir = get_logs_dir()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_stem = _SAFE_NAME_RE.sub("_", src_stem)[:80] or "job"
        log_path = logs_dir / f"{safe_stem}_{timestamp}.log"
        # If two jobs of the same file land in the same second, disambiguate.
        n = 1
        while log_path.exists():
            log_path = logs_dir / f"{safe_stem}_{timestamp}_{n}.log"
            n += 1
        with open(log_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(log_lines))
            fp.write("\n")
        return log_path
    except OSError:
        return None


def verify_output(out_path: Path, expected_duration: float,
                  expect_video: bool = True) -> tuple[bool, str]:
    """Quick post-conversion probe. Sub-second on most files.

    Checks: file exists with non-trivial size, container is parseable, the
    expected stream kind is present, duration within 2% (or 2s) of expected.
    `expect_video=False` is used by audio-only targets (M2).
    """
    if not out_path.exists():
        return False, "Output file does not exist"
    try:
        size = out_path.stat().st_size
    except OSError as e:
        return False, f"Could not stat output ({e})"
    if size < 4096:
        return False, f"Output is suspiciously small ({size} bytes)"

    info = probe_media(out_path)
    if not info.ok:
        return False, "Output is not a readable media file (no streams found)"
    if expect_video and not info.has_video:
        return False, "No video stream in output"
    if not expect_video and not info.has_audio:
        return False, "No audio stream in output"

    mb = size / 1024 / 1024
    actual = info.duration
    if actual and expected_duration > 0:
        diff = abs(actual - expected_duration)
        tolerance = max(2.0, expected_duration * 0.02)
        if diff > tolerance:
            return False, (
                f"Duration mismatch: expected {expected_duration:.1f}s, "
                f"got {actual:.1f}s"
            )
    if actual:
        return True, f"OK ({actual:.1f}s, {mb:.1f} MB)"
    return True, f"OK ({mb:.1f} MB; duration not detected)"


def extract_error(stderr: str) -> str:
    if not stderr:
        return ""
    lines = [_CTX_PREFIX_RE.sub("", ln).strip() for ln in stderr.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    keywords = ("could not", "invalid", "error", "no such", "permission",
                "unable", "failed", "unsupported", "malformed", "denied")
    for ln in reversed(lines):
        low = ln.lower()
        if any(k in low for k in keywords) and not low.startswith("conversion failed"):
            return ln
    return lines[-1]


TS_SYNC = 0x47          # MPEG-TS packet sync byte
TS_PACKET = 188         # standard transport stream packet size


def detect_ts_offset(src: Path, scan_bytes: int = 65536, max_prefix: int = 4096) -> int:
    """Return the byte offset where a junk-prefixed MPEG-TS stream really starts.

    Some 'fake' .ts files have junk bytes (often a tiny PNG) prepended so that
    ffmpeg sniffs the wrong format (e.g. png_pipe, a 1x1 image) and never finds
    the video. The real transport stream begins at the first 0x47 sync byte that
    recurs at the 188-byte packet stride. Returns 0 for clean files (the stream
    already starts at byte 0) or if no transport stream is found.
    """
    try:
        with open(src, "rb") as fp:
            buf = fp.read(scan_bytes)
    except OSError:
        return 0
    n = len(buf)
    need = TS_PACKET * 2
    if n < need + 1:
        return 0
    upper = min(max_prefix, n - need)
    for off in range(upper + 1):
        if (buf[off] == TS_SYNC
                and buf[off + TS_PACKET] == TS_SYNC
                and buf[off + 2 * TS_PACKET] == TS_SYNC):
            return off
    return 0


def ts_input_opts(src: Path) -> list[str]:
    """ffmpeg input options to handle a junk-prefixed .ts file.

    Returns the options needed to skip the junk header and force the mpegts
    demuxer, or an empty list for clean files (and non-.ts inputs, which are
    left to ffmpeg's normal format detection).
    """
    if src.suffix.lower() != ".ts":
        return []
    offset = detect_ts_offset(src)
    if offset > 0:
        return ["-skip_initial_bytes", str(offset), "-f", "mpegts"]
    return []


def probe_duration(src: Path) -> Optional[float]:
    skip = detect_ts_offset(src) if src.suffix.lower() == ".ts" else 0
    info = probe_media(src, skip_bytes=skip)
    return info.duration or None


def detect_hw_encoders() -> list[str]:
    """H.264 hardware encoders that actually work (verified by test-encode)."""
    return hwaccel.working_hw_encoders()


def best_h264_encoder(prefer_hw: bool = True) -> str:
    return hwaccel.best_h264_encoder(prefer_hw)


def resolve_output_path(src: Path, out_dir: Path, policy: ConflictPolicy) -> Optional[Path]:
    candidate = out_dir / (src.stem + ".mp4")
    if not candidate.exists():
        return candidate
    if policy == ConflictPolicy.OVERWRITE:
        return candidate
    if policy == ConflictPolicy.SKIP:
        return None
    n = 1
    while True:
        c = out_dir / f"{src.stem} ({n}).mp4"
        if not c.exists():
            return c
        n += 1


class _Ctx:
    """Engine-internal mutable state for one conversion.

    Replaces the old practice of mutating the UI's Job directly. It never leaves
    the engine: progress is surfaced via ProgressEvent and the final state via
    ConversionResult.
    """
    def __init__(self, req: ConversionRequest):
        self.src = req.src
        self.out_dir = req.out_dir
        self.mode = req.mode
        self.conflict = req.conflict
        self.out_format = req.out_format
        self.duration = req.duration
        self.out_path: Optional[Path] = None
        self.stage = ""
        self.seconds_done = 0.0
        self.speed = 0.0
        self.progress_pct = 0.0
        self.eta_seconds = 0.0
        self.actually_used: Optional[str] = None
        self.log_lines: list = []


class Converter:
    def __init__(self, prefer_hw: bool = True):
        self.prefer_hw = prefer_hw

    @staticmethod
    def _emitter(ctx: "_Ctx", on_progress):
        """Return a no-arg callable that snapshots ctx into a ProgressEvent."""
        def emit():
            if on_progress is not None:
                on_progress(ProgressEvent(
                    stage=ctx.stage, seconds_done=ctx.seconds_done,
                    speed=ctx.speed, progress_pct=ctx.progress_pct,
                    eta_seconds=ctx.eta_seconds, duration=ctx.duration,
                ))
        return emit

    def convert(
        self,
        request: ConversionRequest,
        on_progress: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ConversionResult:
        """Run one conversion. Returns a ConversionResult; never mutates a Job."""
        if cancel_event is None:
            cancel_event = threading.Event()
        ctx = _Ctx(request)
        emit = self._emitter(ctx, on_progress)
        started_at = time.time()
        ctx.log_lines = [
            f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
            f"Source:   {ctx.src}",
            f"Mode:     {ctx.mode.value}",
            f"Conflict: {ctx.conflict.value}",
        ]
        status = JobStatus.DONE
        error_short = error_full = verify_message = None
        verify_ok = True

        try:
            if cancel_event.is_set():
                raise CancelledError()

            if not ctx.duration:
                ctx.stage = "Probing"
                emit()
                d = probe_duration(ctx.src)
                if d:
                    ctx.duration = d
            ctx.log_lines.append(f"Duration: {ctx.duration:.1f}s")

            ctx.out_dir.mkdir(parents=True, exist_ok=True)
            out_path = resolve_output_path(ctx.src, ctx.out_dir, ctx.conflict)
            if out_path is None:
                raise ConversionError("Output exists; skipped")
            ctx.out_path = out_path
            ctx.log_lines.append(f"Output:   {out_path}")

            if cancel_event.is_set():
                raise CancelledError()

            if ctx.mode == Mode.REMUX:
                self._remux(ctx, emit, cancel_event)
            elif ctx.mode == Mode.REENCODE:
                self._reencode(ctx, emit, cancel_event)
            else:
                try:
                    self._remux(ctx, emit, cancel_event)
                except ConversionError as e:
                    if cancel_event.is_set():
                        raise CancelledError()
                    if ctx.out_path and ctx.out_path.exists():
                        try:
                            ctx.out_path.unlink()
                        except OSError:
                            pass
                    ctx.stage = "Re-encoding (remux failed, retrying)"
                    ctx.log_lines.append(f"Remux failed: {e.short} — retrying with re-encode")
                    emit()
                    try:
                        self._reencode(ctx, emit, cancel_event)
                    except ConversionError as e2:
                        raise ConversionError(
                            e2.short,
                            f"Remux failed: {e.full}\n\nRe-encode failed: {e2.full}",
                        )

            # Output verification (quick probe — sub-second on most files)
            if not cancel_event.is_set() and ctx.out_path and ctx.out_path.exists():
                ctx.stage = "Verifying output"
                emit()
                ok, msg = verify_output(ctx.out_path, ctx.duration)
                verify_message = msg
                ctx.log_lines.append(f"Verify:   {msg}")
                if not ok:
                    verify_ok = False
                    raise ConversionError(
                        f"Verify failed: {msg}",
                        f"Output file failed post-conversion verification.\n{msg}\n\n"
                        f"The output file was kept at:\n{ctx.out_path}",
                    )
        except CancelledError:
            status = JobStatus.CANCELLED
            ctx.log_lines.append("CANCELLED")
        except ConversionError as e:
            status = JobStatus.FAILED
            error_short, error_full = e.short, e.full
            if verify_ok:
                ctx.log_lines.append(f"FAILED: {e.short}")
        except Exception as e:  # noqa: BLE001 - report unexpected errors as a result
            status = JobStatus.FAILED
            error_short = error_full = f"{type(e).__name__}: {e}"
            ctx.log_lines.append(f"FAILED: {error_short}")

        completed_at = time.time()
        if status == JobStatus.DONE:
            ctx.log_lines.append(f"Done in {completed_at - started_at:.1f}s")
        log_path = write_log(ctx.log_lines, ctx.src.stem)

        return ConversionResult(
            status=status,
            out_path=ctx.out_path,
            duration=ctx.duration,
            used_encoder=ctx.actually_used,
            verify_message=verify_message,
            error=error_short,
            error_full=error_full,
            log_lines=ctx.log_lines,
            log_path=log_path,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _remux(self, ctx, on_update, cancel_event):
        is_ts_family = ctx.src.suffix.lower() in (".ts", ".m2ts", ".mts")
        in_opts = ts_input_opts(ctx.src)
        if in_opts:
            ctx.log_lines.append(
                f"Junk header detected — skipping {in_opts[1]} bytes, forcing mpegts demuxer"
            )
        cmd = [
            FFMPEG_PATH, "-y",
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+igndts+discardcorrupt",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            *in_opts,
            "-i", str(ctx.src),
            "-map", "0:v?", "-map", "0:a?",
            "-c", "copy",
        ]
        if is_ts_family:
            # AAC in MPEG-TS uses ADTS framing; MP4 needs ASC. Not needed for MKV.
            cmd += ["-bsf:a", "aac_adtstoasc"]
        cmd += [
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats", "-loglevel", "error",
            str(ctx.out_path),
        ]
        self._run(cmd, ctx, on_update, cancel_event, stage="Remuxing")
        ctx.actually_used = "remux"

    def _reencode(self, ctx, on_update, cancel_event):
        encoder = best_h264_encoder(self.prefer_hw)
        is_hw = encoder != "libx264"
        in_opts = ts_input_opts(ctx.src)
        if in_opts:
            ctx.log_lines.append(
                f"Junk header detected — skipping {in_opts[1]} bytes, forcing mpegts demuxer"
            )

        cmd = [
            FFMPEG_PATH, "-y",
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+igndts+discardcorrupt",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            *in_opts,
            "-i", str(ctx.src),
            "-map", "0:v?", "-map", "0:a?",
            "-c:v", encoder,
        ]
        if encoder == "libx264":
            cmd += ["-preset", "veryfast", "-crf", "23"]
        elif encoder == "h264_nvenc":
            cmd += ["-preset", "p4", "-cq", "23", "-rc", "vbr"]
        elif encoder == "h264_qsv":
            cmd += ["-preset", "veryfast", "-global_quality", "23"]
        elif encoder == "h264_amf":
            cmd += ["-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]

        cmd += [
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats", "-loglevel", "error",
            str(ctx.out_path),
        ]
        stage = f"Re-encoding ({'GPU: ' + encoder if is_hw else 'CPU'})"
        self._run(cmd, ctx, on_update, cancel_event, stage=stage)
        ctx.actually_used = encoder

    def _run(self, cmd, ctx, on_update, cancel_event: threading.Event,
             stage: str, stall_timeout: float = 45.0):
        ctx.stage = stage
        ctx.seconds_done = 0.0
        ctx.speed = 0.0
        on_update()

        ctx.log_lines.append(f"--- {stage} ---")
        ctx.log_lines.append("Command: " + " ".join(
            f'"{c}"' if " " in str(c) else str(c) for c in cmd
        ))

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=CREATE_NO_WINDOW,
        )

        stop_watcher = threading.Event()
        stalled_event = threading.Event()
        line_q: queue.Queue = queue.Queue()
        stderr_buf: list[str] = []

        def kill_proc():
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass

        def watchdog():
            """Kill ffmpeg promptly on cancel or stall."""
            last_seconds = 0.0
            last_progress_at = time.time()
            while not stop_watcher.is_set():
                if cancel_event.is_set():
                    kill_proc()
                    return
                current = ctx.seconds_done
                now = time.time()
                if current > last_seconds + 0.05:
                    last_seconds = current
                    last_progress_at = now
                elif current > 0 and (now - last_progress_at) > stall_timeout:
                    stalled_event.set()
                    kill_proc()
                    return
                if stop_watcher.wait(0.2):
                    return

        def stdout_reader():
            try:
                for line in proc.stdout:
                    line_q.put(line)
            except Exception:
                pass
            line_q.put(None)  # EOF sentinel

        def stderr_reader():
            try:
                for line in proc.stderr:
                    stderr_buf.append(line)
            except Exception:
                pass

        watcher_t = threading.Thread(target=watchdog, daemon=True)
        out_t = threading.Thread(target=stdout_reader, daemon=True)
        err_t = threading.Thread(target=stderr_reader, daemon=True)
        watcher_t.start()
        out_t.start()
        err_t.start()

        try:
            while True:
                if cancel_event.is_set() or stalled_event.is_set():
                    break
                try:
                    line = line_q.get(timeout=0.3)
                except queue.Empty:
                    continue
                if line is None:  # EOF
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("out_time_ms="):
                    try:
                        micros = int(line.split("=", 1)[1])
                        ctx.seconds_done = max(0.0, micros / 1_000_000.0)
                        if ctx.duration > 0:
                            ctx.progress_pct = min(100.0, ctx.seconds_done / ctx.duration * 100)
                            if ctx.speed > 0:
                                remaining = max(0.0, ctx.duration - ctx.seconds_done)
                                ctx.eta_seconds = remaining / ctx.speed
                        on_update()
                    except ValueError:
                        pass
                elif line.startswith("speed="):
                    val = line.split("=", 1)[1].strip().rstrip("x")
                    try:
                        ctx.speed = float(val)
                    except ValueError:
                        pass
                elif line == "progress=end":
                    break
        finally:
            stop_watcher.set()
            if cancel_event.is_set() or stalled_event.is_set():
                kill_proc()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                kill_proc()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            # Let reader threads drain so pipes close cleanly
            out_t.join(timeout=1)
            err_t.join(timeout=1)

        ctx.log_lines.append(f"Exit code: {proc.returncode}")
        if stderr_buf:
            ctx.log_lines.append("--- ffmpeg stderr ---")
            for raw in stderr_buf:
                stripped = raw.rstrip()
                if stripped:
                    ctx.log_lines.append(stripped)

        if cancel_event.is_set():
            raise CancelledError()
        if stalled_event.is_set():
            raise ConversionError(
                f"Stalled at {ctx.progress_pct:.0f}% (no progress for {int(stall_timeout)}s)",
                f"ffmpeg produced no new output for {int(stall_timeout)} seconds. "
                f"This usually means a corrupt section the remuxer can't skip. "
                f"Re-encode mode will handle it."
            )
        if proc.returncode != 0:
            err_full = "".join(stderr_buf).strip()
            short = extract_error(err_full) or f"ffmpeg exit {proc.returncode}"
            raise ConversionError(short, err_full)