"""Locate the ffmpeg / ffprobe binaries and expose shared subprocess flags.

Resolution order (first hit wins):
  ffmpeg   : $TSCONVERTER_FFMPEG  ->  imageio-ffmpeg bundle  ->  PATH  ->  "ffmpeg"
  ffprobe  : $TSCONVERTER_FFPROBE ->  next to the frozen app ->  next to ffmpeg ->  PATH

imageio-ffmpeg ships only ffmpeg (no ffprobe), so frozen builds bundle a static
ffprobe next to the app; in dev we fall back to a system ffprobe on PATH. When no
ffprobe can be found, FFPROBE_PATH is None and probing degrades to ffmpeg (see
probe.py).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# Suppress the console window ffmpeg/ffprobe would otherwise flash on Windows.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

try:
    import imageio_ffmpeg
    _IMAGEIO_FFMPEG: Optional[str] = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # noqa: BLE001 - any import/lookup failure -> fall back to PATH
    _IMAGEIO_FFMPEG = None


def _frozen_base() -> Optional[Path]:
    """Directory holding bundled binaries in a PyInstaller build, else None."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).resolve().parent
    return None


def _first_existing(directory: Optional[Path], names) -> Optional[str]:
    if not directory:
        return None
    for name in names:
        cand = directory / name
        if cand.exists():
            return str(cand)
    return None


def _resolve_ffmpeg() -> str:
    env = os.environ.get("TSCONVERTER_FFMPEG")
    if env and Path(env).exists():
        return env
    if _IMAGEIO_FFMPEG and Path(_IMAGEIO_FFMPEG).exists():
        return _IMAGEIO_FFMPEG
    return shutil.which("ffmpeg") or "ffmpeg"


def _resolve_ffprobe() -> Optional[str]:
    env = os.environ.get("TSCONVERTER_FFPROBE")
    if env and Path(env).exists():
        return env
    names = ("ffprobe.exe", "ffprobe")
    bundled = _first_existing(_frozen_base(), names)
    if bundled:
        return bundled
    if _IMAGEIO_FFMPEG:
        sibling = _first_existing(Path(_IMAGEIO_FFMPEG).parent, names)
        if sibling:
            return sibling
    return shutil.which("ffprobe")


FFMPEG_PATH: str = _resolve_ffmpeg()
FFPROBE_PATH: Optional[str] = _resolve_ffprobe()
