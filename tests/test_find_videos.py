"""Drag-and-drop and Add folder queue only supported videos, and search dropped folders."""
import os

import app


def test_find_videos_searches_folders_and_skips_other_files(tmp_path):
    for name in ("a.ts", "notes.pdf", "sub/b.MKV", "sub/cover.jpg"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"x")
    dropped = [str(tmp_path / "a.ts"), str(tmp_path / "notes.pdf"), str(tmp_path / "sub")]
    found = app.find_videos(dropped)
    assert sorted(os.path.basename(p) for p in found) == ["a.ts", "b.MKV"]
