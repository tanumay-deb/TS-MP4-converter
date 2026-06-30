"""Best-effort suspend/resume of a running subprocess (to pause a live ffmpeg).

Uses psutil when available; degrades to no-op otherwise (the queue-level pause
still holds not-yet-started jobs, so pausing always does *something*).
"""
from __future__ import annotations

try:
    import psutil
except Exception:  # noqa: BLE001 - optional dependency
    psutil = None


def available() -> bool:
    return psutil is not None


def suspend(proc) -> bool:
    if psutil is None or proc is None or proc.poll() is not None:
        return False
    try:
        psutil.Process(proc.pid).suspend()
        return True
    except Exception:  # noqa: BLE001 - process may have exited
        return False


def resume(proc) -> None:
    if psutil is None or proc is None:
        return
    try:
        psutil.Process(proc.pid).resume()
    except Exception:  # noqa: BLE001
        pass
