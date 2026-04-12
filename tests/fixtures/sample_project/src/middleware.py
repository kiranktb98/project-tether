"""Request middleware — applies rate limiting to incoming requests."""

from __future__ import annotations

from typing import Any, Callable

from .auth import AuthToken, is_admin
from .ratelimiter import RateLimiter

_limiter = RateLimiter()


def handle_request(
    token: AuthToken,
    handler: Callable[[], Any],
) -> dict:
    """Apply rate limiting then call the handler.

    Admins bypass rate limits entirely.
    """
    if is_admin(token):
        return {"status": 200, "body": handler(), "rate_limited": False}

    if not _limiter.is_allowed(token.user_id):
        return {
            "status": 429,
            "body": "Too Many Requests",
            "rate_limited": True,
            "retry_after": 60,
        }

    return {"status": 200, "body": handler(), "rate_limited": False}
