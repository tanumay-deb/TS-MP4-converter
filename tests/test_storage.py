"""Crash-safe JSON writes and cache pruning."""
import json
import os
import time

import pytest

from tsconverter import storage


def test_write_json_keeps_the_old_file_when_a_write_fails(tmp_path):
    p = tmp_path / "settings.json"
    storage.write_json(p, {"theme": "dark"})
    with pytest.raises(TypeError):
        storage.write_json(p, {"theme": object()})        # fails mid-write
    assert json.loads(p.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_prune_deletes_only_old_files(tmp_path):
    old, new = tmp_path / "old.log", tmp_path / "new.log"
    old.write_text("x")
    new.write_text("y")
    month_ago = time.time() - 31 * 86400
    os.utime(old, (month_ago, month_ago))
    (tmp_path / "sub").mkdir()                              # folders are left alone
    storage.prune_old_files(tmp_path, tmp_path / "missing")
    assert not old.exists() and new.exists() and (tmp_path / "sub").exists()
