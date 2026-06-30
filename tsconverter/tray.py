"""Optional system-tray icon via pystray. No-op when pystray/Pillow are absent."""
from __future__ import annotations

from typing import Callable

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # noqa: BLE001 - optional dependency
    pystray = None
    Image = None


def available() -> bool:
    return pystray is not None and Image is not None


def _make_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 61, 61], radius=12, fill=(37, 99, 235, 255))
    d.polygon([(24, 16), (24, 48), (50, 32)], fill=(255, 255, 255, 255))  # play glyph
    return img


class Tray:
    """A pystray icon running in its own detached thread. Safe to create even
    when pystray is missing (every method becomes a no-op)."""

    def __init__(self, title: str, on_show: Callable[[], None], on_quit: Callable[[], None]):
        self._icon = None
        if not available():
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show", lambda icon, item: on_show(), default=True),
                pystray.MenuItem("Quit", lambda icon, item: on_quit()),
            )
            self._icon = pystray.Icon("tsconverter", _make_image(), title, menu)
        except Exception:  # noqa: BLE001 - no usable tray backend (e.g. headless)
            self._icon = None

    def start(self) -> None:
        if self._icon is not None:
            try:
                self._icon.run_detached()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def notify(self, message: str, title: str = "TS to MP4 Converter") -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:  # noqa: BLE001
                pass
