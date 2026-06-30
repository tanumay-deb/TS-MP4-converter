"""Format handlers build the right output-side ffmpeg args."""
from tsconverter.media import handlers as H


def test_registry_has_expected_formats_and_default():
    assert {"mp4", "mkv", "mov", "webm", "mp3", "m4a", "wav", "flac", "opus"} <= set(H.REGISTRY)
    assert H.get_handler("nonexistent").id == "mp4"


def test_ext_matches_id():
    for fid, h in H.REGISTRY.items():
        assert h.ext == "." + fid


def test_mp4_remux_adds_adtstoasc_only_for_ts_sources():
    h = H.get_handler("mp4")
    ts_args = h.remux_out_args("clip.ts")
    assert "-c" in ts_args and "copy" in ts_args
    assert "aac_adtstoasc" in ts_args and "+faststart" in ts_args
    assert "aac_adtstoasc" not in h.remux_out_args("clip.mkv")


def test_mkv_remux_has_no_faststart():
    args = H.get_handler("mkv").remux_out_args("a.ts")
    assert "copy" in args and "+faststart" not in args


def test_video_reencode_uses_selected_h264_encoder(monkeypatch):
    monkeypatch.setattr(H, "best_h264_encoder", lambda prefer_hw=True: "libx264")
    args, used = H.get_handler("mp4").reencode_out_args(prefer_hw=False)
    assert used == "libx264"
    assert "-c:v" in args and "libx264" in args and "aac" in args


def test_webm_is_reencode_only_vp9_opus():
    h = H.get_handler("webm")
    assert h.can_remux is False
    args, used = h.reencode_out_args(prefer_hw=False)
    assert used == "libvpx-vp9"
    assert "libvpx-vp9" in args and "libopus" in args


def test_mp3_is_audio_only_libmp3lame():
    h = H.get_handler("mp3")
    assert h.kind == "audio" and h.expects_video() is False and h.can_remux is False
    args, used = h.reencode_out_args(prefer_hw=False)
    assert used == "libmp3lame"
    assert "-vn" in args and "libmp3lame" in args


def test_m4a_remux_copies_aac_and_reencodes_to_aac():
    h = H.get_handler("m4a")
    assert h.can_remux is True and h.kind == "audio"
    assert "copy" in h.remux_out_args("a.mp4")
    args, used = h.reencode_out_args(prefer_hw=False)
    assert used == "aac" and "-vn" in args


def test_wav_uses_pcm():
    args, used = H.get_handler("wav").reencode_out_args(prefer_hw=False)
    assert used == "pcm_s16le" and "-vn" in args
