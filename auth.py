"""Authorization.

Rules:
1. Telegram User ID is the permanent identity. If a row with this ID exists,
   its status alone decides access (username changes don't matter).
2. Otherwise, the (normalized) username is used ONCE to find an active row
   that has not been claimed yet; the Telegram ID is then saved on that row.
3. No username and no registered ID -> rejected.

`authorize()` is called before EVERY command and button press.

Speed: a successful check is remembered for AUTH_CACHE_SECONDS, so button
presses don't wait for the database every time. /start always re-checks.
A user you disable is therefore cut off within 30 seconds at most.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from telegram import User

from database import Database, DatabaseError, Row
from utils import normalize_username

log = logging.getLogger(__name__)

AUTH_CACHE_SECONDS = 30
_recently_allowed: dict[int, float] = {}  # telegram_user_id -> time of last successful check


def _remember(tid: int) -> None:
    if len(_recently_allowed) > 5000:
        _recently_allowed.clear()
    _recently_allowed[tid] = time.monotonic()


class AuthStatus(Enum):
    AUTHORIZED = "authorized"
    NOT_ALLOWED = "not_allowed"
    NO_USERNAME = "no_username"


@dataclass(frozen=True)
class AuthResult:
    status: AuthStatus
    user: Row | None = None

    @property
    def allowed(self) -> bool:
        return self.status is AuthStatus.AUTHORIZED


async def authorize(db: Database, tg_user: User, touch: bool = False) -> AuthResult:
    tid = tg_user.id

    # 0) Allowed a few seconds ago -> no database request needed.
    if not touch:
        checked_at = _recently_allowed.get(tid)
        if checked_at is not None and time.monotonic() - checked_at < AUTH_CACHE_SECONDS:
            return AuthResult(AuthStatus.AUTHORIZED)
    _recently_allowed.pop(tid, None)

    # 1) Known Telegram ID -> status decides.
    row = await db.get_user_by_telegram_id(tid)
    if row is not None:
        if row.get("status") == "active":
            if touch:
                try:
                    await db.touch_user(tid, tg_user.first_name, tg_user.last_name)
                except DatabaseError:
                    pass  # last_seen is non-critical
            log.info("User authorized: telegram_id=%s", tid)
            _remember(tid)
            return AuthResult(AuthStatus.AUTHORIZED, row)
        log.info("User rejected (status=%s): telegram_id=%s", row.get("status"), tid)
        return AuthResult(AuthStatus.NOT_ALLOWED)

    # 2) First contact -> match by username.
    username = normalize_username(tg_user.username)
    if not username:
        log.info("User rejected (no username, not registered): telegram_id=%s", tid)
        return AuthResult(AuthStatus.NO_USERNAME)

    try:
        row = await db.claim_user_by_username(username, tid, tg_user.first_name, tg_user.last_name)
    except DatabaseError:
        # e.g. a race where this ID got linked in parallel; re-check by ID once.
        row = await db.get_user_by_telegram_id(tid)
        if row is not None and row.get("status") == "active":
            _remember(tid)
            return AuthResult(AuthStatus.AUTHORIZED, row)
        raise

    if row is not None:
        log.info("User activated (first login): telegram_id=%s", tid)
        _remember(tid)
        return AuthResult(AuthStatus.AUTHORIZED, row)

    log.info("User rejected (not in allowed list): telegram_id=%s", tid)
    return AuthResult(AuthStatus.NOT_ALLOWED)
