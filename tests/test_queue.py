"""QueueController runs jobs, maps results onto Jobs, and reports counts —
without any UI or real ffmpeg."""
import threading
from pathlib import Path

from tsconverter.models import ConversionResult, JobStatus, Job, ProgressEvent
from tsconverter.queue import QueueController


class FakeConverter:
    def __init__(self, status_by_name):
        self.status_by_name = status_by_name

    def convert(self, request, on_progress, cancel_event, pause_event=None):
        on_progress(ProgressEvent(stage="Running", progress_pct=50.0))
        status = self.status_by_name.get(request.src.name, JobStatus.DONE)
        return ConversionResult(status=status, duration=1.0, used_encoder="fake")


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


def test_toggle_pause_flips_state():
    qc = QueueController(
        FakeConverter({}), refresh=lambda j: None, record=lambda j, r: None,
        set_overall=lambda p: None, finished=lambda *a: None,
        concurrency=lambda: 1, should_delete_source=lambda: False,
    )
    assert qc.is_paused() is False
    assert qc.toggle_pause() is True and qc.is_paused() is True
    assert qc.toggle_pause() is False and qc.is_paused() is False
