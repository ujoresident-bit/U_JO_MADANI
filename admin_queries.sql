-- ============================================================================
-- U JO Flashcards Bot — Ready-to-use admin queries
-- Copy the block you need into Supabase → SQL Editor and run it.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- A) BULK ADD USERS — paste your list as-is (one username per line)
--    "@User1" and "user1" are both accepted; duplicates are skipped.
-- ----------------------------------------------------------------------------
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


-- ----------------------------------------------------------------------------
-- B) ADD ONE USER
-- ----------------------------------------------------------------------------
insert into public.allowed_users (username) values ('@new_user')
on conflict (username) do update set status = 'active';


-- ----------------------------------------------------------------------------
-- C) ADD A USER WHO HAS NO USERNAME (by Telegram User ID)
--    The user can get their numeric ID from a bot like @userinfobot.
-- ----------------------------------------------------------------------------
insert into public.allowed_users (telegram_user_id, status)
values (123456789, 'active')
on conflict (telegram_user_id) do update set status = 'active';


-- ----------------------------------------------------------------------------
-- D) DISABLE / RE-ENABLE A USER (takes effect on their very next click)
-- ----------------------------------------------------------------------------
update public.allowed_users set status = 'disabled' where username = 'user1';
update public.allowed_users set status = 'active'   where username = 'user1';

-- by Telegram ID:
update public.allowed_users set status = 'disabled' where telegram_user_id = 123456789;


-- ----------------------------------------------------------------------------
-- E) RESET A USER'S LINK (e.g. they sold their account / wrong person claimed it)
--    Progress must be deleted first because telegram_user_id becomes NULL.
--    Only for users added by username (the username is used again on next /start).
--    For users added by Telegram ID only, just delete or disable the row instead.
-- ----------------------------------------------------------------------------
delete from public.user_progress where telegram_user_id = 123456789;
update public.allowed_users
   set telegram_user_id = null, activated_at = null
 where telegram_user_id = 123456789;


-- ----------------------------------------------------------------------------
-- F) SEE USERS
-- ----------------------------------------------------------------------------
-- Everyone:
select username, telegram_user_id, status, first_name, activated_at, last_seen_at
from public.allowed_users order by created_at;

-- Added but never opened the bot yet:
select username from public.allowed_users
where telegram_user_id is null and status = 'active';


-- ----------------------------------------------------------------------------
-- G) BULK ADD FLASHCARDS (SQL alternative to CSV import)
--    $$ ... $$ lets you write text with quotes and line breaks safely.
-- ----------------------------------------------------------------------------
insert into public.flashcards (content, category, year, order_number) values
($$Most common cause of community-acquired pneumonia in adults:

Streptococcus pneumoniae$$, 'Microbiology', 2026, 1),
($$Flashcard content 2$$, 'Basics', 2026, 2),
($$Flashcard content 3$$, 'Pharmacology', 2026, 3);


-- ----------------------------------------------------------------------------
-- H) UPDATE / HIDE FLASHCARDS
-- ----------------------------------------------------------------------------
update public.flashcards set content = $$New corrected text$$ where order_number = 12;

-- Hide without deleting (users keep their progress):
update public.flashcards set is_active = false where order_number = 12;

-- Insert a card between 12 and 13: shift everything from 13 up by 1 first.
-- (Done in two steps to avoid temporary UNIQUE conflicts.)
update public.flashcards set order_number = order_number + 1000000 where order_number >= 13;
update public.flashcards set order_number = order_number - 999999  where order_number >= 1000000;
insert into public.flashcards (content, category, year, order_number)
values ($$New card text$$, 'Basics', 2026, 13);


-- ----------------------------------------------------------------------------
-- I) QUICK COUNTS
-- ----------------------------------------------------------------------------
select
  (select count(*) from public.allowed_users where status = 'active')               as active_users,
  (select count(*) from public.allowed_users where telegram_user_id is not null)    as registered_users,
  (select count(*) from public.flashcards where is_active)                          as active_flashcards;
