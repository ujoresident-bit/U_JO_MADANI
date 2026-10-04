"""Small dependency-free helpers shared by the bot and the import scripts."""
from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[a-z0-9_]{4,32}$")


def normalize_username(raw: str | None) -> str | None:
    """'@User123' -> 'user123'. Returns None for empty input.

    Must stay identical to the SQL trigger `allowed_users_normalize`.
    """
    if raw is None:
        return None
    value = raw.strip().lstrip("@").strip().lower()
    return value or None


def is_valid_username(username: str | None) -> bool:
    return bool(username and _USERNAME_RE.match(username))
