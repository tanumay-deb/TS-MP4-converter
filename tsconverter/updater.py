"""Best-effort update check + self-update download against GitHub Releases.
Stdlib only (no deps)."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

RELEASES_API = "https://api.github.com/repos/tanumay-deb/TS-MP4-converter/releases/latest"
# Only ever download assets from our own release host, over HTTPS.
_TRUSTED_HOST_PREFIX = "https://github.com/tanumay-deb/TS-MP4-converter/"
_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass
class UpdateInfo:
    version: str        # normalized, e.g. "1.6.0"
    tag: str            # raw tag, e.g. "v1.6.0"
    url: str            # release page
    notes: str = ""
    setup_url: Optional[str] = None   # the *-setup.exe asset, if published
    setup_name: str = ""
    setup_size: int = 0


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

    setup_url = setup_name = None
    setup_size = 0
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.lower().endswith("setup.exe") and url.startswith(_TRUSTED_HOST_PREFIX):
            setup_url, setup_name = url, name
            setup_size = int(asset.get("size") or 0)
            break

    m = _VER_RE.search(tag)
    return UpdateInfo(
        version=m.group(0) if m else tag,
        tag=tag,
        url=str(data.get("html_url")
                or f"https://github.com/tanumay-deb/TS-MP4-converter/releases/tag/{tag}"),
        notes=str(data.get("body") or "")[:4000],
        setup_url=setup_url,
        setup_name=setup_name or "",
        setup_size=setup_size,
    )


def download(url: str, dest: str, on_progress: Optional[Callable[[int, int], None]] = None,
             timeout: float = 30.0) -> bool:
    """Download `url` to `dest`. Returns True on success. Never raises.

    Refuses any URL not on our own release host. Reports (read, total) bytes.
    """
    if not url.startswith(_TRUSTED_HOST_PREFIX):
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "TS-MP4-converter"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fp:
            total = int(resp.headers.get("Content-Length") or 0)
            read = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fp.write(chunk)
                read += len(chunk)
                if on_progress and total:
                    on_progress(read, total)
        return True
    except Exception:  # noqa: BLE001 - best-effort; clean up a partial file
        try:
            os.remove(dest)
        except OSError:
            pass
        return False
