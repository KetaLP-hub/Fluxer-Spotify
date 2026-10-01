"""Exceptions. Messages are bilingual (de/en) because they go straight to the user."""


def bi(de: str, en: str) -> str:
    return f"{de}\n{en}"


class Fatal(Exception):
    """Retrying cannot fix this; the user has to act."""


class AuthError(Fatal):
    """A service rejected our credentials (401 / invalid_grant)."""


class LoginError(Fatal):
    """Interactive login failed."""
