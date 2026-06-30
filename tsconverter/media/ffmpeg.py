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


_FFMPEG_NAMES = ("ffmpeg.exe", "ffmpeg")
_FFPROBE_NAMES = ("ffprobe.exe", "ffprobe")


def _frozen_base() -> Optional[Path]:
    """Root of the unpacked bundle in a PyInstaller build, else None."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).resolve().parent
    return None


def _bundled_dir() -> Optional[Path]:
    """Where the shared ffmpeg/ffprobe live inside a frozen build (bundle root)."""
    return _frozen_base()


def _dev_bin() -> Optional[Path]:
    """Repo-level bin/ populated by build.ps1, for source/dev runs."""
    if getattr(sys, "frozen", False):
        return None
    return Path(__file__).resolve().parents[2] / "bin"


def _first_existing(directory: Optional[Path], names) -> Optional[str]:
    if not directory:
        return None
    for name in names:
        cand = directory / name
        if cand.exists():
            return str(cand)
    return None


def _resolve(env_var: str, names, imageio_path: Optional[str]) -> Optional[str]:
    env = os.environ.get(env_var)
    if env and Path(env).exists():
        return env
    for directory in (_bundled_dir(), _dev_bin()):
        hit = _first_existing(directory, names)
        if hit:
            return hit
    if imageio_path and Path(imageio_path).exists():
        return imageio_path
    return shutil.which(names[-1])  # plain "ffmpeg"/"ffprobe" on PATH


def _resolve_ffmpeg() -> str:
    return _resolve("TSCONVERTER_FFMPEG", _FFMPEG_NAMES, _IMAGEIO_FFMPEG) or "ffmpeg"


def _resolve_ffprobe() -> Optional[str]:
    # imageio-ffmpeg provides no ffprobe, so there is no imageio fallback here.
    return _resolve("TSCONVERTER_FFPROBE", _FFPROBE_NAMES, None)


FFMPEG_PATH: str = _resolve_ffmpeg()
FFPROBE_PATH: Optional[str] = _resolve_ffprobe()
