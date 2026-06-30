"""Junk-prefixed .ts detection — pure, no external binaries."""
import converter as c


def _make(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_detect_offset_on_fake_png_prefixed_ts(tmp_path):
    junk = b"\x89PNG\r\n\x1a\n" + b"\x00" * 62                       # 70-byte fake header
    ts = b"".join(bytes([0x47]) + b"\x00" * 187 for _ in range(5))   # 5 TS packets
    fake = _make(tmp_path, "fake.ts", junk + ts)
    clean = _make(tmp_path, "clean.ts", ts)
    assert c.detect_ts_offset(fake) == 70
    assert c.detect_ts_offset(clean) == 0


def test_ts_input_opts(tmp_path):
    junk = b"\x89PNG\r\n\x1a\n" + b"\x00" * 62
    ts = b"".join(bytes([0x47]) + b"\x00" * 187 for _ in range(5))
    fake = _make(tmp_path, "fake.ts", junk + ts)
    clean = _make(tmp_path, "clean.ts", ts)
    assert c.ts_input_opts(fake) == ["-skip_initial_bytes", "70", "-f", "mpegts"]
    assert c.ts_input_opts(clean) == []
    # non-.ts inputs are never touched
    mkv = _make(tmp_path, "x.mkv", ts)
    assert c.ts_input_opts(mkv) == []
