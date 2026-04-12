"""Quick smoke-test / demo script for the ratelimiter sample project.

Run this after tether bootstrap to verify the three features work.
"""

from src.auth import AuthToken, is_admin
from src.ratelimiter import RateLimiter
from src.middleware import handle_request


def main() -> None:
    print("=== ratelimiter demo ===\n")

    # Auth
    user_tok = AuthToken.parse("alice")
    admin_tok = AuthToken.parse("admin:bob")
    print(f"alice is_admin: {is_admin(user_tok)}")   # False
    print(f"bob   is_admin: {is_admin(admin_tok)}")  # True

    # Rate limiter — burst alice past the limit
    limiter = RateLimiter(limit=3, window_seconds=60)
    for i in range(5):
        allowed = limiter.is_allowed("alice")
        print(f"request {i + 1}: allowed={allowed}, remaining={limiter.remaining('alice')}")

    # Middleware — admin bypasses rate limit
    def handler() -> str:
        return "hello"

    resp = handle_request(admin_tok, handler)
    print(f"\nadmin request: {resp}")

    resp = handle_request(user_tok, handler)
    print(f"user  request: {resp}")


if __name__ == "__main__":
    main()
