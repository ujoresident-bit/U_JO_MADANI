"""📝 ملاحظاتي: the list of questions THIS user wrote a note on.

Works like ⭐ المحفوظة: 8 per page, newest first, a number button opens the
question in the normal question screen (where the note can be viewed,
edited or deleted). Only the pressing user's own notes are ever listed.
"""
from __future__ import annotations

import html
import math
import re

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import texts
from common import get_db, guard, show
from flashcards import CB_HOME, excerpt, notes_list_data, open_data

PAGE_SIZE = 8
NUMBERS_PER_ROW = 4
CB_NOOP = "nl:noop"
_PAGE_RE = re.compile(r"^nl:(\d{1,4})$")


def _short(text: str | None, limit: int) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


async def _render(db, telegram_user_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.get_notes_page(telegram_user_id, PAGE_SIZE, page * PAGE_SIZE)
    if not rows and page > 0:  # page no longer exists (notes deleted) -> first page
        page = 0
        rows = await db.get_notes_page(telegram_user_id, PAGE_SIZE, 0)

    home_row = [Button(texts.BTN_HOME, callback_data=CB_HOME)]
    if not rows:
        return texts.NOTES_EMPTY, InlineKeyboardMarkup([home_row])

    total = int(rows[0]["total"])
    pages = max(1, math.ceil(total / PAGE_SIZE))
    first = page * PAGE_SIZE + 1

    lines = [texts.NOTES_TITLE.format(total=total), ""]
    buttons = []
    for i, row in enumerate(rows):
        number = first + i
        question = html.escape(excerpt(row.get("content"), 60), quote=False)   # question only, never the answer
        note = html.escape(_short(row.get("note_text"), 60), quote=False)
        lines.append(f"<b>{number}.</b> {question}\n      📝 <i>{note}</i>")
        buttons.append(Button(str(number), callback_data=open_data(row["flashcard_id"], False)))
    lines += ["", texts.NOTES_HINT]

    keyboard = [buttons[i : i + NUMBERS_PER_ROW] for i in range(0, len(buttons), NUMBERS_PER_ROW)]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Button("◀", callback_data=notes_list_data(page - 1)))
        nav.append(Button(f"{page + 1} / {pages}", callback_data=CB_NOOP))
        if page < pages - 1:
            nav.append(Button("▶", callback_data=notes_list_data(page + 1)))
        keyboard.append(nav)
    keyboard.append(home_row)
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def on_notes_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not await guard(update, context):
        return
    await query.answer()
    match = _PAGE_RE.match(query.data or "")
    if not match:  # nl:noop (page label) or anything unexpected
        return
    text, keyboard = await _render(get_db(context), query.from_user.id, int(match.group(1)))
    await show(update, context, text, keyboard)
