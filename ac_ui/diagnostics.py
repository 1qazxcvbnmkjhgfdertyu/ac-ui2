"""Structured diagnostics — replaces bare except/pass with observable failures.

Usage:
    from ac_ui.diagnostics import warn, error, get_recent

    try:
        ...
    except Exception as exc:
        warn("cava", f"read failed: {exc}", exc=exc)

The ring buffer holds the last MAX_ENTRIES entries and is safe to read from
any thread.  The UI can display recent errors in the debug overlay.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Level(str, Enum):
    INFO  = "info"
    WARN  = "warn"
    ERROR = "error"


@dataclass
class Diagnostic:
    level: Level
    source: str
    message: str
    ts: float = field(default_factory=time.monotonic)
    exc: BaseException | None = None

    def __str__(self) -> str:
        exc_suffix = f": {self.exc}" if self.exc else ""
        return f"[{self.level.value}] {self.source}: {self.message}{exc_suffix}"


MAX_ENTRIES = 200


class DiagnosticsCollector:
    """Thread-safe ring buffer of Diagnostic records."""

    def __init__(self, maxlen: int = MAX_ENTRIES) -> None:
        self._buf: deque[Diagnostic] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counts: dict[Level, int] = {lvl: 0 for lvl in Level}

    def record(self, level: Level, source: str, message: str, exc: BaseException | None = None) -> Diagnostic:
        d = Diagnostic(level=level, source=source, message=message, exc=exc)
        with self._lock:
            self._buf.append(d)
            self._counts[level] += 1
        return d

    def get_recent(self, n: int = 20, level: Level | None = None) -> list[Diagnostic]:
        with self._lock:
            entries = list(self._buf)
        if level is not None:
            entries = [e for e in entries if e.level == level]
        return entries[-n:]

    def count(self, level: Level) -> int:
        with self._lock:
            return self._counts[level]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._counts = {lvl: 0 for lvl in Level}

    @property
    def warn_count(self) -> int:
        return self.count(Level.WARN)

    @property
    def error_count(self) -> int:
        return self.count(Level.ERROR)


# Module-level singleton — import and use directly.
_collector = DiagnosticsCollector()


def info(source: str, message: str, exc: BaseException | None = None) -> Diagnostic:
    return _collector.record(Level.INFO, source, message, exc)


def warn(source: str, message: str, exc: BaseException | None = None) -> Diagnostic:
    return _collector.record(Level.WARN, source, message, exc)


def error(source: str, message: str, exc: BaseException | None = None) -> Diagnostic:
    return _collector.record(Level.ERROR, source, message, exc)


def get_recent(n: int = 20, level: Level | None = None) -> list[Diagnostic]:
    return _collector.get_recent(n=n, level=level)


def counts() -> dict[str, int]:
    return {lvl.value: _collector.count(lvl) for lvl in Level}


def clear() -> None:
    _collector.clear()
