"""Conversion queue orchestration, decoupled from the UI.

Runs the worker pool, owns the cancel/pause events, and maps each engine
ConversionResult onto its Job (the single place a Job is mutated). The UI passes
in callbacks; this module never touches Tk. Callbacks may be invoked from worker
threads, so the UI side is responsible for marshalling to its main thread.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import Callable, List

from .models import Job, JobStatus


class QueueController:
    def __init__(
        self,
        converter,
        *,
        refresh: Callable[[Job], None],
        record: Callable[[Job, object], None],
        set_overall: Callable[[float], None],
        finished: Callable[[int, int, int, int], None],
        concurrency: Callable[[], int],
        should_delete_source: Callable[[], bool],
    ):
        self._converter = converter
        self._refresh = refresh
        self._record = record
        self._set_overall = set_overall
        self._finished = finished
        self._concurrency = concurrency
        self._should_delete = should_delete_source
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self._thread = None

    def is_paused(self) -> bool:
        return self.pause_event.is_set()

    def start(self, pending: List[Job]) -> None:
        self.cancel_event.clear()
        self.pause_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(list(pending),), daemon=True,
            name="conversion-queue",
        )
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.pause_event.clear()      # let any paused workers proceed to cancel

    def toggle_pause(self) -> bool:
        if self.pause_event.is_set():
            self.pause_event.clear()
        else:
            self.pause_event.set()
        return self.pause_event.is_set()

    def join(self, timeout=None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- internals ------------------------------------------------------------

    def _run(self, pending: List[Job]) -> None:
        total = len(pending)
        if total == 0:
            self._finished(0, 0, 0, 0)
            return

        n_workers = max(1, min(8, self._concurrency()))
        n_workers = min(n_workers, total)
        counts = {"done": 0, "fail": 0, "cancel": 0, "completed": 0}
        lock = threading.Lock()

        def update_overall():
            with lock:
                pct = counts["completed"] / total * 100
            self._set_overall(pct)

        def worker(job: Job):
            # Queue-level pause: a not-yet-started job waits here while paused.
            # Jobs already running keep going; only new starts are held back.
            while self.pause_event.is_set() and not self.cancel_event.is_set():
                if job.status != "Paused":
                    job.status = "Paused"
                    self._refresh(job)
                time.sleep(0.2)

            if self.cancel_event.is_set():
                job.status = JobStatus.CANCELLED.value
                self._refresh(job)
                with lock:
                    counts["cancel"] += 1
                    counts["completed"] += 1
                update_overall()
                return

            job.status = "Running"
            self._refresh(job)

            def on_progress(ev, j=job):
                j.apply_progress(ev)
                self._refresh(j)

            # The engine is pure: it returns a result, the controller maps it
            # onto the Job here. pause_event also suspends a running ffmpeg.
            result = self._converter.convert(
                job.to_request(), on_progress, self.cancel_event, self.pause_event)
            job.apply_result(result)
            if result.status in (JobStatus.DONE, JobStatus.FAILED):
                self._record(job, result)

            if result.status == JobStatus.DONE:
                with lock:
                    counts["done"] += 1
                if (self._should_delete()
                        and job.out_path and job.out_path.exists()
                        and job.out_path.resolve() != job.src.resolve()):
                    try:
                        job.src.unlink()
                        job.stage = "Source deleted"
                    except OSError:
                        pass
            elif result.status == JobStatus.CANCELLED:
                with lock:
                    counts["cancel"] += 1
                if job.out_path and job.out_path.exists():
                    try:
                        job.out_path.unlink()
                    except OSError:
                        pass
            else:  # FAILED / SKIPPED
                with lock:
                    counts["fail"] += 1

            self._refresh(job)
            with lock:
                counts["completed"] += 1
            update_overall()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=n_workers, thread_name_prefix="ffmpeg-worker"
        ) as pool:
            list(pool.map(worker, pending))

        self._finished(counts["done"], counts["fail"], counts["cancel"], total)
