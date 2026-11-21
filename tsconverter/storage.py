"""Small file helpers: crash-safe JSON writes and pruning of app-owned caches."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def write_json(path, data) -> None:
    """Write to a temp file, flush it to disk, then swap it in (atomic on one volume).

    A crash mid-write leaves the old file intact instead of a cut-off one. Raises
    OSError like open() does; callers decide whether that matters.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


def prune_old_files(*dirs, days: int = 30) -> None:
    """Delete files older than `days` directly inside each app-owned folder
    (logs, thumbnail cache), which would otherwise grow forever. Best-effort."""
    cutoff = time.time() - days * 86400
    for d in dirs:
        try:
            files = list(Path(d).iterdir())
        except OSError:
            continue
        for f in files:
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
