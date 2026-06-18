"""Background catalog scanning with cancellation (Section 5).

Yazi's performance lesson: do heavy I/O off the UI thread and support
cancellation.  ``BackgroundScan`` runs a worker function in a daemon thread,
exposes a thread-safe result/done/error, and can be cancelled cooperatively —
the worker is handed a ``should_cancel()`` predicate it can poll.

Used to warm the track catalog at startup without blocking the first frame, and
reusable for any future long scan (folder import, metadata extraction).
"""
from __future__ import annotations

import threading
from typing import Any, Callable


class BackgroundScan:
    def __init__(self, worker: Callable[[Callable[[], bool]], Any]):
        """``worker(should_cancel)`` runs in a thread and returns a result.

        It should poll ``should_cancel()`` periodically and bail out early
        (returning whatever partial result makes sense) when it returns True.
        """
        self._worker = worker
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None

    def start(self) -> "BackgroundScan":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        try:
            result = self._worker(self.cancelled)
            with self._lock:
                self._result = result
        except BaseException as e:  # noqa: BLE001 — report, don't crash UI
            with self._lock:
                self._error = e
        finally:
            self._done.set()

    def cancel(self):
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def error(self) -> BaseException | None:
        with self._lock:
            return self._error

    @property
    def result(self) -> Any:
        with self._lock:
            return self._result

    def join(self, timeout: float | None = None):
        if self._thread is not None:
            self._thread.join(timeout)
        return self.result
