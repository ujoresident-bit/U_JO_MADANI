"""All user-facing texts in one place, so wording can be changed easily.

Messages are sent with HTML parse mode: use <b>, <i> only, and escape & < >.
"""

WELCOME = "👋 <b>Welcome to U JO Flashcards.</b>"

HELP = (
    "<b>U JO Flashcards</b>\n\n"
    "• Send /start to open the home screen.\n"
    "• Use <b>◀ Previous</b> and <b>Next ▶</b> to move between flashcards.\n"
    "• Your place is saved automatically — tap <b>Continue</b> next time."
)

# Rejection messages (Arabic, as specified)
NOT_AUTHORIZED = "هذا البوت متاح للمستخدمين المصرح لهم فقط."
NO_USERNAME = (
    "هذا البوت متاح للمستخدمين المصرح لهم فقط. "
    "يرجى التواصل مع الإدارة لتفعيل الوصول."
)

# Short popups (callback answers, max 200 chars)
FIRST_CARD = "This is the first flashcard."
LAST_CARD = "🎉 You've reached the last flashcard."
NO_FLASHCARDS = "No flashcards are available yet. Please check back later."
INVALID_CARD = "This flashcard is no longer available. Tap 🏠 Home."
UNKNOWN_ACTION = "This button is no longer valid. Send /start."
GENERIC_ERROR = "⚠️ Something went wrong. Please try again in a moment."

# Buttons
BTN_START = "📚 Start Flashcards"
BTN_CONTINUE = "▶ Continue (#{number:03d})"
BTN_FROM_BEGINNING = "⏮ Start From Beginning"
BTN_PREVIOUS = "◀ Previous"
BTN_NEXT = "Next ▶"
BTN_HOME = "🏠 Home"
