"""Telegram handlers: /start, /help, inline buttons, and the error handler.

Saved flashcards live in saved.py and personal notes in notes.py; shared
helpers (authorization guard, message editing) live in common.py.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import Conflict, Forbidden, NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import texts
from auth import authorize
from common import clear_note_state, get_db, guard, rejection_text, show, show_card
from database import Database, DatabaseError
from flashcards import (
    CB_CONTINUE,
    CB_FIRST,
    CB_HOME,
    NEXT,
    home_keyboard,
    parse_nav,
    parse_open,
    resolve_continue_card,
)
import question_order
from notes import on_non_text, on_note_button, on_note_text
from saved import on_saved

log = logging.getLogger(__name__)


async def _home_view(db: Database, telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    continue_card = await resolve_continue_card(db, telegram_user_id)
    return texts.WELCOME, home_keyboard(continue_card)


# --------------------------------------------------------------------- commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, message = update.effective_user, update.effective_message
    if user is None or message is None:
        return
    db = get_db(context)
    clear_note_state(context)

    auth = await authorize(db, user, touch=True)
    if not auth.allowed:
        await message.reply_text(rejection_text(auth.status))
        return

    text, keyboard = await _home_view(db, user.id)
    await message.reply_text(text, reply_markup=keyboard)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not await guard(update, context):
        return
    await message.reply_text(texts.HELP)


# --------------------------------------------------------------------- buttons
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """home, fc:first, fc:cont, fc:next, fc:prev, fc:open."""
    query = update.callback_query
    if query is None:
        return
    # Private chats only + re-authorize on EVERY press (disabled users are cut off immediately).
    if not await guard(update, context):
        return
    user = query.from_user
    data = query.data or ""
    db = get_db(context)

    # Home
    if data == CB_HOME:
        text, keyboard = await _home_view(db, user.id)
        await show(update, context, text, keyboard)
        await query.answer()
        return

    # Resolve which card to show
    log.info("Flashcard requested: telegram_id=%s action=%s", user.id, data)
    revealed = False  # every newly opened card starts with the answer hidden
    if data == CB_FIRST:
        card = await question_order.first_card(db, user.id)
    elif data == CB_CONTINUE:
        card = await resolve_continue_card(db, user.id) or await question_order.first_card(db, user.id)
    elif (opened := parse_open(data)) is not None:
        # Same card: show/hide answer, back from a note, or open from the saved list
        card_id, revealed = opened
        card = await db.get_card(card_id)  # must exist and be active
        if card is None:
            await query.answer(texts.INVALID_CARD, show_alert=True)
            return
    else:
        nav = parse_nav(data)
        if nav is None:
            await query.answer(texts.UNKNOWN_ACTION, show_alert=True)
            return
        direction, current_id = nav

        current = await db.get_card(current_id, active_only=False)
        if current is None:
            await query.answer(texts.INVALID_CARD, show_alert=True)
            return

        # Next / Previous follow THIS user's random order
        if direction == NEXT:
            card = await question_order.next_card(db, user.id, current_id)
            if card is None:
                await query.answer(texts.LAST_CARD)
                return
        else:
            card = await question_order.previous_card(db, user.id, current_id)
            if card is None:
                await query.answer(texts.FIRST_CARD)
                return

    if card is None:
        await query.answer(texts.NO_FLASHCARDS, show_alert=True)
        return

    await show_card(update, context, card, revealed=revealed)
    await query.answer()
    log.info("Flashcard sent: telegram_id=%s card_id=%s revealed=%s", user.id, card["id"], revealed)

    # Progress is always saved for the user who pressed the button.
    try:
        await db.save_progress(user.id, card["id"])
    except DatabaseError:
        log.warning("Progress not saved for telegram_id=%s", user.id)


async def on_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None and await guard(update, context):
        await query.answer(texts.UNKNOWN_ACTION, show_alert=True)


# --------------------------------------------------------------------- errors
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """One user's error never stops the bot: log it and tell that user."""
    err = context.error

    if isinstance(err, Conflict):
        log.warning("Telegram conflict: another instance is polling with this token.")
        return
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning("Telegram connection error (will retry): %s", err)
        return
    if isinstance(err, Forbidden):
        log.info("User blocked the bot: %s", err)
        return

    if isinstance(err, DatabaseError):
        log.error("Database error while handling an update.")
    else:
        log.error("Unhandled error while handling an update.", exc_info=err)

    if not isinstance(update, Update):
        return
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(texts.GENERIC_ERROR, show_alert=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(texts.GENERIC_ERROR)
    except Exception:  # the query may already be answered / expired
        pass


def register_handlers(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler("help", cmd_help, filters=private))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(home|fc:.+)$"))
    app.add_handler(CallbackQueryHandler(on_saved, pattern=r"^sv:"))
    app.add_handler(CallbackQueryHandler(on_note_button, pattern=r"^nt:"))
    app.add_handler(CallbackQueryHandler(on_unknown_callback))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_note_text))
    app.add_handler(MessageHandler(private & ~filters.TEXT & ~filters.COMMAND, on_non_text))
    app.add_error_handler(on_error)
