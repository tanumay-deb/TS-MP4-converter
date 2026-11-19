"""Feedback form link: hidden until configured; version + OS prefilled and URL-encoded."""
from tsconverter import feedback


def test_form_url_empty_until_configured(monkeypatch):
    monkeypatch.setattr(feedback, "FORM_URL", "")
    assert feedback.form_url("1.7.3") == ""


def test_form_url_prefills_version_and_os(monkeypatch):
    monkeypatch.setattr(feedback, "FORM_URL",
                        "https://f.example/viewform?usp=pp_url&entry.1={version}&entry.2={os}")
    monkeypatch.setattr(feedback.platform, "platform", lambda: "Windows-11 build")
    assert feedback.form_url("1.7.3") == \
        "https://f.example/viewform?usp=pp_url&entry.1=1.7.3&entry.2=Windows-11%20build"
