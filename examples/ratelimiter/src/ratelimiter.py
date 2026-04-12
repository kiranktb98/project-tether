"""Per-user rate limiting using a sliding window."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any


class RateLimiter:
    """Sliding window rate limiter.

    Default: 100 requests per 60 seconds per user.
    """

    def __init__(self, limit: int = 100, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, user_id: str) -> bool:
        """Return True if the user is within their rate limit."""
        now = time.time()
        window = self._windows[user_id]

        # Drop events outside the sliding window
        cutoff = now - self.window
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= self.limit:
            return False

        window.append(now)
        return True

    def remaining(self, user_id: str) -> int:
        """Return how many requests the user has left in the current window."""
        now = time.time()
        window = self._windows[user_id]
        cutoff = now - self.window
        while window and window[0] < cutoff:
            window.popleft()
        return max(0, self.limit - len(window))

    def reset(self, user_id: str) -> None:
        """Clear the rate limit state for a user (admin operation)."""
        self._windows.pop(user_id, None)
