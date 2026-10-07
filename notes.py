"""Personal notes: one private note per user per flashcard.

Flow (the flashcard message itself turns into the prompt, so the chat stays clean):
    📝 Note          -> "اكتب ملاحظتك..." + [❌ إلغاء]; the user's next text is the note
    📝 عرض الملاحظة  -> note + [✏️ تعديل] [🗑 حذف] [↩️ العودة]
    🗑 حذف           -> confirmation -> delete -> back to the card

The pending input is stored in context.user_data, which python-telegram-bot
keeps separately for each Telegram user, together with the flashcard id and
the message to update. A message from one user can never complete another
user's note. Any other button or /start cancels a pending note.
"""
from __future__ import annotations

import html
import logging
import re

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import texts
from common import NOTE_STATE_KEY, clear_note_state, edit_or_send, get_db, guard, render_card_for_user, show, show_card
from flashcards import card_number, excerpt, note_data, open_data
from question_order import with_number

log = logging.getLogger(__name__)

NOTE_MAX_CHARS = 2000
_NOTE_RE = re.compile(r"^nt:(add|edit|view|del|yes|cancel):(\d{1,18}):([01])$")


def _card_line(card) -> str:
    return f"<i>QUESTION {card_number(card)} · {html.escape(excerpt(card.get('content'), 90), quote=False)}</i>"


def _prompt_view(card, revealed: bool, current_note: str | None = None, error: str | None = None):
    parts = []
    if error:
        parts += [error, ""]
    parts += [texts.NOTE_EDIT_PROMPT if current_note else texts.NOTE_PROMPT, "", _card_line(card)]
    if current_note:
        parts += ["", texts.NOTE_CURRENT, html.escape(current_note, quote=False)]
    keyboard = InlineKeyboardMarkup(
        [[Button(texts.BTN_CANCEL, callback_data=note_data("cancel", card["id"], revealed))]]
    )
    return "\n".join(parts), keyboard


def _note_view(card, revealed: bool, note: str):
    text = f"{texts.NOTE_VIEW_TITLE.format(number=card_number(card))}\n\n{html.escape(note, quote=False)}"
    keyboard = InlineKeyboardMarkup([
        [Button(texts.BTN_EDIT_NOTE, callback_data=note_data("edit", card["id"], revealed))],
        [Button(texts.BTN_DELETE_NOTE, callback_data=note_data("del", card["id"], revealed))],
        [Button(texts.BTN_BACK, callback_data=open_data(card["id"], revealed))],
    ])
    return text, keyboard


def _delete_confirm_view(card, revealed: bool):
    keyboard = InlineKeyboardMarkup([[
        Button(texts.BTN_CONFIRM_DELETE, callback_data=note_data("yes", card["id"], revealed)),
        Button(texts.BTN_CANCEL_PLAIN, callback_data=note_data("view", card["id"], revealed)),
    ]])
    return f"{texts.NOTE_DELETE_CONFIRM}\n\n{_card_line(card)}", keyboard


# --------------------------------------------------------------------- buttons
async def on_note_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not await guard(update, context):  # guard also cancels any pending note
        return
    user, db = query.from_user, get_db(context)

    match = _NOTE_RE.match(query.data or "")
    if not match:
        await query.answer(texts.UNKNOWN_ACTION, show_alert=True)
        return
    action, card_id, revealed = match.group(1), int(match.group(2)), match.group(3) == "1"

    card = await db.get_card(card_id)  # must exist and be active
    if card is None:
        await query.answer(texts.INVALID_CARD, show_alert=True)
        return
    card = await with_number(db, user.id, card)  # this user's QUESTION number

    if action in ("add", "edit"):
        current = await db.get_note(user.id, card_id) if action == "edit" else None
        context.user_data[NOTE_STATE_KEY] = {
            "card_id": card_id,
            "revealed": revealed,
            "chat_id": user.id,
            "message_id": query.message.message_id if query.message is not None else None,
        }
        await query.answer()
        text, keyboard = _prompt_view(card, revealed, current)
        await show(update, context, text, keyboard)
        return

    if action == "view":
        await query.answer()
        note = await db.get_note(user.id, card_id)
        if note is None:
            await show_card(update, context, card, revealed=revealed)
        else:
            text, keyboard = _note_view(card, revealed, note)
            await show(update, context, text, keyboard)
        return

    if action == "del":
        await query.answer()
        text, keyboard = _delete_confirm_view(card, revealed)
        await show(update, context, text, keyboard)
        return

    if action == "yes":
        await query.answer()
        await db.delete_note(user.id, card_id)
        log.info("Note deleted: telegram_id=%s card_id=%s", user.id, card_id)
        await show_card(update, context, card, revealed=revealed, notice=texts.NOTE_DELETED)
        return

    # cancel
    await query.answer()
    await show_card(update, context, card, revealed=revealed)


# --------------------------------------------------------------------- typed note
async def _delete_user_message(update: Update) -> None:
    try:
        await update.effective_message.delete()
    except (BadRequest, Forbidden):
        pass  # not critical: only keeps the chat clean


async def on_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A text message: saved as a note only if THIS user has a pending note input."""
    state = (context.user_data or {}).get(NOTE_STATE_KEY)
    if not state:
        return  # normal text outside note input is ignored (as before)
    if not await guard(update, context, keep_note_state=True):
        return

    user, db = update.effective_user, get_db(context)
    card_id, revealed = state["card_id"], state["revealed"]
    chat_id, message_id = state["chat_id"], state["message_id"]

    card = await db.get_card(card_id)
    if card is None:
        clear_note_state(context)
        await update.effective_message.reply_text(texts.INVALID_CARD)
        return
    card = await with_number(db, user.id, card)  # this user's QUESTION number

    note = (update.effective_message.text or "").strip()
    error = None
    if not note:
        error = texts.NOTE_EMPTY
    elif len(note) > NOTE_MAX_CHARS:
        error = texts.NOTE_TOO_LONG.format(max=NOTE_MAX_CHARS)
    if error:  # keep waiting for a valid note
        await _delete_user_message(update)
        current = await db.get_note(user.id, card_id)
        text, keyboard = _prompt_view(card, revealed, current, error)
        await edit_or_send(context, chat_id, message_id, text, keyboard)
        return

    await db.save_note(user.id, card_id, note)  # insert or update the same record
    clear_note_state(context)
    log.info("Note saved: telegram_id=%s card_id=%s", user.id, card_id)

    await _delete_user_message(update)
    text, keyboard = await render_card_for_user(db, user.id, card, revealed, notice=texts.NOTE_SAVED)
    await edit_or_send(context, chat_id, message_id, text, keyboard)


async def on_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo, sticker, voice... while a note is expected."""
    if (context.user_data or {}).get(NOTE_STATE_KEY) and update.effective_message is not None:
        if await guard(update, context, keep_note_state=True):
            await update.effective_message.reply_text(texts.NOTE_TEXT_ONLY)
