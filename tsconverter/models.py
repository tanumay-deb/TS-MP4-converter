"""Shared data types: enums, errors, the engine's request/result contract, and
the UI-owned Job view-model.

The engine consumes an immutable ConversionRequest and produces a
ConversionResult (streaming ProgressEvents along the way). It never touches Job —
the UI/controller is the single owner that maps results onto Job for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


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


class CancelledError(Exception):
    pass


class ConversionError(Exception):
    def __init__(self, short: str, full: str = ""):
        super().__init__(short)
        self.short = short
        self.full = full or short


class JobStatus(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    SKIPPED = "Skipped"


# --- Engine contract (immutable in, value out) ---------------------------------

@dataclass(frozen=True)
class ConversionRequest:
    """Everything the engine needs for one conversion. Immutable."""
    src: Path
    out_dir: Path
    mode: Mode = Mode.AUTO
    conflict: ConflictPolicy = ConflictPolicy.RENAME
    duration: float = 0.0          # known source duration; 0.0 => engine probes
    out_format: str = "mp4"        # forward-compat for multi-format (M2)


@dataclass
class ProgressEvent:
    """A snapshot of in-flight progress, pushed to the engine's on_progress."""
    stage: str = ""
    seconds_done: float = 0.0
    speed: float = 0.0
    progress_pct: float = 0.0
    eta_seconds: float = 0.0
    duration: float = 0.0          # source duration once probed (0 = unknown yet)


@dataclass
class ConversionResult:
    """The outcome of a conversion. Returned by Converter.convert()."""
    status: JobStatus
    out_path: Optional[Path] = None
    duration: float = 0.0
    used_encoder: Optional[str] = None
    verify_message: Optional[str] = None
    error: Optional[str] = None
    error_full: Optional[str] = None
    log_lines: list = field(default_factory=list)
    log_path: Optional[Path] = None
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == JobStatus.DONE


# --- UI view-model -------------------------------------------------------------

@dataclass
class Job:
    """Mutable per-file state owned and mutated ONLY by the UI/controller."""
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

    log_lines: list = field(default_factory=list)
    log_path: Optional[Path] = None
    verify_message: Optional[str] = None

    def to_request(self) -> ConversionRequest:
        return ConversionRequest(
            src=self.src, out_dir=self.out_dir, mode=self.mode,
            conflict=self.conflict, duration=self.duration,
        )

    def apply_progress(self, ev: ProgressEvent) -> None:
        self.stage = ev.stage
        self.seconds_done = ev.seconds_done
        self.speed = ev.speed
        self.progress_pct = ev.progress_pct
        self.eta_seconds = ev.eta_seconds
        if ev.duration:
            self.duration = ev.duration

    def apply_result(self, r: ConversionResult) -> None:
        self.status = r.status.value
        self.out_path = r.out_path
        if r.duration:
            self.duration = r.duration
        self.actually_used = r.used_encoder
        self.verify_message = r.verify_message
        self.error = r.error
        self.error_full = r.error_full
        self.log_lines = r.log_lines
        self.log_path = r.log_path
        self.started_at = r.started_at
        self.completed_at = r.completed_at
        if r.status == JobStatus.DONE:
            self.progress_pct = 100.0
