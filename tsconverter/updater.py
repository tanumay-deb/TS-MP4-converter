"""Best-effort update check against GitHub Releases. Stdlib only (no deps)."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional

RELEASES_API = "https://api.github.com/repos/tanumay-deb/TS-MP4-converter/releases/latest"
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass
class UpdateInfo:
    version: str        # normalized, e.g. "1.6.0"
    tag: str            # raw tag, e.g. "v1.6.0"
    url: str            # release page
    notes: str = ""


def _parse(v: str):
    m = _VER_RE.search(v or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    if a is None or b is None:
        return False
    return a > b


def check_for_update(current_version: str, timeout: float = 8.0) -> Optional[UpdateInfo]:
    """Return UpdateInfo when the latest release is newer than current, else None.

    Network or parse failures return None — update checks never raise.
    """
    req = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "TS-MP4-converter",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - any failure => "no update info"
        return None
    tag = str(data.get("tag_name") or "")
    if not tag or not is_newer(tag, current_version):
        return None
    m = _VER_RE.search(tag)
    return UpdateInfo(
        version=m.group(0) if m else tag,
        tag=tag,
        url=str(data.get("html_url")
                or f"https://github.com/tanumay-deb/TS-MP4-converter/releases/tag/{tag}"),
        notes=str(data.get("body") or "")[:4000],
    )
