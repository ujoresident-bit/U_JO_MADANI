"""Telegram handlers: /start, /help, inline buttons, and the error handler."""
from __future__ import annotations

import logging

from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Conflict, Forbidden, NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, filters

import texts
from auth import AuthStatus, authorize
from database import Database, DatabaseError
from flashcards import (
    CB_CONTINUE,
    CB_FIRST,
    CB_HOME,
    NEXT,
    home_keyboard,
    parse_nav,
    render_card,
    resolve_continue_card,
)

log = logging.getLogger(__name__)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _rejection_text(status: AuthStatus) -> str:
    return texts.NO_USERNAME if status is AuthStatus.NO_USERNAME else texts.NOT_AUTHORIZED


async def _home_view(db: Database, telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    continue_card = await resolve_continue_card(db, telegram_user_id)
    return texts.WELCOME, home_keyboard(continue_card)


async def _show(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Edit the existing message (one flashcard message that changes).

    Falls back to sending a new message if the old one can't be edited
    (too old, deleted, ...).
    """
    if query.message is not None:
        try:
            await query.edit_message_text(text, reply_markup=keyboard)
            return
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return  # double tap on the same button
            log.warning("Could not edit message (%s); sending a new one.", exc)
    await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=keyboard)


# --------------------------------------------------------------------- commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, message = update.effective_user, update.effective_message
    if user is None or message is None:
        return
    db = _db(context)

    auth = await authorize(db, user, touch=True)
    if not auth.allowed:
        await message.reply_text(_rejection_text(auth.status))
        return

    text, keyboard = await _home_view(db, user.id)
    await message.reply_text(text, reply_markup=keyboard)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, message = update.effective_user, update.effective_message
    if user is None or message is None:
        return

    auth = await authorize(_db(context), user)
    if not auth.allowed:
        await message.reply_text(_rejection_text(auth.status))
        return
    await message.reply_text(texts.HELP)


# --------------------------------------------------------------------- buttons
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    user = query.from_user
    data = query.data or ""
    db = _db(context)

    # Only private chats: the person pressing is the owner of the chat.
    if query.message is not None and query.message.chat.type != ChatType.PRIVATE:
        await query.answer()
        return

    # Re-authorize on EVERY press (disabled users are cut off immediately).
    auth = await authorize(db, user)
    if not auth.allowed:
        await query.answer(_rejection_text(auth.status), show_alert=True)
        return

    # Home
    if data == CB_HOME:
        text, keyboard = await _home_view(db, user.id)
        await _show(query, context, text, keyboard)
        await query.answer()
        return

    # Resolve which card to show
    log.info("Flashcard requested: telegram_id=%s action=%s", user.id, data)
    if data == CB_FIRST:
        card = await db.get_first_card()
    elif data == CB_CONTINUE:
        card = await resolve_continue_card(db, user.id) or await db.get_first_card()
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

        if direction == NEXT:
            card = await db.get_next_card(current["order_number"])
            if card is None:
                await query.answer(texts.LAST_CARD)
                return
        else:
            card = await db.get_previous_card(current["order_number"])
            if card is None:
                await query.answer(texts.FIRST_CARD)
                return

    if card is None:
        await query.answer(texts.NO_FLASHCARDS, show_alert=True)
        return

    text, keyboard = render_card(card)
    await _show(query, context, text, keyboard)
    await query.answer()
    log.info("Flashcard sent: telegram_id=%s card_id=%s", user.id, card["id"])

    # Progress is always saved for the user who pressed the button.
    try:
        await db.save_progress(user.id, card["id"])
    except DatabaseError:
        log.warning("Progress not saved for telegram_id=%s", user.id)


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
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
