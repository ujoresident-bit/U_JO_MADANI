"""Supabase data access layer.

Every query lives here, so the rest of the bot never talks to Supabase
directly. The supabase-py client is synchronous, so each call runs in a
worker thread (asyncio.to_thread) to keep the bot responsive.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from supabase import Client, create_client

log = logging.getLogger(__name__)

USERS = "allowed_users"
CARDS = "flashcards"
PROGRESS = "user_progress"

CARD_COLUMNS = "id,content,category,year,order_number,is_active"
USER_COLUMNS = "id,username,telegram_user_id,status"

Row = dict[str, Any]


class DatabaseError(Exception):
    """Any failure talking to Supabase."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(response: Any) -> Row | None:
    data = getattr(response, "data", None) or []
    return data[0] if data else None


class Database:
    def __init__(self, url: str, key: str) -> None:
        self._client: Client = create_client(url, key)

    async def _run(self, fn: Callable[[], Any]) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:  # network, PostgREST, constraint errors...
            log.error("Database error: %s: %s", type(exc).__name__, exc)
            raise DatabaseError(str(exc)) from exc

    # ------------------------------------------------------------ health
    async def ping(self) -> None:
        await self._run(lambda: self._client.table(CARDS).select("id").limit(1).execute())

    # ------------------------------------------------------------ users
    async def get_user_by_telegram_id(self, telegram_user_id: int) -> Row | None:
        res = await self._run(
            lambda: self._client.table(USERS)
            .select(USER_COLUMNS)
            .eq("telegram_user_id", telegram_user_id)
            .limit(1)
            .execute()
        )
        return _first(res)

    async def claim_user_by_username(
        self,
        username: str,
        telegram_user_id: int,
        first_name: str | None,
        last_name: str | None,
    ) -> Row | None:
        """Bind a Telegram ID to an active, not-yet-claimed username row.

        The `telegram_user_id IS NULL` filter makes this atomic: a row that
        already belongs to another Telegram account can never be taken over.
        """
        now = _now()
        res = await self._run(
            lambda: self._client.table(USERS)
            .update(
                {
                    "telegram_user_id": telegram_user_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "activated_at": now,
                    "last_seen_at": now,
                }
            )
            .eq("username", username)
            .eq("status", "active")
            .is_("telegram_user_id", "null")
            .execute()
        )
        return _first(res)

    async def touch_user(
        self, telegram_user_id: int, first_name: str | None, last_name: str | None
    ) -> None:
        await self._run(
            lambda: self._client.table(USERS)
            .update({"first_name": first_name, "last_name": last_name, "last_seen_at": _now()})
            .eq("telegram_user_id", telegram_user_id)
            .execute()
        )

    # ------------------------------------------------------------ flashcards
    async def get_card(self, card_id: int, active_only: bool = True) -> Row | None:
        def query():
            q = self._client.table(CARDS).select(CARD_COLUMNS).eq("id", card_id)
            if active_only:
                q = q.eq("is_active", "true")
            return q.limit(1).execute()

        return _first(await self._run(query))

    async def _card_by_order(self, op: str, order_number: int | None, descending: bool) -> Row | None:
        def query():
            q = self._client.table(CARDS).select(CARD_COLUMNS).eq("is_active", "true")
            if op == "gt":
                q = q.gt("order_number", order_number)
            elif op == "lt":
                q = q.lt("order_number", order_number)
            elif op == "gte":
                q = q.gte("order_number", order_number)
            return q.order("order_number", desc=descending).limit(1).execute()

        return _first(await self._run(query))

    async def get_first_card(self) -> Row | None:
        return await self._card_by_order("first", None, descending=False)

    async def get_next_card(self, order_number: int) -> Row | None:
        return await self._card_by_order("gt", order_number, descending=False)

    async def get_previous_card(self, order_number: int) -> Row | None:
        return await self._card_by_order("lt", order_number, descending=True)

    async def get_card_at_or_after(self, order_number: int) -> Row | None:
        return await self._card_by_order("gte", order_number, descending=False)

    # ------------------------------------------------------------ progress
    async def get_progress(self, telegram_user_id: int) -> Row | None:
        res = await self._run(
            lambda: self._client.table(PROGRESS)
            .select("last_flashcard_id")
            .eq("telegram_user_id", telegram_user_id)
            .limit(1)
            .execute()
        )
        return _first(res)

    async def save_progress(self, telegram_user_id: int, flashcard_id: int) -> None:
        await self._run(
            lambda: self._client.table(PROGRESS)
            .upsert(
                {
                    "telegram_user_id": telegram_user_id,
                    "last_flashcard_id": flashcard_id,
                    "updated_at": _now(),
                },
                on_conflict="telegram_user_id",
            )
            .execute()
        )
