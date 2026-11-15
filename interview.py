"""Expected interview questions: only for verified interview candidates.

Access needs BOTH:
  1. the normal bot access (allowed_users, checked by guard() on every update), and
  2. being on the interview candidates list (table interview_candidates).

Verification (once per Telegram account):
  /start -> choose a specialty (buttons) -> type first name + father's name
  -> the bot looks for that name among the candidates of THAT specialty
  -> the matching candidate row is linked to this Telegram ID (claimed_by)
  -> from then on the user only sees the questions of that specialty.

A candidate row can be linked to one Telegram account only, so nobody can use
a colleague's name after the colleague has verified. The admin can unlink a
row in the table (set claimed_by to empty) if a mistake happens.

Callback data:  iv:list  -> choose specialty     iv:d:<i> -> specialty #i chosen
"""
from __future__ import annotations

import html
import logging
import re
import time

from telegram import InlineKeyboardButton as Button
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import question_order
import texts
from common import INTERVIEW_STATE_KEY, clear_note_state, get_db, guard, show
from database import Database
from flashcards import home_keyboard

log = logging.getLogger(__name__)

# Specialties of the interview list (most candidates first). The text must be
# EXACTLY the same as interview_candidates.department and flashcards.department.
DEPARTMENTS: tuple[str, ...] = (
    "الباطنية",
    "الجراحة العامة",
    "النسائية والتوليد",
    "الأشعة التشخيصية",
    "جراحة العظام",
    "طب الأطفال",
    "طب وجراحة العيون",
    "طب الأسرة",
    "طب الطوارئ",
    "التخدير والعناية المركزة",
    "الأذنية",
    "الجلدية",
    "جراحة المسالك",
    "الطب النفسي",
)

_DEPT_RE = re.compile(r"^iv:d:(\d{1,2})$")
MAX_FAILS_PER_HOUR = 10
_fails: dict[int, list[float]] = {}


# --------------------------------------------------------------------- name matching
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_TITLES = {"د", "د.", "دكتور", "الدكتور", "دكتوره", "الدكتوره", "دكتورة", "الدكتورة", "dr", "dr."}


