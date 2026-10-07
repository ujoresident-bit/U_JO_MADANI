"""Per-user random question order (display only).

Every user gets their own shuffled order of the active questions. The order
is computed from (Telegram User ID, question id) with SHA-256, so:

* it is different for every user,
* it never changes for the same user (not between Next/Previous, not after
  a restart, not on another device), so Previous always goes back exactly,
* nothing is stored and the database is not changed: the original order,
  ids and order_number of the questions stay as they are.

"QUESTION 1, 2, 3..." is the position of the question in THIS user's order.
New questions added later simply take their place inside each user's order.
"""
from __future__ import annotations

import asyncio
import bisect
import hashlib
import logging
import time

from database import CARDS, Database, DatabaseError, Row

log = logging.getLogger(__name__)

CACHE_SECONDS = 60          # how often the list of active question ids is refreshed
PAGE_SIZE = 1000            # Supabase returns at most 1000 rows per request
MAX_SKIP = 5                # questions hidden in the last minute are skipped
_SALT = "ujo-question-order-v1"

_active_ids: list[int] = []
_loaded_at: float | None = None
_generation = 0
_lock = asyncio.Lock()
_user_orders: dict[int, tuple[int, list[tuple[int, int]]]] = {}


def sort_key(telegram_user_id: int, card_id: int) -> int:
    digest = hashlib.sha256(f"{_SALT}:{telegram_user_id}:{card_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


async def _load_active_ids(db: Database) -> list[int]:
    """Ids only (small), all pages, ordered by id."""
    ids: list[int] = []
    start = 0
    while True:
        res = await db._run(
            lambda s=start: db._client.table(CARDS)
            .select("id")
            .eq("is_active", "true")
            .order("id")
            .range(s, s + PAGE_SIZE - 1)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        ids.extend(int(r["id"]) for r in rows)
        if len(rows) < PAGE_SIZE:
            return ids
        start += PAGE_SIZE


async def _get_active_ids(db: Database) -> list[int]:
    global _active_ids, _loaded_at, _generation
    if _loaded_at is not None and time.monotonic() - _loaded_at < CACHE_SECONDS:
        return _active_ids
    async with _lock:
        if _loaded_at is not None and time.monotonic() - _loaded_at < CACHE_SECONDS:
            return _active_ids
        try:
            ids = await _load_active_ids(db)
        except DatabaseError:
            if _loaded_at is not None:
                return _active_ids  # keep working with the last known list
            raise
        if ids != _active_ids:
            _active_ids = ids
            _generation += 1
        _loaded_at = time.monotonic()
    return _active_ids


async def _order(db: Database, telegram_user_id: int) -> list[tuple[int, int]]:
    """This user's order as a sorted list of (key, card_id)."""
    ids = await _get_active_ids(db)
    cached = _user_orders.get(telegram_user_id)
    if cached is not None and cached[0] == _generation:
        return cached[1]
    order = sorted((sort_key(telegram_user_id, card_id), card_id) for card_id in ids)
    if len(_user_orders) > 2000:
        _user_orders.clear()
    _user_orders[telegram_user_id] = (_generation, order)
    return order


async def _fetch(db: Database, order: list[tuple[int, int]], index: int, step: int) -> Row | None:
    """The active card at `index`, moving by `step` past cards hidden in the meantime."""
    for _ in range(MAX_SKIP):
        if not 0 <= index < len(order):
            return None
        card = await db.get_card(order[index][1])
        if card is not None:
            return {**card, "display_number": index + 1}
        index += step
    return None


def _position(telegram_user_id: int, card_id: int) -> tuple[int, int]:
    return sort_key(telegram_user_id, card_id), int(card_id)


# --------------------------------------------------------------------- public
async def first_card(db: Database, telegram_user_id: int) -> Row | None:
    return await _fetch(db, await _order(db, telegram_user_id), 0, 1)


async def next_card(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    order = await _order(db, telegram_user_id)
    return await _fetch(db, order, bisect.bisect_right(order, _position(telegram_user_id, card_id)), 1)


async def previous_card(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    order = await _order(db, telegram_user_id)
    return await _fetch(db, order, bisect.bisect_left(order, _position(telegram_user_id, card_id)) - 1, -1)


async def card_at_or_after(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    """The card itself if still active, otherwise the next one in this user's order."""
    order = await _order(db, telegram_user_id)
    return await _fetch(db, order, bisect.bisect_left(order, _position(telegram_user_id, card_id)), 1)


async def with_number(db: Database, telegram_user_id: int, card: Row) -> Row:
    """Add this user's question number ("QUESTION n") to a card."""
    if card.get("display_number"):
        return card
    order = await _order(db, telegram_user_id)
    i = bisect.bisect_left(order, _position(telegram_user_id, card["id"]))
    if i < len(order) and order[i][1] == int(card["id"]):
        return {**card, "display_number": i + 1}
    return card
