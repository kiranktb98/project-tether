"""Per-path event debouncer for the file watcher."""

from __future__ import annotations

import threading
import time
from typing import Callable


class Debouncer:
    """Debounce file-change events per path.

    For each file path, delays firing the callback until no further
    events for that path arrive within `delay_ms` milliseconds.
    """

    def __init__(self, delay_ms: int = 800) -> None:
        self._delay = delay_ms / 1000.0  # seconds
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def trigger(self, path: str, callback: Callable[[str], None]) -> None:
        """Schedule callback(path) after the debounce delay.

        If called again for the same path before the timer fires,
        the previous timer is cancelled and a new one starts.
        """
        with self._lock:
            existing = self._timers.get(path)
            if existing is not None:
                existing.cancel()

            timer = threading.Timer(self._delay, self._fire, args=[path, callback])
            self._timers[path] = timer
            timer.daemon = True
            timer.start()

    def _fire(self, path: str, callback: Callable[[str], None]) -> None:
        with self._lock:
            self._timers.pop(path, None)
        callback(path)

    def cancel_all(self) -> None:
        """Cancel all pending timers (call on shutdown)."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
