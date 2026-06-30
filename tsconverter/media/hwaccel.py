"""Honest H.264 hardware-encoder detection.

The old approach grepped `ffmpeg -encoders` for a name and assumed it worked.
But the bundled (imageio-ffmpeg / PyPI) ffmpeg is frequently built WITHOUT the
proprietary GPU encoders, so a name match gave a false sense of acceleration and
the code silently fell back to libx264. Here we instead run a tiny real
test-encode and only report an encoder as available if it actually succeeds.
"""
from __future__ import annotations

import platform
import subprocess
from typing import List, Optional

from .ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH

# Platform-appropriate candidates, best-first. macOS videotoolbox was previously
# missing entirely.
_CANDIDATES = {
    "Windows": ["h264_nvenc", "h264_qsv", "h264_amf"],
    "Darwin": ["h264_videotoolbox"],
    "Linux": ["h264_nvenc", "h264_qsv", "h264_vaapi"],
}

_WORKING_CACHE: Optional[List[str]] = None


def _encoder_runs(encoder: str) -> bool:
    """True only if ffmpeg can actually encode a frame with this encoder."""
    cmd = [
        FFMPEG_PATH, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=0.1:size=128x72:rate=5",
        "-frames:v", "1", "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=CREATE_NO_WINDOW, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


def working_hw_encoders(force: bool = False) -> List[str]:
    """H.264 hardware encoders that genuinely work with the resolved ffmpeg."""
    global _WORKING_CACHE
    if _WORKING_CACHE is not None and not force:
        return _WORKING_CACHE
    candidates = _CANDIDATES.get(platform.system(), [])
    _WORKING_CACHE = [c for c in candidates if _encoder_runs(c)]
    return _WORKING_CACHE


def best_h264_encoder(prefer_hw: bool = True) -> str:
    """Pick the fastest working encoder, or libx264 when no HW is usable."""
    if prefer_hw:
        hw = working_hw_encoders()
        if hw:
            return hw[0]
    return "libx264"
