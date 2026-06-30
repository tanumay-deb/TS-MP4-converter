"""Output-format handlers — the internal "plugin" registry.

The engine builds the common input side (junk-header skip, ``-i src``) and the
shared run machinery; each handler supplies the OUTPUT-side ffmpeg args for its
container/codecs. No third-party plugin API — formats are registered here.
"""
from __future__ import annotations

from typing import List, Tuple

from .hwaccel import best_h264_encoder

_TS_FAMILY = (".ts", ".m2ts", ".mts")


def _h264_video_args(prefer_hw: bool) -> Tuple[List[str], str]:
    """``-c:v <encoder>`` plus quality params; returns (args, encoder_name)."""
    encoder = best_h264_encoder(prefer_hw)
    args = ["-c:v", encoder]
    if encoder == "libx264":
        args += ["-preset", "veryfast", "-crf", "23"]
    elif encoder == "h264_nvenc":
        args += ["-preset", "p4", "-cq", "23", "-rc", "vbr"]
    elif encoder == "h264_qsv":
        args += ["-preset", "veryfast", "-global_quality", "23"]
    elif encoder == "h264_amf":
        args += ["-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]
    return args, encoder


class FormatHandler:
    id: str = ""
    ext: str = ""
    kind: str = "video"          # "video" | "audio"
    label: str = ""
    can_remux: bool = True       # whether a stream-copy remux is worth attempting

    def expects_video(self) -> bool:
        return self.kind == "video"

    def remux_out_args(self, src) -> List[str]:
        """Output-side args for a stream-copy. `src` allows source-aware filters."""
        raise NotImplementedError

    def reencode_out_args(self, prefer_hw: bool) -> Tuple[List[str], str]:
        """Output-side args for a re-encode; returns (args, used_label)."""
        raise NotImplementedError


# --- video containers ---------------------------------------------------------

class _Mp4LikeHandler(FormatHandler):
    """mp4 / mov: H.264 + AAC, faststart, aac_adtstoasc for MPEG-TS sources."""
    kind = "video"
    _faststart = True

    def remux_out_args(self, src) -> List[str]:
        args = ["-map", "0:v?", "-map", "0:a?", "-c", "copy"]
        if str(src).lower().endswith(_TS_FAMILY):
            # AAC in MPEG-TS uses ADTS framing; MP4/MOV need ASC.
            args += ["-bsf:a", "aac_adtstoasc"]
        args += ["-avoid_negative_ts", "make_zero"]
        if self._faststart:
            args += ["-movflags", "+faststart"]
        return args

    def reencode_out_args(self, prefer_hw: bool) -> Tuple[List[str], str]:
        vargs, enc = _h264_video_args(prefer_hw)
        args = ["-map", "0:v?", "-map", "0:a?", *vargs, "-c:a", "aac", "-b:a", "192k"]
        if self._faststart:
            args += ["-movflags", "+faststart"]
        return args, enc


class Mp4Handler(_Mp4LikeHandler):
    id, ext, label = "mp4", ".mp4", "MP4 (H.264/AAC)"


class MovHandler(_Mp4LikeHandler):
    id, ext, label = "mov", ".mov", "MOV (H.264/AAC)"


class MkvHandler(FormatHandler):
    id, ext, label, kind = "mkv", ".mkv", "MKV (H.264/AAC)", "video"

    def remux_out_args(self, src) -> List[str]:
        return ["-map", "0:v?", "-map", "0:a?", "-c", "copy"]

    def reencode_out_args(self, prefer_hw: bool) -> Tuple[List[str], str]:
        vargs, enc = _h264_video_args(prefer_hw)
        return ["-map", "0:v?", "-map", "0:a?", *vargs, "-c:a", "aac", "-b:a", "192k"], enc


class WebmHandler(FormatHandler):
    # WebM can't hold H.264/AAC, so a copy is never valid — always re-encode.
    id, ext, label, kind, can_remux = "webm", ".webm", "WebM (VP9/Opus)", "video", False

    def remux_out_args(self, src) -> List[str]:
        return ["-map", "0:v?", "-map", "0:a?", "-c", "copy"]  # unused

    def reencode_out_args(self, prefer_hw: bool) -> Tuple[List[str], str]:
        return (["-map", "0:v?", "-map", "0:a?",
                 "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
                 "-c:a", "libopus", "-b:a", "128k"], "libvpx-vp9")


# --- audio targets (drop the video stream) ------------------------------------

class _AudioHandler(FormatHandler):
    kind = "audio"
    _acodec = ""
    _aargs: List[str] = []
    _faststart = False

    def remux_out_args(self, src) -> List[str]:
        args = ["-vn", "-map", "0:a?", "-c:a", "copy"]
        if self._faststart:
            args += ["-movflags", "+faststart"]
        return args

    def reencode_out_args(self, prefer_hw: bool) -> Tuple[List[str], str]:
        args = ["-vn", "-map", "0:a?", "-c:a", self._acodec, *self._aargs]
        if self._faststart:
            args += ["-movflags", "+faststart"]
        return args, self._acodec


class Mp3Handler(_AudioHandler):
    id, ext, label, can_remux = "mp3", ".mp3", "MP3 (audio)", False
    _acodec, _aargs = "libmp3lame", ["-q:a", "2"]


class M4aHandler(_AudioHandler):
    # AAC copies straight into m4a, so remux is worth a try.
    id, ext, label, can_remux = "m4a", ".m4a", "M4A / AAC (audio)", True
    _acodec, _aargs, _faststart = "aac", ["-b:a", "192k"], True


class WavHandler(_AudioHandler):
    id, ext, label, can_remux = "wav", ".wav", "WAV (audio)", False
    _acodec, _aargs = "pcm_s16le", []


class FlacHandler(_AudioHandler):
    id, ext, label, can_remux = "flac", ".flac", "FLAC (audio)", False
    _acodec, _aargs = "flac", []


class OpusHandler(_AudioHandler):
    id, ext, label, can_remux = "opus", ".opus", "Opus (audio)", False
    _acodec, _aargs = "libopus", ["-b:a", "160k"]


# Ordered: video containers first, then audio targets.
_HANDLERS = [
    Mp4Handler(), MkvHandler(), MovHandler(), WebmHandler(),
    Mp3Handler(), M4aHandler(), WavHandler(), FlacHandler(), OpusHandler(),
]
REGISTRY = {h.id: h for h in _HANDLERS}
DEFAULT_FORMAT = "mp4"


def get_handler(fmt: str) -> FormatHandler:
    return REGISTRY.get(fmt) or REGISTRY[DEFAULT_FORMAT]
