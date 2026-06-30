"""Extract a representative thumbnail frame from a media file (best-effort).

Cached by source path + size + mtime + width, as PNG, in a temp dir. Returns
None for audio-only files or any failure — callers treat "no thumbnail" as fine.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH
from .probe import probe

_CACHE_DIR = Path(tempfile.gettempdir()) / "TSConverter_thumbs"


def _cache_key(src: Path, width: int) -> str:
    try:
        st = src.stat()
        sig = f"{src.resolve()}|{st.st_size}|{st.st_mtime_ns}|{width}"
    except OSError:
        sig = f"{src}|{width}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def extract_thumbnail(src, width: int = 320, timeout: float = 20.0) -> Optional[Path]:
    src = Path(src)
    if not src.exists():
        return None
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    dest = _CACHE_DIR / f"{_cache_key(src, width)}.png"
    if dest.exists():
        return dest

    # Seek a little in to skip black intros; use a known duration when available.
    info = probe(src)
    if info.duration and not info.has_video:
        return None                       # audio-only: no frame to grab
    ss = max(0.0, info.duration * 0.2) if info.duration else 1.0
    cmd = [
        FFMPEG_PATH, "-y", "-ss", f"{ss:.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-1",
        "-loglevel", "error", str(dest),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True,
                              creationflags=CREATE_NO_WINDOW, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    return dest if (proc.returncode == 0 and dest.exists()) else None