def name_key(text: str) -> str:
    """Spelling-tolerant key of an Arabic name.

    Ignores diacritics, spaces, all alef/hamza forms (ا أ إ آ ء), and treats
    ى=ي, ة=ه, ؤ=و, ئ=ي. So "عبد الله" = "عبدالله", "علاء" = "علا", "اسامة" = "أسامه".
    """
    text = _DIACRITICS.sub("", text or "")
    text = text.translate(str.maketrans({"ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}))
    text = re.sub(r"[اأإآء]", "", text)
    return re.sub(r"[^ء-ي]", "", text)


def clean_typed_name(text: str) -> list[str]:
    """The typed words without titles like د. / دكتور."""
    words = (text or "").replace("‏", " ").split()
    return [w for w in words if w.strip(".").lower() not in _TITLES and w.lower() not in _TITLES]


def name_matches(typed_key: str, candidate_key: str) -> bool:
    """The typed name is the start of the candidate's full name.

    The candidate list comes from a PDF where some neighbouring letters are
    swapped (e.g. "عبير" was read as "عبري", "الشرع" as "الرشع"), so two
    neighbouring letters in reverse order are accepted too.
    """
    n = len(typed_key)
    if n < 3 or len(candidate_key) < n:
        return False
    start = candidate_key[:n]
    if start == typed_key:
        return True
    i = 0
    while i < n:
        if start[i] == typed_key[i]:
            i += 1
        elif i + 1 < n and start[i] == typed_key[i + 1] and start[i + 1] == typed_key[i]:
            i += 2
        else:
            return False
    return True


def _too_many_fails(telegram_user_id: int) -> bool:
    now = time.monotonic()
    recent = [t for t in _fails.get(telegram_user_id, []) if now - t < 3600]
    _fails[telegram_user_id] = recent
    return len(recent) >= MAX_FAILS_PER_HOUR


def _record_fail(telegram_user_id: int) -> None:
    _fails.setdefault(telegram_user_id, []).append(time.monotonic())


# --------------------------------------------------------------------- views
def choose_view() -> tuple[str, InlineKeyboardMarkup]:
    buttons = [Button(d, callback_data=f"iv:d:{i}") for i, d in enumerate(DEPARTMENTS)]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return f"{texts.WELCOME}\n\n{texts.IV_CHOOSE}", InlineKeyboardMarkup(rows)


def _ask_name_view(dept: str, notice: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    text = texts.IV_ASK_NAME.format(dept=html.escape(dept))
    if notice:
        text = f"{notice}\n\n{text}"
    keyboard = InlineKeyboardMarkup([[Button(texts.BTN_IV_CHANGE, callback_data="iv:list")]])
    return text, keyboard


async def user_department(db: Database, telegram_user_id: int) -> str | None:
    return await db.get_user_department(telegram_user_id)


# --------------------------------------------------------------------- handlers
async def on_interview_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not await guard(update, context):  # guard also clears pending input
        return
    db, user = get_db(context), query.from_user

    if await db.get_user_department(user.id):  # already verified: nothing to choose
        await query.answer()
        from handlers import home_view  # local import (handlers imports this module)
        text, keyboard = await home_view(db, user.id)
        await show(update, context, text, keyboard)
        return

    data = query.data or ""
    if data == "iv:list":
        await query.answer()
        await show(update, context, *choose_view())
        return

    match = _DEPT_RE.match(data)
    if match is None or int(match.group(1)) >= len(DEPARTMENTS):
        await query.answer(texts.UNKNOWN_ACTION, show_alert=True)
        return
    dept = DEPARTMENTS[int(match.group(1))]
    context.user_data[INTERVIEW_STATE_KEY] = dept  # the next typed text is the name
    await query.answer()
    await show(update, context, *_ask_name_view(dept))


async def on_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The typed first name + father's name, while a specialty is chosen."""
    if not await guard(update, context, keep_note_state=True):
        return
    user, message, db = update.effective_user, update.effective_message, get_db(context)
    dept = (context.user_data or {}).get(INTERVIEW_STATE_KEY)
    if not dept:
        return

    if _too_many_fails(user.id):
        await message.reply_text(texts.IV_TOO_MANY)
        return

    words = clean_typed_name(message.text or "")
    typed_key = name_key("".join(words))
    if len(words) < 2 or len(typed_key) < 3:
        text, keyboard = _ask_name_view(dept, texts.IV_NAME_SHORT)
        await message.reply_text(text, reply_markup=keyboard)
        return

    candidates = await db.get_candidates(dept)
    matches = [c for c in candidates if name_matches(typed_key, c.get("name_key") or "")]
    mine = [c for c in matches if c.get("claimed_by") == user.id]
    free = [c for c in matches if c.get("claimed_by") is None]

    claimed = mine[0] if mine else None
    for cand in free:
        if claimed is not None:
            break
        if await db.claim_candidate(int(cand["id"]), user.id):
            claimed = cand

    if claimed is None:
        _record_fail(user.id)
        if matches:  # the name exists, but another account already verified with it
            log.info("Interview verify: name already claimed (telegram_id=%s dept=%s)", user.id, dept)
            notice = texts.IV_TAKEN
        else:
            log.info("Interview verify: no match (telegram_id=%s dept=%s)", user.id, dept)
            notice = texts.IV_NOT_FOUND.format(dept=html.escape(dept))
        text, keyboard = _ask_name_view(dept, notice)
        await message.reply_text(text, reply_markup=keyboard)
        return

    clear_note_state(context)
    question_order.forget_user(user.id)
    log.info("Interview verify: OK (telegram_id=%s dept=%s candidate=%s)", user.id, dept, claimed["id"])
    await message.reply_text(
        texts.IV_OK.format(dept=html.escape(dept)),
        reply_markup=home_keyboard(None),
    )


async def on_name_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None and await guard(update, context, keep_note_state=True):
        await update.effective_message.reply_text(texts.IV_TEXT_ONLY)
