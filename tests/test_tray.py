"""Tray wrapper is always safe to construct/use, even with no usable backend."""
from tsconverter import tray


def test_construct_and_methods_never_raise():
    t = tray.Tray("Test", on_show=lambda: None, on_quit=lambda: None)
    # stop / notify must be safe whether or not an icon backend was available
    t.stop()
    t.notify("hello")


def test_available_is_boolean():
    assert isinstance(tray.available(), bool)


class _NoTray:
    def run_detached(self):
        raise NotImplementedError("no tray here")   # e.g. macOS, Tk owns the main thread


def test_start_reports_failure_so_the_window_stays():
    t = tray.Tray.__new__(tray.Tray)
    t._icon = _NoTray()
    assert t.start() is False
    t._icon = None                                    # pystray missing
    assert t.start() is False
