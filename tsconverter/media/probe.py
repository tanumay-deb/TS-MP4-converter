"""Inspect a media file with `ffprobe -print_format json`.

Replaces the old fragile regex-on-stderr duration guessing. When no ffprobe is
available, falls back to parsing `ffmpeg -i` stderr so the app still functions.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from .ffmpeg import CREATE_NO_WINDOW, FFMPEG_PATH, FFPROBE_PATH

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")


@dataclass
class MediaInfo:
    duration: float = 0.0          # seconds; 0.0 if unknown
    format_name: str = ""
    has_video: bool = False        # excludes attached cover-art "video" streams
    has_audio: bool = False
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    width: int = 0
    height: int = 0
    ok: bool = False               # container parsed and at least one A/V stream
    source: str = "none"           # "ffprobe" | "ffmpeg-fallback" | "none"


def _hms(h, m, s) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


TS_SYNC = 0x47          # MPEG-TS packet sync byte
TS_PACKET = 188         # standard transport stream packet size


def detect_ts_offset(src, scan_bytes: int = 65536, max_prefix: int = 4096) -> int:
    """Return the byte offset where a junk-prefixed MPEG-TS stream really starts.

    Some 'fake' .ts files have junk bytes (often a tiny PNG) prepended so that
    ffmpeg sniffs the wrong format (e.g. png_pipe, a 1x1 image) and never finds
    the video. The real transport stream begins at the first 0x47 sync byte that
    recurs at the 188-byte packet stride. Returns 0 for clean files (the stream
    already starts at byte 0) or if no transport stream is found.
    """
    try:
        with open(src, "rb") as fp:
            buf = fp.read(scan_bytes)
    except OSError:
        return 0
    n = len(buf)
    need = TS_PACKET * 2
    if n < need + 1:
        return 0
    upper = min(max_prefix, n - need)
    for off in range(upper + 1):
        if (buf[off] == TS_SYNC
                and buf[off + TS_PACKET] == TS_SYNC
                and buf[off + 2 * TS_PACKET] == TS_SYNC):
            return off
    return 0


def _skip_opts(skip_bytes: int) -> list:
    # A junk-prefixed .ts needs the same skip + forced demuxer ffmpeg gets.
    return ["-skip_initial_bytes", str(skip_bytes), "-f", "mpegts"] if skip_bytes else []


def _probe_ffprobe(src, skip_bytes: int) -> Optional[MediaInfo]:
    if not FFPROBE_PATH:
        return None
    cmd = [FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", *_skip_opts(skip_bytes), str(src)]
    try:
        # UTF-8: the JSON holds the file name, and the Windows default (cp1252) failed on
        # names like "●", so probing (and the output check) saw no streams at all.
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", creationflags=CREATE_NO_WINDOW, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    info = MediaInfo(source="ffprobe")
    fmt = data.get("format") or {}
    info.format_name = fmt.get("format_name", "") or ""
    try:
        info.duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        info.duration = 0.0

    for st in data.get("streams", []):
        ctype = st.get("codec_type")
        if ctype == "video" and not info.has_video:
            if (st.get("disposition") or {}).get("attached_pic"):
                continue  # cover art, not real video
            info.has_video = True
            info.vcodec = st.get("codec_name")
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            if not info.duration:
                try:
                    info.duration = float(st.get("duration") or 0.0)
                except (TypeError, ValueError):
                    pass
        elif ctype == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = st.get("codec_name")

    info.ok = info.has_video or info.has_audio
    return info


def _probe_ffmpeg(src, skip_bytes: int) -> MediaInfo:
    cmd = [FFMPEG_PATH, "-hide_banner", *_skip_opts(skip_bytes), "-i", str(src)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", creationflags=CREATE_NO_WINDOW, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return MediaInfo(source="none")
    stderr = proc.stderr or ""
    info = MediaInfo(source="ffmpeg-fallback")
    m = _DURATION_RE.search(stderr)
    if m:
        info.duration = _hms(*m.groups())
    info.has_video = "Video:" in stderr
    info.has_audio = "Audio:" in stderr
    info.ok = info.has_video or info.has_audio
    return info


def probe(src, skip_bytes: int = 0) -> MediaInfo:
    """Return a MediaInfo for `src`. Prefers ffprobe-JSON, falls back to ffmpeg.

    `skip_bytes` mirrors the junk-header skip used for fake `.ts` files.
    """
    info = _probe_ffprobe(src, skip_bytes)
    if info is not None:
        return info
    return _probe_ffmpeg(src, skip_bytes)
