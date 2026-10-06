"""Helpers shared by handlers.py, saved.py and notes.py."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import texts
from auth import AuthStatus, authorize
from database import Database, Row
from flashcards import render_card

log = logging.getLogger(__name__)

# Per-user note input state, kept in context.user_data (PTB keeps a separate
# dict for every Telegram user, so two users can never share this state).
NOTE_STATE_KEY = "note_input"


def get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def rejection_text(status: AuthStatus) -> str:
    return texts.NO_USERNAME if status is AuthStatus.NO_USERNAME else texts.NOT_AUTHORIZED


def clear_note_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data is not None:
        context.user_data.pop(NOTE_STATE_KEY, None)


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE, keep_note_state: bool = False) -> bool:
    """Private chats only + authorization on EVERY update. Returns True if allowed.

    Any action other than typing a note cancels a pending note input.
    """
    user, query = update.effective_user, update.callback_query
    if user is None:
        return False

    chat = update.effective_chat
    if chat is not None and chat.type != ChatType.PRIVATE:
        if query is not None:
            await query.answer()
        return False

    auth = await authorize(get_db(context), user)
    if not auth.allowed:
        clear_note_state(context)
        if query is not None:
            await query.answer(rejection_text(auth.status), show_alert=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(rejection_text(auth.status))
        return False

    if not keep_note_state:
        clear_note_state(context)
    return True


async def edit_or_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int | None,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Edit the existing message (one message that changes); send a new one
    only if it can't be edited (too old, deleted...)."""
    if message_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
            )
            return
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return  # double tap on the same button
            log.warning("Could not edit message (%s); sending a new one.", exc)
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup) -> None:
    """Edit the message whose button was pressed.

    Protection can only be set when a message is SENT, not when it is edited.
    So a message sent before protection was turned on is deleted and replaced
    by a new, protected one.
    """
    query = update.callback_query
    message = query.message if query is not None else None
    message_id = message.message_id if message is not None else None
    if message is not None and not getattr(message, "has_protected_content", False):
        try:
            await message.delete()
        except Exception:  # too old to delete: just send the new protected message
            pass
        message_id = None
    await edit_or_send(context, update.effective_user.id, message_id, text, keyboard)


async def render_card_for_user(
    db: Database, telegram_user_id: int, card: Row, revealed: bool = False, notice: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Card text + keyboard with THIS user's saved / note state."""
    is_saved, has_note = await db.get_card_user_state(telegram_user_id, card["id"])
    return render_card(
        card,
        revealed=revealed,
        is_saved=is_saved,
        has_note=has_note,
        notice=notice,
        watermark=texts.WATERMARK.format(tid=telegram_user_id),
    )


async def show_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    card: Row,
    revealed: bool = False,
    notice: str | None = None,
) -> None:
    text, keyboard = await render_card_for_user(get_db(context), update.effective_user.id, card, revealed, notice)
    await show(update, context, text, keyboard)
