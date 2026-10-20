"""Telegram handlers: /start, /help, inline buttons, and the error handler.

Saved flashcards live in saved.py and personal notes in notes.py; shared
helpers (authorization guard, message editing) live in common.py.
"""
from __future__ import annotations

import html
import logging
import re

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup, Update
from telegram.error import Conflict, Forbidden, NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import texts
from auth import authorize
from common import SPECIALTY_STATE_KEY, clear_note_state, get_db, guard, rejection_text, show, show_card
from database import Database, DatabaseError
from flashcards import (
    CB_BLOCKS,
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
from my_notes import on_notes_list
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

    # Ask once, right after the welcome: "which specialty are you applying for?"
    try:
        answered = await db.has_specialty(user.id)
    except DatabaseError:
        answered = True  # never block the bot if this check fails
    if not answered:
        context.user_data[SPECIALTY_STATE_KEY] = True
        await message.reply_text(texts.WELCOME)
        await message.reply_text(texts.SPECIALTY_PROMPT)
        return

    text, keyboard = await _home_view(db, user.id)
    await message.reply_text(text, reply_markup=keyboard)


# --------------------------------------------------------------------- specialty
SPECIALTY_MIN_CHARS = 2
SPECIALTY_MAX_CHARS = 100


async def on_specialty_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The user's answer to "which specialty?" -> saved on their allowed_users row."""
    if not await guard(update, context, keep_note_state=True):
        return
    user, message, db = update.effective_user, update.effective_message, get_db(context)

    specialty = " ".join((message.text or "").split())  # tidy spaces / new lines
    if not SPECIALTY_MIN_CHARS <= len(specialty) <= SPECIALTY_MAX_CHARS:
        await message.reply_text(texts.SPECIALTY_INVALID)
        return  # keep waiting for a valid answer

    await db.save_specialty(user.id, specialty)
    clear_note_state(context)
    log.info("Specialty saved: telegram_id=%s", user.id)

    _, keyboard = await _home_view(db, user.id)
    await message.reply_text(
        texts.SPECIALTY_SAVED.format(specialty=html.escape(specialty, quote=False)),
        reply_markup=keyboard,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Typed text: the specialty answer if it is pending, otherwise a note."""
    if (context.user_data or {}).get(SPECIALTY_STATE_KEY):
        await on_specialty_text(update, context)
    else:
        await on_note_text(update, context)


async def on_other_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo, sticker, voice...: ask for text if the specialty answer is pending."""
    if (context.user_data or {}).get(SPECIALTY_STATE_KEY) and update.effective_message is not None:
        if await guard(update, context, keep_note_state=True):
            await update.effective_message.reply_text(texts.SPECIALTY_TEXT_ONLY)
        return
    await on_non_text(update, context)


# --------------------------------------------------------------------- blocks (jump)
BLOCK_SIZE = 100   # one block = 100 questions
GROUP_SIZE = 10    # inside a block: groups of 10
_BLOCK_RE = re.compile(r"^bk:(\d{1,6})$")
_GO_RE = re.compile(r"^go:(\d{1,6})$")


def _range_label(start: int, end: int) -> str:
    return f"{start} – {end}"


async def _current_number(db: Database, telegram_user_id: int) -> int | None:
    """The QUESTION number this user is at (from saved progress), if any."""
    try:
        card = await resolve_continue_card(db, telegram_user_id)
    except DatabaseError:
        return None
    return int(card["display_number"]) if card and card.get("display_number") else None


async def _blocks_view(db: Database, telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    total = await question_order.total_count(db, telegram_user_id)
    here = await _current_number(db, telegram_user_id)
    buttons = []
    for start in range(1, total + 1, BLOCK_SIZE):
        end = min(start + BLOCK_SIZE - 1, total)
        mark = "📍 " if here is not None and start <= here <= end else ""
        buttons.append(Button(mark + _range_label(start, end), callback_data=f"bk:{start}"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([Button(texts.BTN_HOME, callback_data=CB_HOME)])
    text = texts.BLOCKS_TITLE.format(total=total)
    if here is not None:
        text += "\n\n" + texts.BLOCKS_HERE.format(number=here)
    return text, InlineKeyboardMarkup(rows)


async def _block_view(db: Database, telegram_user_id: int, start: int) -> tuple[str, InlineKeyboardMarkup] | None:
    total = await question_order.total_count(db, telegram_user_id)
    if start < 1 or start > total or (start - 1) % BLOCK_SIZE:
        return None
    end = min(start + BLOCK_SIZE - 1, total)
    here = await _current_number(db, telegram_user_id)
    buttons = []
    for g in range(start, end + 1, GROUP_SIZE):
        g_end = min(g + GROUP_SIZE - 1, end)
        mark = "📍 " if here is not None and g <= here <= g_end else ""
        buttons.append(Button(mark + _range_label(g, g_end), callback_data=f"go:{g}"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([
        Button(texts.BTN_BLOCKS, callback_data=CB_BLOCKS),
        Button(texts.BTN_HOME, callback_data=CB_HOME),
    ])
    text = texts.BLOCK_TITLE.format(start=start, end=end)
    if here is not None and start <= here <= end:
        text += "\n\n" + texts.BLOCKS_HERE.format(number=here)
    return text, InlineKeyboardMarkup(rows)


async def on_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """bk -> blocks of 100, bk:<start> -> groups of 10, go:<n> -> open QUESTION n."""
    query = update.callback_query
    if query is None or not await guard(update, context):
        return
    user, data, db = query.from_user, query.data or "", get_db(context)

    if data == CB_BLOCKS:
        await query.answer()
        text, keyboard = await _blocks_view(db, user.id)
        await show(update, context, text, keyboard)
        return

    if (match := _BLOCK_RE.match(data)) is not None:
        view = await _block_view(db, user.id, int(match.group(1)))
        if view is None:
            await query.answer(texts.UNKNOWN_ACTION, show_alert=True)
            return
        await query.answer()
        await show(update, context, *view)
        return

    if (match := _GO_RE.match(data)) is not None:
        card = await question_order.card_at_number(db, user.id, int(match.group(1)))
        if card is None:
            await query.answer(texts.INVALID_CARD, show_alert=True)
            return
        await query.answer()
        await show_card(update, context, card)
        log.info("Jumped to question: telegram_id=%s card_id=%s", user.id, card["id"])
        context.application.create_task(_save_progress(db, user.id, card["id"]), update=update)
        return

    await query.answer(texts.UNKNOWN_ACTION, show_alert=True)


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
        await query.answer()
        text, keyboard = await _home_view(db, user.id)
        await show(update, context, text, keyboard)
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

    await query.answer()  # stop the button's loading spinner right away
    await show_card(update, context, card, revealed=revealed)
    log.info("Flashcard sent: telegram_id=%s card_id=%s revealed=%s", user.id, card["id"], revealed)

    # Progress is always saved for the user who pressed the button,
    # in the background so the user never waits for it.
    context.application.create_task(_save_progress(db, user.id, card["id"]), update=update)


async def _save_progress(db: Database, telegram_user_id: int, card_id: int) -> None:
    try:
        await db.save_progress(telegram_user_id, card_id)
    except DatabaseError:
        log.warning("Progress not saved for telegram_id=%s", telegram_user_id)


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
    app.add_handler(CallbackQueryHandler(on_notes_list, pattern=r"^nl:"))
    app.add_handler(CallbackQueryHandler(on_blocks, pattern=r"^(bk|bk:\d+|go:\d+)$"))
    app.add_handler(CallbackQueryHandler(on_unknown_callback))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(private & ~filters.TEXT & ~filters.COMMAND, on_other_message))
    app.add_error_handler(on_error)
