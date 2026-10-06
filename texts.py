"""All user-facing texts in one place, so wording can be changed easily.

Messages are sent with HTML parse mode: use <b>, <i> only, and escape & < >.
"""

# ------------------------------------------------------------------ home
WELCOME = (
    "👋 أهلاً بك في U JO MADANI\n"
    "🏥 هذا البوت مخصص للمتقدمين لامتحان المدني في الخدمات الطبية الملكية.\n"
    "📚 يمكنك استعراض الأسئلة وإظهار الإجابات، وحفظ الأسئلة المهمة ⭐، "
    "وإضافة ملاحظاتك الشخصية 📝 والرجوع إليها في أي وقت.\n"
    "🎯 نتمنى لك التوفيق،\n"
    "U JO RESIDENT"
)

HELP = (
    "<b>U JO Flashcards</b>\n\n"
    "• أرسل /start لفتح الصفحة الرئيسية.\n"
    "• <b>👁 إظهار الإجابة</b> لعرض إجابة الـ Flashcard.\n"
    "• <b>◀ السابق</b> و<b>التالي ▶</b> للتنقل.\n"
    "• <b>⭐ حفظ</b> لإضافة الـ Flashcard إلى المحفوظة.\n"
    "• <b>📝 Note</b> لإضافة ملاحظة شخصية لا يراها غيرك.\n"
    "• يتم حفظ مكانك تلقائيًا، واضغط <b>🚀 لنبدأ</b> للمتابعة."
)

# Rejection messages (Arabic, as specified)
NOT_AUTHORIZED = "هذا البوت متاح للمستخدمين المصرح لهم فقط."
NO_USERNAME = (
    "هذا البوت متاح للمستخدمين المصرح لهم فقط. "
    "يرجى التواصل مع الإدارة لتفعيل الوصول."
)

# ------------------------------------------------------------------ flashcard
CARD_TITLE = "🧠 <b>FLASHCARD {number:03d}</b>"
ANSWER_HIDDEN = "🔒 <i>الإجابة مخفية</i>"
ANSWER_SHOWN = "✅ <b>{answer}</b>"

# ------------------------------------------------------------------ saved list
SAVED_TITLE = "⭐ <b>المحفوظة</b> ({total})"
SAVED_EMPTY = "⭐ <b>المحفوظة</b>\n\nلا توجد Flashcards محفوظة حالياً."
SAVED_HINT = "<i>اختر رقمًا لفتح الـ Flashcard.</i>"

# ------------------------------------------------------------------ notes
NOTE_PROMPT = "📝 اكتب ملاحظتك لهذه الـ Flashcard:"
NOTE_EDIT_PROMPT = "✏️ اكتب النص الجديد للملاحظة:"
NOTE_CURRENT = "<b>الملاحظة الحالية:</b>"
NOTE_VIEW_TITLE = "📝 <b>ملاحظتك</b> · FLASHCARD {number:03d}"
NOTE_DELETE_CONFIRM = "هل أنت متأكد من حذف هذه الملاحظة؟"
NOTE_EMPTY = "⚠️ الملاحظة فارغة. اكتب نص الملاحظة أو اضغط إلغاء."
NOTE_TOO_LONG = "⚠️ الملاحظة طويلة جدًا (الحد الأقصى {max} حرف). اختصرها وأرسلها مرة أخرى."
NOTE_TEXT_ONLY = "⚠️ الرجاء إرسال الملاحظة كنص فقط، أو اضغط إلغاء."
NOTE_SAVED = "✅ تم حفظ ملاحظتك."
NOTE_DELETED = "🗑 تم حذف الملاحظة."

# ------------------------------------------------------------------ short popups (max 200 chars)
SAVED_ADDED = "⭐ تمت إضافتها إلى المحفوظة."
SAVED_REMOVED = "تمت إزالتها من المحفوظة."
FIRST_CARD = "هذه أول Flashcard."
LAST_CARD = "🎉 وصلت إلى آخر Flashcard."
NO_FLASHCARDS = "لا توجد Flashcards متاحة حاليًا. يرجى المحاولة لاحقًا."
INVALID_CARD = "هذه الـ Flashcard لم تعد متاحة."
UNKNOWN_ACTION = "هذا الزر لم يعد صالحًا. أرسل /start."
GENERIC_ERROR = "⚠️ حدث خطأ مؤقت. يرجى المحاولة مرة أخرى بعد قليل."

# ------------------------------------------------------------------ buttons
BTN_START = "🚀 لنبدأ"
BTN_FROM_BEGINNING = "⏮ من البداية"
BTN_SAVED_LIST = "⭐ المحفوظة"
BTN_HOME = "🏠 الرئيسية"
BTN_SHOW_ANSWER = "👁 إظهار الإجابة"
BTN_SAVE = "⭐ حفظ"
BTN_SAVED_ON = "⭐ محفوظة"
BTN_ADD_NOTE = "📝 Note"
BTN_VIEW_NOTE = "📝 عرض الملاحظة"
BTN_PREVIOUS = "◀ السابق"
BTN_NEXT = "التالي ▶"
BTN_CANCEL = "❌ إلغاء"
BTN_EDIT_NOTE = "✏️ تعديل الملاحظة"
BTN_DELETE_NOTE = "🗑 حذف الملاحظة"
BTN_BACK = "↩️ العودة"
BTN_CONFIRM_DELETE = "نعم، احذفها"
BTN_CANCEL_PLAIN = "إلغاء"
