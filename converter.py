"""TS → MP4 conversion engine. No UI dependencies."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = "ffmpeg"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
_CTX_PREFIX_RE = re.compile(r"^\[[^\]]+@\s*[0-9a-fx]+\]\s*", re.IGNORECASE)


class Mode(str, Enum):
    REMUX = "remux"
    AUTO = "auto"
    REENCODE = "reencode"


MODE_LABELS = {
    Mode.REMUX: "Fast (remux only)",
    Mode.AUTO: "Auto (remux, re-encode if needed)",
    Mode.REENCODE: "Re-encode (most compatible)",
}


class ConflictPolicy(str, Enum):
    RENAME = "rename"
    OVERWRITE = "overwrite"
    SKIP = "skip"


@dataclass
class Job:
    src: Path
    out_dir: Path
    mode: Mode = Mode.AUTO
    conflict: ConflictPolicy = ConflictPolicy.RENAME

    duration: float = 0.0
    file_size: int = 0
    out_path: Optional[Path] = None

    status: str = "Queued"
    stage: str = ""
    seconds_done: float = 0.0
    speed: float = 0.0
    progress_pct: float = 0.0
    eta_seconds: float = 0.0

    error: Optional[str] = None
    error_full: Optional[str] = None
    actually_used: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class CancelledError(Exception):
    pass


class ConversionError(Exception):
    def __init__(self, short: str, full: str = ""):
        super().__init__(short)
        self.short = short
        self.full = full or short


def hms_to_seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)


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


def probe_duration(src: Path) -> Optional[float]:
    try:
        proc = subprocess.run(
            [FFMPEG_PATH, "-hide_banner", "-i", str(src)],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    m = DURATION_RE.search(proc.stderr or "")
    return hms_to_seconds(*m.groups()) if m else None


_HW_CACHE: Optional[list[str]] = None


def detect_hw_encoders() -> list[str]:
    global _HW_CACHE
    if _HW_CACHE is not None:
        return _HW_CACHE
    try:
        proc = subprocess.run(
            [FFMPEG_PATH, "-hide_banner", "-encoders"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=10,
        )
        out = proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        out = ""
    candidates = ["h264_nvenc", "h264_qsv", "h264_amf"]
    _HW_CACHE = [c for c in candidates if c in out]
    return _HW_CACHE


def best_h264_encoder(prefer_hw: bool = True) -> str:
    if prefer_hw:
        hw = detect_hw_encoders()
        if hw:
            return hw[0]
    return "libx264"


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


class Converter:
    def __init__(self, prefer_hw: bool = True):
        self.prefer_hw = prefer_hw

    def convert(
        self,
        job: Job,
        on_update: Callable[[], None],
        cancel_event: threading.Event,
    ):
        job.started_at = time.time()

        if cancel_event.is_set():
            raise CancelledError()

        if not job.duration:
            job.stage = "Probing"
            on_update()
            d = probe_duration(job.src)
            if d:
                job.duration = d

        job.out_dir.mkdir(parents=True, exist_ok=True)
        out_path = resolve_output_path(job.src, job.out_dir, job.conflict)
        if out_path is None:
            raise ConversionError("Output exists; skipped")
        job.out_path = out_path

        if cancel_event.is_set():
            raise CancelledError()

        if job.mode == Mode.REMUX:
            self._remux(job, on_update, cancel_event)
        elif job.mode == Mode.REENCODE:
            self._reencode(job, on_update, cancel_event)
        else:
            try:
                self._remux(job, on_update, cancel_event)
            except ConversionError as e:
                if cancel_event.is_set():
                    raise CancelledError()
                if job.out_path and job.out_path.exists():
                    try:
                        job.out_path.unlink()
                    except OSError:
                        pass
                job.stage = "Re-encoding (remux failed, retrying)"
                job.error = None
                on_update()
                try:
                    self._reencode(job, on_update, cancel_event)
                except ConversionError as e2:
                    raise ConversionError(
                        e2.short,
                        f"Remux failed: {e.full}\n\nRe-encode failed: {e2.full}",
                    )

        job.completed_at = time.time()

    def _remux(self, job, on_update, cancel_event):
        cmd = [
            FFMPEG_PATH, "-y",
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+igndts+discardcorrupt",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            "-i", str(job.src),
            "-map", "0:v?", "-map", "0:a?",
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats", "-loglevel", "error",
            str(job.out_path),
        ]
        self._run(cmd, job, on_update, cancel_event, stage="Remuxing")
        job.actually_used = "remux"

    def _reencode(self, job, on_update, cancel_event):
        encoder = best_h264_encoder(self.prefer_hw)
        is_hw = encoder != "libx264"

        cmd = [
            FFMPEG_PATH, "-y",
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+igndts+discardcorrupt",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            "-i", str(job.src),
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
            str(job.out_path),
        ]
        stage = f"Re-encoding ({'GPU: ' + encoder if is_hw else 'CPU'})"
        self._run(cmd, job, on_update, cancel_event, stage=stage)
        job.actually_used = encoder

    def _run(self, cmd, job: Job, on_update, cancel_event: threading.Event,
             stage: str, stall_timeout: float = 45.0):
        job.stage = stage
        job.seconds_done = 0.0
        job.speed = 0.0
        on_update()

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
                current = job.seconds_done
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
                        job.seconds_done = max(0.0, micros / 1_000_000.0)
                        if job.duration > 0:
                            job.progress_pct = min(100.0, job.seconds_done / job.duration * 100)
                            if job.speed > 0:
                                remaining = max(0.0, job.duration - job.seconds_done)
                                job.eta_seconds = remaining / job.speed
                        on_update()
                    except ValueError:
                        pass
                elif line.startswith("speed="):
                    val = line.split("=", 1)[1].strip().rstrip("x")
                    try:
                        job.speed = float(val)
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

        if cancel_event.is_set():
            raise CancelledError()
        if stalled_event.is_set():
            raise ConversionError(
                f"Stalled at {job.progress_pct:.0f}% (no progress for {int(stall_timeout)}s)",
                f"ffmpeg produced no new output for {int(stall_timeout)} seconds. "
                f"This usually means a corrupt section the remuxer can't skip. "
                f"Re-encode mode will handle it."
            )
        if proc.returncode != 0:
            err_full = "".join(stderr_buf).strip()
            short = extract_error(err_full) or f"ffmpeg exit {proc.returncode}"
            raise ConversionError(short, err_full)