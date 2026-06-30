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
