"""The Job view-model is the single place engine results map onto UI state."""
from pathlib import Path

from tsconverter.models import (
    ConversionResult,
    Job,
    JobStatus,
    Mode,
    ProgressEvent,
)


def test_to_request_carries_fields():
    j = Job(src=Path("a.ts"), out_dir=Path("o"), mode=Mode.REENCODE, duration=5.0)
    r = j.to_request()
    assert r.src == Path("a.ts") and r.out_dir == Path("o")
    assert r.mode == Mode.REENCODE and r.duration == 5.0


def test_apply_progress_updates_view_fields():
    j = Job(src=Path("a.ts"), out_dir=Path("o"))
    j.apply_progress(ProgressEvent(stage="Remuxing", seconds_done=2.0, speed=10.0,
                                   progress_pct=40.0, eta_seconds=3.0, duration=5.0))
    assert j.stage == "Remuxing" and j.seconds_done == 2.0 and j.speed == 10.0
    assert j.progress_pct == 40.0 and j.eta_seconds == 3.0
    assert j.duration == 5.0      # live Length update


def test_apply_result_done_sets_status_and_full_progress():
    j = Job(src=Path("a.ts"), out_dir=Path("o"))
    j.apply_result(ConversionResult(
        status=JobStatus.DONE, out_path=Path("o/a.mp4"), duration=5.0,
        used_encoder="remux", verify_message="OK", log_path=Path("l.log"),
        started_at=1.0, completed_at=2.0,
    ))
    assert j.status == "Done" and j.progress_pct == 100.0
    assert j.out_path == Path("o/a.mp4") and j.actually_used == "remux"
    assert j.duration == 5.0 and j.verify_message == "OK"


def test_apply_result_failed_carries_error():
    j = Job(src=Path("a.ts"), out_dir=Path("o"))
    j.apply_result(ConversionResult(status=JobStatus.FAILED, error="boom",
                                    error_full="boom detail"))
    assert j.status == "Failed" and j.error == "boom" and j.error_full == "boom detail"
