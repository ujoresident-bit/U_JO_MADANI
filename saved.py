"""Saved flashcards: ⭐ حفظ / ⭐ محفوظة toggle and the ⭐ المحفوظة list.

Always scoped to the Telegram user who pressed the button.
"""
from __future__ import annotations

import html
import logging
import math
import re

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import texts
from common import get_db, guard, show, show_card
from flashcards import CB_HOME, CB_SAVED_NOOP, excerpt, open_data, saved_list_data

log = logging.getLogger(__name__)

PAGE_SIZE = 8
NUMBERS_PER_ROW = 4

_TOGGLE_RE = re.compile(r"^sv:(on|off):(\d{1,18}):([01])$")
_LIST_RE = re.compile(r"^sv:list:(\d{1,4})$")


async def _render_list(db, telegram_user_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.get_saved_page(telegram_user_id, PAGE_SIZE, page * PAGE_SIZE)
    if not rows and page > 0:  # page no longer exists (cards removed) -> first page
        page = 0
        rows = await db.get_saved_page(telegram_user_id, PAGE_SIZE, 0)

    home_row = [Button(texts.BTN_HOME, callback_data=CB_HOME)]
    if not rows:
        return texts.SAVED_EMPTY, InlineKeyboardMarkup([home_row])

    total = int(rows[0]["total"])
    pages = max(1, math.ceil(total / PAGE_SIZE))
    first = page * PAGE_SIZE + 1

    lines = [texts.SAVED_TITLE.format(total=total), ""]
    buttons = []
    for i, row in enumerate(rows):
        number = first + i
        lines.append(f"<b>{number}.</b> {html.escape(excerpt(row.get('content')), quote=False)}")
        buttons.append(Button(str(number), callback_data=open_data(row["flashcard_id"], False)))
    lines += ["", texts.SAVED_HINT]

    keyboard = [buttons[i : i + NUMBERS_PER_ROW] for i in range(0, len(buttons), NUMBERS_PER_ROW)]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Button("◀", callback_data=saved_list_data(page - 1)))
        nav.append(Button(f"{page + 1} / {pages}", callback_data=CB_SAVED_NOOP))
        if page < pages - 1:
            nav.append(Button("▶", callback_data=saved_list_data(page + 1)))
        keyboard.append(nav)
    keyboard.append(home_row)
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def on_saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not await guard(update, context):
        return
    user, data, db = query.from_user, query.data or "", get_db(context)

    if data == CB_SAVED_NOOP:
        await query.answer()
        return

    match = _LIST_RE.match(data)
    if match:
        text, keyboard = await _render_list(db, user.id, int(match.group(1)))
        await show(update, context, text, keyboard)
        await query.answer()
        return

    match = _TOGGLE_RE.match(data)
    if not match:
        await query.answer(texts.UNKNOWN_ACTION, show_alert=True)
        return
    turn_on, card_id, revealed = match.group(1) == "on", int(match.group(2)), match.group(3) == "1"

    card = await db.get_card(card_id)  # must exist and be active
    if turn_on:
        if card is None:
            await query.answer(texts.INVALID_CARD, show_alert=True)
            return
        await db.add_saved(user.id, card_id)  # no duplicates (unique + ignore)
        log.info("Flashcard saved: telegram_id=%s card_id=%s", user.id, card_id)
    else:
        await db.remove_saved(user.id, card_id)
        log.info("Flashcard unsaved: telegram_id=%s card_id=%s", user.id, card_id)
        if card is None:
            await query.answer(texts.SAVED_REMOVED)
            return

    await show_card(update, context, card, revealed=revealed)
    await query.answer(texts.SAVED_ADDED if turn_on else texts.SAVED_REMOVED)
