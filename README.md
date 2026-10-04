# U JO Flashcards Bot

بوت Telegram خاص ومجاني لعرض Flashcards للمستخدمين الذين اشتروا كتاب U JO.

**Python · Telegram Bot API (Long Polling) · Supabase · Render**

لا يوجد في هذه النسخة: AI، دفع، اشتراكات، Quiz، Scoring، أو Leaderboard.

---

## المحتويات

- [تحليل المتطلبات والقرارات التقنية](#تحليل-المتطلبات-والقرارات-التقنية)
- [Architecture وهيكل المشروع](#architecture-وهيكل-المشروع)
- **خطوات الإعداد (1 → 15)**
  1. [ما هو المشروع؟](#1-ما-هو-المشروع)
  2. [المتطلبات](#2-المتطلبات)
  3. [إنشاء Telegram Bot](#3-إنشاء-telegram-bot)
  4. [الحصول على Bot Token](#4-الحصول-على-bot-token)
  5. [إنشاء Supabase Project](#5-إنشاء-supabase-project)
  6. [إنشاء Database Tables](#6-إنشاء-database-tables)
  7. [Import Allowed Users](#7-import-allowed-users)
  8. [Import Flashcards](#8-import-flashcards)
  9. [إعداد GitHub](#9-إعداد-github)
  10. [إعداد Render](#10-إعداد-render)
  11. [إضافة Environment Variables](#11-إضافة-environment-variables)
  12. [اختيار Service Type](#12-اختيار-service-type)
  13. [إضافة Start Command](#13-إضافة-start-command)
  14. [Deploy](#14-deploy)
  15. [اختبار البوت](#15-اختبار-البوت)
- **الإدارة اليومية (16 → 19)**
  16. [إضافة مستخدم جديد](#16-إضافة-مستخدم-جديد)
  17. [تعطيل مستخدم](#17-تعطيل-مستخدم)
  18. [إضافة Flashcards](#18-إضافة-flashcards)
  19. [تحديث Flashcards](#19-تحديث-flashcards)
- [حل المشاكل الشائعة](#حل-المشاكل-الشائعة)
- [التوسع مستقبلًا](#التوسع-مستقبلًا)

---

## تحليل المتطلبات والقرارات التقنية

| القرار | الاختيار | السبب |
|---|---|---|
| مكتبة Telegram | `python-telegram-bot` v22 | مستقرة، تدعم Long Polling وإعادة الاتصال التلقائية ومعالجة SIGTERM عند إعادة التشغيل |
| الاتصال بـTelegram | Long Polling | لا حاجة لـWebhook أو domain أو port |
| نوع خدمة Render | **Background Worker** | عملية مستمرة بدون HTTP. خدمة Web المجانية تنام بعد فترة خمول، فلا تصلح لـ24/7 |
| مفتاح Supabase | Secret / `service_role` (server-side) | البوت هو الوحيد الذي يصل للبيانات |
| حماية البيانات | RLS مفعّل **بدون أي Policy** + سحب الصلاحيات من `anon` | من يملك الـURL أو الـanon key لا يستطيع قراءة أي شيء |
| الهوية | `telegram_user_id` دائمًا، و`username` للمطابقة الأولى فقط | تغيير الـusername لا يلغي الوصول |
| توحيد الـusername | Trigger في قاعدة البيانات + نفس الدالة في Python | يعمل مع كل طرق الإدخال (CSV، SQL، Script) |
| الترتيب | `order_number` فريد (UNIQUE) | Next/Previous دائمًا واضحة وبدون تكرار |
| التنقل | تعديل نفس الرسالة (message editing) | رسالة Flashcard واحدة تتغير بدل عشرات الرسائل |
| الأداء | كل ضغطة = استعلامات صغيرة `limit 1` على index | لا يتم تحميل كل الـFlashcards أبدًا |

**قرارات افتراضية تم اتخاذها (موثّقة):**

- زرا **Previous/Next** يظهران دائمًا. عند أول Flashcard يظهر تنبيه صغير "This is the first flashcard"، وعند آخرها "You've reached the last flashcard"، بدون أي خطأ.
- صفحة Home: إذا وُجد تقدم سابق تظهر **Continue (#رقم)** و**Start From Beginning**، وإلا يظهر **Start Flashcards** فقط.
- إذا تم إخفاء Flashcard كان المستخدم واقفًا عندها، فإن Continue ينقله تلقائيًا إلى أول Flashcard نشطة بعدها.
- الحد الأقصى لطول الـFlashcard هو **3900 حرف** (حد رسالة Telegram هو 4096).
- واجهة البوت بالإنجليزية، ورسائل الرفض بالعربية كما طلبت. كل النصوص في ملف `texts.py` لتعديلها بسهولة.
- البوت يعمل في المحادثات الخاصة فقط (ليس في Groups).
- عند تغيير المستخدم لـusername، يبقى حقل `username` في قاعدة البيانات كما أدخلته أنت (هو مفتاح المطابقة الذي تديره)، ويستمر الوصول عبر `telegram_user_id`.

---

## Architecture وهيكل المشروع

```
Telegram User
      ↓
Telegram Bot  (bot.py → handlers.py)
      ↓
Authorization Check  (auth.py)  ← قبل كل Command وكل ضغطة زر
      ↓
Supabase  (database.py)
 ├── allowed_users
 ├── flashcards
 └── user_progress
```

```
ujo-flashcards-bot/
├── bot.py                  # نقطة التشغيل: Logging، Long Polling، إعادة الاتصال
├── config.py               # قراءة Environment Variables (بدون طباعة أي Secret)
├── database.py             # كل استعلامات Supabase في مكان واحد
├── auth.py                 # منطق Authorization
├── flashcards.py           # تنسيق الـFlashcard والأزرار والتنقل
├── handlers.py             # /start و /help والأزرار ومعالجة الأخطاء
├── texts.py                # كل النصوص التي يراها المستخدم
├── utils.py                # توحيد الـusername
├── sql/
│   ├── schema.sql          # إنشاء الجداول + الحماية (يُشغَّل مرة واحدة)
│   └── admin_queries.sql   # استعلامات جاهزة للإدارة
├── scripts/
│   ├── import_users.py     # استيراد المستخدمين من CSV (اختياري)
│   └── import_flashcards.py# استيراد/تحديث الـFlashcards من CSV (اختياري)
├── templates/
│   ├── allowed_users_template.csv
│   └── flashcards_template.csv
├── requirements.txt
├── render.yaml             # Render Blueprint (اختياري)
├── .python-version
├── .env.example
└── .gitignore
```

**تدفق الدخول (Authorization):**

1. هل `telegram_user_id` موجود في `allowed_users`؟ ← إذا نعم: الحالة `active` تسمح، غير ذلك رفض.
2. إذا لا: هل للمستخدم username؟ ← إذا لا: رسالة "يرجى التواصل مع الإدارة".
3. ابحث عن username موحّد، حالته `active`، و**غير مرتبط بأي حساب بعد** ← اربطه بـ`telegram_user_id` وسجّل `activated_at`.
4. غير ذلك: "هذا البوت متاح للمستخدمين المصرح لهم فقط."

الشرط "غير مرتبط بأي حساب بعد" يمنع أي شخص من سرقة وصول مستخدم آخر عن طريق أخذ الـusername القديم له.

---

## 1. ما هو المشروع؟

بوت Telegram يعرض Flashcards تعليمية بالترتيب، مع أزرار Previous/Next، ويحفظ آخر Flashcard وصل إليها كل مستخدم. الوصول فقط للمستخدمين الموجودين في قائمة `allowed_users`. كل البيانات في Supabase، لذلك لا يضيع شيء عند إعادة تشغيل Render.

## 2. المتطلبات

- حساب Telegram
- حساب [Supabase](https://supabase.com) (الخطة المجانية كافية)
- حساب [GitHub](https://github.com)
- حساب [Render](https://render.com) — **Background Worker يحتاج خطة مدفوعة (Starter)**، لأن الخطة المجانية لا تشمل Background Workers، وخدمات Web المجانية تنام عند الخمول
- (اختياري) Python 3.12 على جهازك إذا أردت استخدام Scripts الاستيراد أو التجربة محليًا

## 3. إنشاء Telegram Bot

1. افتح Telegram وابحث عن **@BotFather** (بعلامة التوثيق الزرقاء).
2. أرسل `/newbot`.
3. اكتب اسم البوت، مثلًا: `U JO Flashcards`.
4. اكتب username للبوت ينتهي بـ`bot`، مثلًا: `ujo_flashcards_bot`.

## 4. الحصول على Bot Token

بعد إنشاء البوت يرسل لك BotFather رسالة فيها Token بهذا الشكل:

```
123456789:AAH...xyz
```

احفظه في مكان آمن. **لا تضعه في الكود ولا في GitHub.** إذا تسرّب، أرسل `/revoke` لـBotFather لإصدار Token جديد.

## 5. إنشاء Supabase Project

1. ادخل [supabase.com](https://supabase.com) ← **New project**.
2. اختر اسمًا (مثلًا `ujo-flashcards`) وكلمة مرور قوية للقاعدة، ومنطقة قريبة (مثلًا Frankfurt).
3. بعد اكتمال الإنشاء، اذهب إلى **Project Settings → API Keys** وانسخ:
   - **Project URL** ← سيكون `SUPABASE_URL` (يمكن إيجاده أيضًا في Settings → Data API)
   - **Secret key** (يبدأ بـ`sb_secret_`) أو **service_role** key من تبويب Legacy ← سيكون `SUPABASE_KEY`

> ⚠️ لا تستخدم الـ**anon / publishable** key. البوت يحتاج مفتاح server-side. وهذا المفتاح سري تمامًا: لا تشاركه ولا ترفعه على GitHub.
>
> إذا ظهر خطأ متعلق بالمفتاح عند استخدام Secret key الجديد، استخدم مفتاح `service_role` من تبويب Legacy API Keys.

## 6. إنشاء Database Tables

1. في Supabase اذهب إلى **SQL Editor → New query**.
2. افتح ملف `sql/schema.sql` من المشروع، انسخ محتواه كاملًا، والصقه.
3. اضغط **Run**. يجب أن تظهر `Success`.

سيتم إنشاء:

| الجدول | الوظيفة |
|---|---|
| `allowed_users` | المستخدمون المسموح لهم (`username`, `telegram_user_id`, `status`, `first_name`, `last_name`, `created_at`, `activated_at`, `last_seen_at`) |
| `flashcards` | المحتوى (`content`, `category`, `year`, `order_number`, `is_active`, `created_at`, `updated_at`) |
| `user_progress` | آخر Flashcard لكل مستخدم (`telegram_user_id`, `last_flashcard_id`, `updated_at`) |

بالإضافة إلى: Primary Keys، Foreign Keys، Unique constraints، Indexes، Triggers لتوحيد الـusername وتحديث `updated_at`، وتفعيل Row Level Security.

الملف آمن لإعادة التشغيل إذا احتجت.

## 7. Import Allowed Users

**قاعدة التوحيد:** `@User123` و`user123` و` USER123 ` كلها تُخزَّن `user123` تلقائيًا (عن طريق Trigger في القاعدة)، والمقارنة لا تتأثر بحالة الأحرف.

الـCSV Template (`templates/allowed_users_template.csv`):

```csv
username,status
user1,active
user2,active
@user3,active
User4,active
```

- `status`: إما `active` أو `disabled`. إذا تركته فارغًا يُعتبر `active`.

اختر **طريقة واحدة** من التالي:

### الطريقة A — لصق القائمة مباشرة في SQL (الأسرع لـ100–150 مستخدم)

في **SQL Editor** الصق هذا، وضع قائمتك بين علامتي `$list$` كما هي (سطر لكل username، مع @ أو بدونها):

```sql
insert into public.allowed_users (username, status)
select u, 'active'
from regexp_split_to_table($list$
@user1
@user2
user3
User4
$list$, '\s+') as u
where btrim(u) <> ''
on conflict (username) do nothing;
```

المكرر يتم تجاهله تلقائيًا، ويمكن تشغيل الأمر أكثر من مرة بأمان.

### الطريقة B — Supabase CSV Import (من الواجهة)

1. **Table Editor → allowed_users**.
2. **Insert → Import data from CSV**.
3. اختر ملف الـCSV وتأكد أن الأعمدة `username` و`status` مطابقة ← **Import**.

> ملاحظة: إذا كان الملف يحتوي username موجودًا مسبقًا سيفشل الاستيراد. في هذه الحالة استخدم الطريقة A أو C.

### الطريقة C — Script الاستيراد (يتحقق من الأخطاء ويعرض تقريرًا)

على جهازك:

```bash
pip install -r requirements.txt
cp .env.example .env        # ثم ضع SUPABASE_URL و SUPABASE_KEY داخل .env
python scripts/import_users.py my_users.csv --dry-run   # فحص فقط بدون كتابة
python scripts/import_users.py my_users.csv             # الاستيراد الفعلي
```

يضيف المستخدمين الجدد ويحدّث `status` للموجودين، ولا يلمس `telegram_user_id` أو التقدم أبدًا.

> 🔒 احتفظ بملفات المستخدمين الحقيقية داخل مجلد `data/` (موجود في `.gitignore`) حتى لا تُرفع على GitHub.

## 8. Import Flashcards

الـCSV Template (`templates/flashcards_template.csv`):

```csv
content,category,year,order_number
"Most common cause of community-acquired pneumonia in adults:

Streptococcus pneumoniae","Microbiology",2026,1
"Flashcard content 2","Basics",2026,2
"Flashcard content 3","Pharmacology",2026,3
```

قواعد مهمة:

- ضع `content` بين علامتي تنصيص `"..."`. يمكن أن يحتوي على أسطر جديدة، وستظهر كما هي في Telegram.
- إذا احتوى النص على علامة `"` اكتبها مرتين `""`.
- `order_number` رقم صحيح موجب و**غير مكرر**. هو الذي يحدد الترتيب.
- `category` و`year` اختياريان (محفوظان للاستخدام المستقبلي).
- أقصى طول للمحتوى: 3900 حرف.
- إذا جهّزت الملف في Excel أو Google Sheets، احفظه بصيغة **CSV UTF-8**.

الشكل داخل Telegram:

```
━━━━━━━━━━━━

FLASHCARD #001

Most common cause of community-acquired pneumonia in adults:

Streptococcus pneumoniae

━━━━━━━━━━━━
[ ◀ Previous ] [ Next ▶ ]
[ 🏠 Home ]
```

اختر طريقة:

- **Supabase CSV Import:** Table Editor → `flashcards` → Insert → Import data from CSV.
- **Script (يضيف ويحدّث):**
  ```bash
  python scripts/import_flashcards.py my_cards.csv --dry-run
  python scripts/import_flashcards.py my_cards.csv
  ```
- **SQL:** انظر القسم G في `sql/admin_queries.sql`.

## 9. إعداد GitHub

1. أنشئ Repository جديدًا على GitHub (يُفضّل **Private**)، مثلًا `ujo-flashcards-bot`.
2. من مجلد المشروع على جهازك:

```bash
git init
git add .
git commit -m "U JO Flashcards Bot v1"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/ujo-flashcards-bot.git
git push -u origin main
```

3. تأكد أن ملف `.env` **غير موجود** على GitHub (الملف `.gitignore` يمنع رفعه). الموجود فقط `.env.example` بدون قيم حقيقية.

> يمكنك أيضًا رفع الملفات من واجهة GitHub مباشرة (**Add file → Upload files**)، لكن لا ترفع `.env` أبدًا.

## 10. إعداد Render

1. ادخل [dashboard.render.com](https://dashboard.render.com) وسجّل دخولك باستخدام GitHub.
2. اضغط **New +** ← **Background Worker**.
3. اختر الـRepository الخاص بالمشروع (امنح Render صلاحية الوصول إليه إذا طُلب منك).
4. الإعدادات:

| الحقل | القيمة |
|---|---|
| Name | `ujo-flashcards-bot` |
| Region | الأقرب لك (مثلًا Frankfurt) |
| Branch | `main` |
| Runtime / Language | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python bot.py` |
| Instance Type | `Starter` |

> **بديل:** المشروع يحتوي `render.yaml`. يمكنك اختيار **New + → Blueprint** واختيار الـRepository، وسيقوم Render بتعبئة الإعدادات تلقائيًا، ثم يطلب منك قيم المتغيرات السرية.

## 11. إضافة Environment Variables

في نفس صفحة الإنشاء (أو لاحقًا من تبويب **Environment**)، أضف:

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | الـToken من BotFather |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | الـSecret / service_role key |
| `PYTHON_VERSION` | `3.12.8` |
| `LOG_LEVEL` | `INFO` (اختياري) |

القيم محفوظة عند Render فقط، ولا تظهر في GitHub ولا في الـLogs.

## 12. اختيار Service Type

اختر **Background Worker**.

- البوت يستخدم Long Polling: هو من يتصل بـTelegram، ولا يستقبل أي HTTP requests، لذلك لا يحتاج port.
- Background Worker يعمل باستمرار، ويعيد Render تشغيله تلقائيًا إذا توقف.
- لا يُنصح بـWeb Service المجاني: ينام بعد فترة بدون زيارات HTTP، والبوت سيتوقف عن الرد.

## 13. إضافة Start Command

```
python bot.py
```

## 14. Deploy

1. اضغط **Create Background Worker** (أو **Deploy**).
2. افتح تبويب **Logs**. عند النجاح سترى:

```
Starting U JO Flashcards Bot…
Database connected.
Bot started successfully as @ujo_flashcards_bot
```

بعد ذلك: كل `git push` إلى `main` يعيد النشر تلقائيًا.

> ⚠️ **شغّل نسخة واحدة فقط من البوت.** إذا شغّلته على جهازك وعلى Render بنفس الـToken، سيظهر في الـLogs: `Telegram conflict: another instance is polling`. أوقف النسخة المحلية. (رسالة Conflict لبضع ثوانٍ أثناء إعادة النشر طبيعية.)

## 15. اختبار البوت

قائمة فحص:

- [ ] من حساب موجود في القائمة: أرسل `/start` ← تظهر رسالة Welcome وزر **Start Flashcards**.
- [ ] اضغط **Start Flashcards** ← تظهر `FLASHCARD #001`.
- [ ] **Next** ← تتغير نفس الرسالة إلى #002.
- [ ] **Previous** عند #001 ← تنبيه "This is the first flashcard" بدون خطأ.
- [ ] **Next** عند آخر Flashcard ← تنبيه "You've reached the last flashcard".
- [ ] **Home** ثم ارجع ← تظهر **Continue (#رقم)** و**Start From Beginning**.
- [ ] في Supabase ← `allowed_users`: تم تعبئة `telegram_user_id` و`activated_at` لحسابك.
- [ ] في `user_progress` يوجد سطر لحسابك.
- [ ] من حساب غير موجود في القائمة: `/start` ← "هذا البوت متاح للمستخدمين المصرح لهم فقط."
- [ ] غيّر الـusername لحسابك في Telegram ثم `/start` ← ما زلت تستطيع الدخول.
- [ ] من Render: **Manual Deploy → Restart service** ثم `/start` ← التقدم ما زال محفوظًا.

---

## 16. إضافة مستخدم جديد

في **SQL Editor**:

```sql
insert into public.allowed_users (username) values ('@new_user')
on conflict (username) do update set status = 'active';
```

أو من **Table Editor → allowed_users → Insert row** واكتب الـusername فقط (مع @ أو بدونها).

لعدة مستخدمين: استخدم الطريقة A في [القسم 7](#7-import-allowed-users).

**مستخدم ليس لديه username:** اطلب منه Telegram User ID الرقمي الخاص به (يمكنه معرفته عبر بوت مثل `@userinfobot`)، ثم:

```sql
insert into public.allowed_users (telegram_user_id) values (123456789)
on conflict (telegram_user_id) do update set status = 'active';
```

## 17. تعطيل مستخدم

```sql
update public.allowed_users set status = 'disabled' where username = 'user1';
-- أو حسب Telegram ID:
update public.allowed_users set status = 'disabled' where telegram_user_id = 123456789;
```

يسري التعطيل **فورًا** عند أول ضغطة زر تالية، لأن الصلاحية تُفحص مع كل عملية. لإعادة التفعيل استخدم `status = 'active'`.

أو من Table Editor: غيّر قيمة `status` إلى `disabled`.

**ربط خاطئ؟** إذا دخل شخص آخر بالـusername قبل صاحبه، انظر القسم E في `sql/admin_queries.sql` لفك الربط.

## 18. إضافة Flashcards

- **دفعة كبيرة:** جهّز CSV كما في [القسم 8](#8-import-flashcards) واستورده. استخدم `order_number` يبدأ بعد آخر رقم موجود (مثلًا إذا كان آخر رقم 250، ابدأ من 251).
- **Flashcard واحدة:** Table Editor → `flashcards` → Insert row (اكتب `content` و`order_number`).
- **إدراج في المنتصف** (بين 12 و13): انظر القسم H في `sql/admin_queries.sql`.

الـFlashcards الجديدة تظهر للمستخدمين فورًا بدون إعادة تشغيل البوت.

## 19. تحديث Flashcards

- **تعديل نص:** Table Editor ← عدّل خانة `content` مباشرة، أو:
  ```sql
  update public.flashcards set content = $$Corrected text$$ where order_number = 12;
  ```
- **إخفاء بدون حذف (مُفضَّل):**
  ```sql
  update public.flashcards set is_active = false where order_number = 12;
  ```
  البوت يتخطاها تلقائيًا، ومن كان واقفًا عندها ينتقل للتالية.
- **تحديث جماعي:** عدّل ملف الـCSV ثم شغّل `python scripts/import_flashcards.py my_cards.csv`. كل صف له `order_number` موجود يتم **تحديثه**، والأرقام الجديدة تُضاف.

---

## حل المشاكل الشائعة

| المشكلة | الحل |
|---|---|
| `Missing required environment variable` في الـLogs | أضف المتغير الناقص في Render → Environment ثم أعد النشر |
| `Database connection failed` | تأكد من `SUPABASE_URL` و`SUPABASE_KEY` (مفتاح server-side وليس anon)، وأن مشروع Supabase غير متوقف |
| `Telegram conflict` باستمرار | يوجد نسخة أخرى تعمل بنفس الـToken (جهازك أو خدمة ثانية). أوقفها |
| مستخدم مصرح له يظهر له "غير مصرح" | تأكد أن الـusername في القاعدة يطابق الـusername الحالي في Telegram، وأن `status = active`، وأن الصف غير مرتبط بـ`telegram_user_id` آخر |
| "No flashcards are available yet" | لا توجد Flashcards بحالة `is_active = true` |
| البوت لا يرد إطلاقًا | افتح Render → Logs. تأكد أن الخدمة **Background Worker** وحالتها Live |

**ملاحظة عن Supabase المجاني:** المشاريع المجانية قد تتوقف بعد فترة طويلة بدون نشاط. البوت يرسل استعلامًا خفيفًا كل 6 ساعات لإبقاء القاعدة نشطة، ومع ذلك إذا توقف المشروع، أعد تشغيله من Supabase Dashboard.

---

## التوسع مستقبلًا

المشروع Modular بحيث يمكن إضافة ميزات لاحقًا بدون إعادة البناء (**غير منفذة في هذه النسخة**):

| الميزة المستقبلية | أين تُضاف |
|---|---|
| AI Explanation | Module جديد (مثلًا `ai.py`) + زر جديد في `flashcards.py` + callback جديد مثل `fc:explain:<id>` |
| Categories / Filters / Book Sections | الأعمدة `category` و`year` موجودة. تُضاف دوال في `database.py` مع index عند الحاجة |
| Search | دالة جديدة في `database.py` (مثلًا Postgres full-text search) |
| Favorites | جدول جديد `favorites` مرتبط بـ`telegram_user_id` |
| Statistics / Admin Dashboard | الجداول تحتوي `activated_at` و`last_seen_at` و`user_progress` |

صيغة callback data (`fc:<action>:<id>`) مصممة لتقبل أفعالًا جديدة بسهولة، وكل الاستعلامات معزولة في `database.py`، وكل النصوص في `texts.py`.
