"""JWT-based authentication and admin override."""

from __future__ import annotations


class AuthToken:
    """Parsed JWT claims (simplified for demo)."""

    def __init__(self, user_id: str, is_admin: bool = False) -> None:
        self.user_id = user_id
        self.is_admin = is_admin

    @classmethod
    def parse(cls, token: str) -> "AuthToken":
        """Parse a token string into claims (simplified — no real JWT)."""
        if token.startswith("admin:"):
            return cls(user_id=token[6:], is_admin=True)
        return cls(user_id=token)


def is_admin(token: AuthToken) -> bool:
    """Return True if the token has admin privileges."""
    return token.is_admin
