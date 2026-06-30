"""Best-effort process suspend/resume."""
import subprocess
import sys

import pytest

from tsconverter.media import procctl


def test_none_and_safe_calls():
    assert procctl.suspend(None) is False
    procctl.resume(None)            # must not raise


@pytest.mark.skipif(not procctl.available(), reason="psutil not installed")
def test_suspend_resume_roundtrip_on_real_process():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert procctl.suspend(p) is True
        procctl.resume(p)          # must not raise
    finally:
        p.kill()
        p.wait(timeout=5)
    # suspending an exited process is a no-op, not an error
    assert procctl.suspend(p) is False
