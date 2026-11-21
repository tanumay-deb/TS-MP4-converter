"""Update-checker: semver comparison and the GitHub release parse (mocked)."""
import json

import tsconverter.updater as u


def test_is_newer_handles_two_and_three_part_versions():
    assert u.is_newer("v1.5.0", "1.4")          # APP_VERSION is "1.4"
    assert u.is_newer("1.4.1", "1.4.0")
    assert u.is_newer("v2.0.0", "1.9.9")
    assert not u.is_newer("v1.4.0", "1.4")      # 1.4 == 1.4.0
    assert not u.is_newer("v1.3.0", "1.4.0")
    assert not u.is_newer("garbage", "1.4.0")


def test_release_notes_extracts_one_version_as_plain_bullets():
    md = ("# Changelog\n\n## Unreleased\n- wip\n\n"
          "## v1.2.0 (2026-01-01)\n- **Bold** `code`\n  wrapped on\n- two\n\n## v1.1.0\n- old\n")
    assert u.release_notes("1.2.0", md) == ["Bold code wrapped on", "two"]
    assert u.release_notes("1.1.0", md) == ["old"]
    assert u.release_notes("1.2", md) == []
    assert u.release_notes("9.9.9", md) == []


def test_notes_since_covers_skipped_versions():
    md = "## v1.3.0\n- c\n\n## v1.2.0\n- b\n\n## v1.1.0\n- a\n"
    assert u.notes_since("1.1.0", "1.3.0", md) == [("1.3.0", ["c"]), ("1.2.0", ["b"])]
    assert u.notes_since("", "1.3.0", md) == [("1.3.0", ["c"])]        # unknown: current only
    assert u.notes_since("1.3.0", "1.3.0", md) == [("1.3.0", ["c"])]
    assert u.notes_since("9.0.0", "1.3.0", md) == [("1.3.0", ["c"])]   # downgrade


def test_changelog_has_notes_for_current_version():
    # The app pops these up on the first launch of each version: never ship without them.
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app_src = (root / "app.py").read_text(encoding="utf-8")
    version = re.search(r'^APP_VERSION = "(.+)"', app_src, re.M).group(1)
    assert u.release_notes(version, (root / "CHANGELOG.md").read_text(encoding="utf-8")), \
        f"CHANGELOG.md has no '## v{version}' section"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _mock_release(monkeypatch, obj):
    payload = json.dumps(obj).encode("utf-8")
    monkeypatch.setattr(u.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))


def test_check_for_update_returns_info_when_newer(monkeypatch):
    _mock_release(monkeypatch, {"tag_name": "v2.0.0",
                                "html_url": "https://example/r", "body": "notes"})
    info = u.check_for_update("1.4")
    assert info is not None
    assert info.tag == "v2.0.0" and info.version == "2.0.0"
    assert info.url == "https://example/r" and info.notes == "notes"


def test_check_for_update_none_when_same_version(monkeypatch):
    _mock_release(monkeypatch, {"tag_name": "v1.4.0"})
    assert u.check_for_update("1.4") is None


def test_check_for_update_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(u.urllib.request, "urlopen", boom)
    assert u.check_for_update("1.4") is None


_DL = "https://github.com/tanumay-deb/TS-MP4-converter/releases/download/v2.0.0/"


def test_check_for_update_extracts_setup_asset(monkeypatch):
    _mock_release(monkeypatch, {
        "tag_name": "v2.0.0",
        "assets": [
            {"name": "TSConverter-2.0.0-portable.zip", "browser_download_url": _DL + "p.zip", "size": 1},
            {"name": "TSConverter-2.0.0-setup.exe", "browser_download_url": _DL + "s.exe", "size": 12345},
        ],
    })
    info = u.check_for_update("1.7.0")
    assert info.setup_name == "TSConverter-2.0.0-setup.exe"
    assert info.setup_size == 12345 and info.setup_url == _DL + "s.exe"


def test_setup_asset_from_untrusted_host_is_ignored(monkeypatch):
    _mock_release(monkeypatch, {
        "tag_name": "v2.0.0",
        "assets": [{"name": "x-setup.exe", "browser_download_url": "https://evil.example/x.exe", "size": 1}],
    })
    assert u.check_for_update("1.7.0").setup_url is None


def test_download_rejects_untrusted_url(tmp_path):
    dest = tmp_path / "x.exe"
    assert u.download("https://evil.example/setup.exe", str(dest)) is False
    assert not dest.exists()


class _DlResp:
    def __init__(self, data):
        self.headers = {"Content-Length": str(len(data))}
        self._data, self._pos = data, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=65536):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


def test_download_writes_file_and_reports_progress(tmp_path, monkeypatch):
    payload = b"data" * 500
    monkeypatch.setattr(u.urllib.request, "urlopen",
                        lambda req, timeout=30: _DlResp(payload))
    dest = tmp_path / "setup.exe"
    progress = []
    ok = u.download(_DL + "s.exe", str(dest), on_progress=lambda r, t: progress.append((r, t)))
    assert ok and dest.read_bytes() == payload
    assert progress and progress[-1] == (len(payload), len(payload))
