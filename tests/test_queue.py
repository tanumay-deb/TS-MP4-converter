"""QueueController runs jobs, maps results onto Jobs, and reports counts —
without any UI or real ffmpeg."""
import threading
from pathlib import Path

from tsconverter.models import ConversionResult, JobStatus, Job, ProgressEvent
from tsconverter.queue import QueueController


class FakeConverter:
    def __init__(self, status_by_name):
        self.status_by_name = status_by_name
        self.ended = None
        self.queued = None

    def convert(self, request, on_progress, cancel_event, pause_event=None):
        self.queued = request.queued_sources
        on_progress(ProgressEvent(stage="Running", progress_pct=50.0))
        status = self.status_by_name.get(request.src.name, JobStatus.DONE)
        return ConversionResult(status=status, out_path=Path(request.src.stem + ".mp4"),
                                duration=1.0, used_encoder="fake")

    def end_batch(self, out_paths):
        self.ended = list(out_paths)


def test_queue_runs_all_jobs_and_reports_counts():
    jobs = [Job(src=Path(f"{n}.ts"), out_dir=Path("o")) for n in ("a", "b", "c")]
    conv = FakeConverter({"b.ts": JobStatus.FAILED})

    recorded, finished, done_evt = [], {}, threading.Event()

    def on_finished(d, f, c, t):
        finished.update(done=d, fail=f, cancel=c, total=t)
        done_evt.set()

    qc = QueueController(
        conv,
        refresh=lambda j: None,
        record=lambda j, r: recorded.append(j.src.name),
        set_overall=lambda pct: None,
        finished=on_finished,
        concurrency=lambda: 2,
        should_delete_source=lambda: False,
    )
    qc.start(jobs)

    assert done_evt.wait(10)
    assert finished == {"done": 2, "fail": 1, "cancel": 0, "total": 3}
    assert {j.status for j in jobs} == {"Done", "Failed"}
    assert sorted(recorded) == ["a.ts", "b.ts", "c.ts"]   # done + failed both recorded
    # Outputs are freed once, after the whole batch, not per job.
    assert sorted(p.name for p in conv.ended) == ["a.mp4", "b.mp4", "c.mp4"]
    # Every job knows the batch's sources, so Overwrite can't replace one still queued.
    assert conv.queued == {Path("a.ts"), Path("b.ts"), Path("c.ts")}


def test_delete_source_only_after_a_real_done(tmp_path):
    # The only code that destroys user files: Done with a separate output deletes
    # the source; Failed, Skipped, or an "output" that is the source itself never do.
    src = {n: tmp_path / f"{n}.ts" for n in ("ok", "bad", "skip", "same")}
    for p in src.values():
        p.write_bytes(b"x")
    out_ok = tmp_path / "ok.mp4"
    out_ok.write_bytes(b"y")
    results = {
        "ok.ts": ConversionResult(status=JobStatus.DONE, out_path=out_ok),
        "bad.ts": ConversionResult(status=JobStatus.FAILED, out_path=tmp_path / "bad.part.mp4"),
        "skip.ts": ConversionResult(status=JobStatus.SKIPPED),
        "same.ts": ConversionResult(status=JobStatus.DONE, out_path=src["same"]),
    }

    class Conv:
        def convert(self, request, on_progress, cancel_event, pause_event=None):
            return results[request.src.name]

        def end_batch(self, out_paths):
            pass

    finished, done_evt = {}, threading.Event()
    qc = QueueController(
        Conv(), refresh=lambda j: None, record=lambda j, r: None,
        set_overall=lambda p: None,
        finished=lambda d, f, c, t: (finished.update(done=d, fail=f), done_evt.set()),
        concurrency=lambda: 2, should_delete_source=lambda: True,
    )
    qc.start([Job(src=p, out_dir=tmp_path) for p in src.values()])
    assert done_evt.wait(10)
    assert not src["ok"].exists()
    assert src["bad"].exists() and src["skip"].exists() and src["same"].exists()
    assert finished == {"done": 3, "fail": 1}          # skipped counts as done, not failed


class DiskFullConverter:
    """First attempts run side by side and run out of space; alone, 'a' fits, 'b' doesn't."""
    def __init__(self):
        self.calls, self.active, self.max_alone = [], 0, 0
        self.both_in = threading.Barrier(2, timeout=5)
        self.lock = threading.Lock()

    def convert(self, request, on_progress, cancel_event, pause_event=None):
        name = request.src.name
        with self.lock:
            first = name not in self.calls
            self.calls.append(name)
            self.active += 1
            if not first:
                self.max_alone = max(self.max_alone, self.active)
        if first:
            self.both_in.wait()                  # force the two first attempts to overlap
        with self.lock:
            self.active -= 1
        if first or name == "b.ts":
            return ConversionResult(status=JobStatus.FAILED, error="Not enough free space",
                                    disk_full=True)
        return ConversionResult(status=JobStatus.DONE, out_path=Path("a.mp4"))

    def end_batch(self, out_paths):
        pass


def _run_queue(conv, jobs, concurrency):
    finished, done_evt = {}, threading.Event()
    qc = QueueController(
        conv, refresh=lambda j: None, record=lambda j, r: None, set_overall=lambda p: None,
        finished=lambda d, f, c, t: (finished.update(done=d, fail=f, cancel=c, total=t),
                                     done_evt.set()),
        concurrency=lambda: concurrency, should_delete_source=lambda: False,
    )
    qc.start(jobs)
    assert done_evt.wait(10)
    return finished


def test_parallel_disk_full_failures_retry_one_at_a_time():
    conv = DiskFullConverter()
    jobs = [Job(src=Path(n), out_dir=Path("o")) for n in ("a.ts", "b.ts")]
    finished = _run_queue(conv, jobs, concurrency=2)
    assert sorted(conv.calls) == ["a.ts", "a.ts", "b.ts", "b.ts"]   # each retried once
    assert conv.max_alone == 1                                       # retries ran alone
    assert [j.status for j in jobs] == ["Done", "Failed"]            # b doesn't fit at all
    assert finished == {"done": 1, "fail": 1, "cancel": 0, "total": 2}


def test_disk_full_alone_is_not_retried():
    class Conv:
        calls = 0

        def convert(self, request, on_progress, cancel_event, pause_event=None):
            Conv.calls += 1
            return ConversionResult(status=JobStatus.FAILED, disk_full=True)

        def end_batch(self, out_paths):
            pass

    finished = _run_queue(Conv(), [Job(src=Path("big.ts"), out_dir=Path("o"))], concurrency=2)
    assert Conv.calls == 1 and finished["fail"] == 1


def test_toggle_pause_flips_state():
    qc = QueueController(
        FakeConverter({}), refresh=lambda j: None, record=lambda j, r: None,
        set_overall=lambda p: None, finished=lambda *a: None,
        concurrency=lambda: 1, should_delete_source=lambda: False,
    )
    assert qc.is_paused() is False
    assert qc.toggle_pause() is True and qc.is_paused() is True
    assert qc.toggle_pause() is False and qc.is_paused() is False
