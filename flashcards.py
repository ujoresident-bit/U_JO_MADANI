"""Flashcard presentation (text + keyboards) and callback data.

Callback data (short, never contains card content or user IDs):
    home                     -> home screen
    fc:first                 -> first flashcard
    fc:cont                  -> continue from saved progress
    fc:next:<id>             -> card after card <id>      (answer hidden)
    fc:prev:<id>             -> card before card <id>     (answer hidden)
    fc:open:<id>:<r>         -> show card <id>; r=1 reveals the answer
    sv:on:<id>:<r>           -> save card          sv:off:<id>:<r> -> unsave
    sv:list:<page>           -> saved list page    sv:noop         -> page label
    nt:<act>:<id>:<r>        -> notes: add | edit | view | del | yes | cancel

<r> only remembers whether the answer is currently visible, so the screen
can be redrawn the same way. The card id only says which card is on screen;
every press is re-authorized, and saved cards / notes / progress always use
the Telegram ID of the person who pressed (never a value from callback data).
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
CB_SAVED_NOOP = "sv:noop"
NEXT = "next"
PREV = "prev"

_NAV_RE = re.compile(r"^fc:(next|prev):(\d{1,18})$")
_OPEN_RE = re.compile(r"^fc:open:(\d{1,18}):([01])$")

DIVIDER = "━━━━━━━━━━━━"
MAX_CONTENT_CHARS = 3800  # Telegram message limit is 4096 incl. header + answer


# --------------------------------------------------------------------- callback data
def nav_data(direction: str, card_id: int) -> str:
    return f"fc:{direction}:{card_id}"


def open_data(card_id: int, revealed: bool = False) -> str:
    return f"fc:open:{card_id}:{int(revealed)}"


def save_data(on: bool, card_id: int, revealed: bool) -> str:
    return f"sv:{'on' if on else 'off'}:{card_id}:{int(revealed)}"


def saved_list_data(page: int = 0) -> str:
    return f"sv:list:{page}"


def note_data(action: str, card_id: int, revealed: bool) -> str:
    return f"nt:{action}:{card_id}:{int(revealed)}"


def parse_nav(data: str) -> tuple[str, int] | None:
    match = _NAV_RE.match(data or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def parse_open(data: str) -> tuple[int, bool] | None:
    match = _OPEN_RE.match(data or "")
    if not match:
        return None
    return int(match.group(1)), match.group(2) == "1"


# --------------------------------------------------------------------- card
def has_answer(card: Row) -> bool:
    return bool((card.get("answer") or "").strip())


def card_number(card: Row) -> int:
    return int(card.get("order_number") or 0)


def excerpt(text: str | None, limit: int = 70) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def format_card_text(card: Row, revealed: bool = False, notice: str | None = None) -> str:
    content = (card.get("content") or "").strip()
    answer = (card.get("answer") or "").strip()
    if len(content) + len(answer) > MAX_CONTENT_CHARS:
        log.warning("Flashcard id=%s is too long; truncated for display.", card.get("id"))
        content = content[: max(MAX_CONTENT_CHARS - len(answer), 200) - 1].rstrip() + "…"

    parts: list[str] = []
    if notice:
        parts += [notice, ""]
    parts += [
        texts.CARD_TITLE.format(number=card_number(card)),
        DIVIDER,
        "",
        html.escape(content, quote=False),
    ]
    if answer:  # cards without an answer show their content only (as before)
        parts.append("")
        parts.append(
            texts.ANSWER_SHOWN.format(answer=html.escape(answer, quote=False))
            if revealed
            else texts.ANSWER_HIDDEN
        )
    return "\n".join(parts)


def card_keyboard(card: Row, revealed: bool = False, is_saved: bool = False, has_note: bool = False) -> InlineKeyboardMarkup:
    card_id = card["id"]
    revealed = revealed and has_answer(card)
    rows: list[list[Button]] = []

    if has_answer(card) and not revealed:
        rows.append([Button(texts.BTN_SHOW_ANSWER, callback_data=open_data(card_id, True))])

    rows.append([
        Button(texts.BTN_SAVED_ON if is_saved else texts.BTN_SAVE,
               callback_data=save_data(not is_saved, card_id, revealed)),
        Button(texts.BTN_VIEW_NOTE if has_note else texts.BTN_ADD_NOTE,
               callback_data=note_data("view" if has_note else "add", card_id, revealed)),
    ])
    rows.append([
        Button(texts.BTN_PREVIOUS, callback_data=nav_data(PREV, card_id)),
        Button(texts.BTN_NEXT, callback_data=nav_data(NEXT, card_id)),
    ])
    rows.append([
        Button(texts.BTN_SAVED_LIST, callback_data=saved_list_data(0)),
        Button(texts.BTN_HOME, callback_data=CB_HOME),
    ])
    return InlineKeyboardMarkup(rows)


def render_card(
    card: Row,
    revealed: bool = False,
    is_saved: bool = False,
    has_note: bool = False,
    notice: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    revealed = revealed and has_answer(card)
    return format_card_text(card, revealed, notice), card_keyboard(card, revealed, is_saved, has_note)


# --------------------------------------------------------------------- home
def home_keyboard(continue_card: Row | None) -> InlineKeyboardMarkup:
    if continue_card is None:
        rows = [[Button(texts.BTN_START, callback_data=CB_FIRST)]]
    else:
        rows = [
            [Button(texts.BTN_START, callback_data=CB_CONTINUE)],
            [Button(texts.BTN_FROM_BEGINNING, callback_data=CB_FIRST)],
        ]
    rows.append([Button(texts.BTN_SAVED_LIST, callback_data=saved_list_data(0))])
    return InlineKeyboardMarkup(rows)


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
