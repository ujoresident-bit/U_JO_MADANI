"""Per-user random question order (display only).

Every user gets their own shuffled order of the active questions. The order
is computed from (Telegram User ID, question id) with SHA-256, so:

* it is different for every user,
* it never changes for the same user (not between Next/Previous, not after
  a restart, not on another device), so Previous always goes back exactly,
* nothing is stored and the database is not changed: the original order,
  ids and order_number of the questions stay as they are.

New questions always come LAST:
  The questions are grouped in "batches". The first questions of the bot
  (order_number 1..BASE_ORDER_NUMBER) are batch 0. Every question added
  later belongs to the batch of the minute it was uploaded (created_at).
  Each user sees batch 0 first (shuffled), then every newer batch after
  it, oldest upload first (each batch shuffled too). So a new upload:
    * goes to the END of every user's order (users reach it by pressing Next),
    * never changes the QUESTION number of the questions before it.

"QUESTION 1, 2, 3..." is the position of the question in THIS user's order.
"""
from __future__ import annotations

import asyncio
import bisect
import hashlib
import logging
import time

from database import Database, DatabaseError, Row

log = logging.getLogger(__name__)

CACHE_SECONDS = 60          # how often the list of active questions is refreshed
MAX_SKIP = 5                # questions hidden in the last minute are skipped
BASE_ORDER_NUMBER = 600     # questions 1..600 = the questions the bot launched with
_SALT = "ujo-question-order-v1"

_active: list[tuple[int, str]] = []      # (card_id, batch) of the active questions
_batch_of: dict[int, str] = {}           # card_id -> batch
_loaded_at: float | None = None
_generation = 0
_lock = asyncio.Lock()
_user_orders: dict[int, tuple[int, list[tuple[str, int, int]]]] = {}


def sort_key(telegram_user_id: int, card_id: int) -> int:
    digest = hashlib.sha256(f"{_SALT}:{telegram_user_id}:{card_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def batch_key(card: Row) -> str:
    """"" for the launch questions; the upload minute for questions added later.

    Text like "2026-10-12T15:04" sorts in time order, and "" sorts first.
    """
    try:
        order_number = int(card.get("order_number") or 0)
    except (TypeError, ValueError):
        order_number = 0
    if 0 < order_number <= BASE_ORDER_NUMBER:
        return ""
    created = str(card.get("created_at") or "")[:16]
    return created or "9999"  # unknown upload time -> at the very end


async def _get_active(db: Database) -> list[tuple[int, str]]:
    global _active, _batch_of, _loaded_at, _generation
    if _loaded_at is not None and time.monotonic() - _loaded_at < CACHE_SECONDS:
        return _active
    async with _lock:
        if _loaded_at is not None and time.monotonic() - _loaded_at < CACHE_SECONDS:
            return _active
        try:
            cards = await db.get_active_cards()
        except DatabaseError:
            if _loaded_at is not None:
                return _active  # keep working with the last known list
            raise
        active = [(int(c["id"]), batch_key(c)) for c in cards]
        if active != _active:
            _active = active
            _batch_of = dict(active)
            _generation += 1
        _loaded_at = time.monotonic()
    return _active


async def _order(db: Database, telegram_user_id: int) -> list[tuple[str, int, int]]:
    """This user's order as a sorted list of (batch, key, card_id)."""
    active = await _get_active(db)
    cached = _user_orders.get(telegram_user_id)
    if cached is not None and cached[0] == _generation:
        return cached[1]
    order = sorted((batch, sort_key(telegram_user_id, card_id), card_id) for card_id, batch in active)
    if len(_user_orders) > 2000:
        _user_orders.clear()
    _user_orders[telegram_user_id] = (_generation, order)
    return order


async def _fetch(db: Database, order: list[tuple[str, int, int]], index: int, step: int) -> Row | None:
    """The active card at `index`, moving by `step` past cards hidden in the meantime."""
    for _ in range(MAX_SKIP):
        if not 0 <= index < len(order):
            return None
        card = await db.get_card(order[index][2])
        if card is not None:
            return {**card, "display_number": index + 1}
        index += step
    return None


async def _position(db: Database, telegram_user_id: int, card_id: int) -> tuple[str, int, int]:
    """Where a card sits in this user's order (also works for a hidden card)."""
    card_id = int(card_id)
    batch = _batch_of.get(card_id)
    if batch is None:  # not active any more: look it up once
        card = await db.get_card(card_id, active_only=False)
        batch = batch_key(card) if card else ""
    return batch, sort_key(telegram_user_id, card_id), card_id


# --------------------------------------------------------------------- public
async def first_card(db: Database, telegram_user_id: int) -> Row | None:
    return await _fetch(db, await _order(db, telegram_user_id), 0, 1)


async def next_card(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    order = await _order(db, telegram_user_id)
    pos = await _position(db, telegram_user_id, card_id)
    return await _fetch(db, order, bisect.bisect_right(order, pos), 1)


async def previous_card(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    order = await _order(db, telegram_user_id)
    pos = await _position(db, telegram_user_id, card_id)
    return await _fetch(db, order, bisect.bisect_left(order, pos) - 1, -1)


async def card_at_or_after(db: Database, telegram_user_id: int, card_id: int) -> Row | None:
    """The card itself if still active, otherwise the next one in this user's order."""
    order = await _order(db, telegram_user_id)
    pos = await _position(db, telegram_user_id, card_id)
    return await _fetch(db, order, bisect.bisect_left(order, pos), 1)


async def with_number(db: Database, telegram_user_id: int, card: Row) -> Row:
    """Add this user's question number ("QUESTION n") to a card."""
    if card.get("display_number"):
        return card
    order = await _order(db, telegram_user_id)
    pos = await _position(db, telegram_user_id, card["id"])
    i = bisect.bisect_left(order, pos)
    if i < len(order) and order[i][2] == int(card["id"]):
        return {**card, "display_number": i + 1}
    return card
