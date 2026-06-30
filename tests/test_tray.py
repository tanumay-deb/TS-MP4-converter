"""Tray wrapper is always safe to construct/use, even with no usable backend."""
from tsconverter import tray


def test_construct_and_methods_never_raise():
    t = tray.Tray("Test", on_show=lambda: None, on_quit=lambda: None)
    # stop / notify must be safe whether or not an icon backend was available
    t.stop()
    t.notify("hello")


def test_available_is_boolean():
    assert isinstance(tray.available(), bool)
