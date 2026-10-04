"""Flashcard presentation (text + keyboards) and navigation helpers.

Callback data format (short, versionable, never contains card content):
    home            -> home screen
    fc:first        -> first flashcard
    fc:cont         -> continue from saved progress
    fc:next:<id>    -> card after card <id>
    fc:prev:<id>    -> card before card <id>
The card id only says which card is on screen; every press is re-authorized
and progress is always saved for the user who pressed (from Telegram, not
from the callback data), so nobody can touch another user's progress.
"""
from __future__ import annotations

import html
import logging
import re

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup

import texts
from database import Database, Row

log = logging.getLogger(__name__)

CB_HOME = "home"
CB_FIRST = "fc:first"
CB_CONTINUE = "fc:cont"
NEXT = "next"
PREV = "prev"

_NAV_RE = re.compile(r"^fc:(next|prev):(\d{1,18})$")

DIVIDER = "━━━━━━━━━━━━"
MAX_CONTENT_CHARS = 3900  # Telegram message limit is 4096 incl. header


def nav_data(direction: str, card_id: int) -> str:
    return f"fc:{direction}:{card_id}"


def parse_nav(data: str) -> tuple[str, int] | None:
    match = _NAV_RE.match(data or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def format_card_text(card: Row) -> str:
    content = (card.get("content") or "").strip()
    if len(content) > MAX_CONTENT_CHARS:
        log.warning("Flashcard id=%s is too long; truncated for display.", card.get("id"))
        content = content[: MAX_CONTENT_CHARS - 1].rstrip() + "…"
    number = int(card.get("order_number") or 0)
    return (
        f"{DIVIDER}\n\n"
        f"<b>FLASHCARD #{number:03d}</b>\n\n"
        f"{html.escape(content, quote=False)}\n\n"
        f"{DIVIDER}"
    )


def card_keyboard(card: Row) -> InlineKeyboardMarkup:
    card_id = card["id"]
    return InlineKeyboardMarkup(
        [
            [
                Button(texts.BTN_PREVIOUS, callback_data=nav_data(PREV, card_id)),
                Button(texts.BTN_NEXT, callback_data=nav_data(NEXT, card_id)),
            ],
            [Button(texts.BTN_HOME, callback_data=CB_HOME)],
        ]
    )


def render_card(card: Row) -> tuple[str, InlineKeyboardMarkup]:
    return format_card_text(card), card_keyboard(card)


def home_keyboard(continue_card: Row | None) -> InlineKeyboardMarkup:
    if continue_card is None:
        return InlineKeyboardMarkup([[Button(texts.BTN_START, callback_data=CB_FIRST)]])
    number = int(continue_card.get("order_number") or 0)
    return InlineKeyboardMarkup(
        [
            [Button(texts.BTN_CONTINUE.format(number=number), callback_data=CB_CONTINUE)],
            [Button(texts.BTN_FROM_BEGINNING, callback_data=CB_FIRST)],
        ]
    )


async def resolve_continue_card(db: Database, telegram_user_id: int) -> Row | None:
    """The card a user should continue from, or None if there is no progress.

    If the saved card was hidden (is_active = false), continue from the next
    active card after it instead of failing.
    """
    progress = await db.get_progress(telegram_user_id)
    card_id = progress.get("last_flashcard_id") if progress else None
    if not card_id:
        return None

    card = await db.get_card(card_id, active_only=False)
    if card is None:
        return None
    if card.get("is_active"):
        return card
    return await db.get_card_at_or_after(card["order_number"])
