"""Persistent conversion history — a newest-first JSON store in the config dir.

Thread-safe: workers append from pool threads while the UI reads on the main
thread. Schema-tolerant on load so an old/partial file never crashes the app.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

MAX_ENTRIES = 500


@dataclass
class HistoryEntry:
    timestamp: str = ""          # local time, "YYYY-MM-DD HH:MM:SS"
    src: str = ""
    out: str = ""
    result: str = ""             # "Done" | "Failed" | "Cancelled"
    encoder: Optional[str] = None
    duration: float = 0.0
    size: int = 0                # output size in bytes
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def add(self, entry: HistoryEntry) -> None:
        with self._lock:
            entries = self._load()
            entries.insert(0, asdict(entry))     # newest first
            del entries[MAX_ENTRIES:]
            self._save(entries)

    def all(self) -> List[HistoryEntry]:
        with self._lock:
            return [HistoryEntry.from_dict(e) for e in self._load() if isinstance(e, dict)]

    def clear(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError:
                pass

    def _load(self) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return []
        return data.get("entries", []) if isinstance(data, dict) else []

    def _save(self, entries: list) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fp:
                json.dump({"version": 1, "entries": entries}, fp, indent=2)
        except OSError:
            pass
