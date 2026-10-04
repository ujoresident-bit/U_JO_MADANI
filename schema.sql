-- ============================================================================
-- U JO Flashcards Bot — Supabase Database Schema
-- ----------------------------------------------------------------------------
-- Run this whole file ONCE in: Supabase Dashboard → SQL Editor → New query → Run
-- It is safe to re-run (uses IF NOT EXISTS / CREATE OR REPLACE).
--
-- Tables:
--   allowed_users   → who may use the bot (username for first match,
--                     telegram_user_id as the permanent identity)
--   flashcards      → flashcard content, ordered by order_number
--   user_progress   → last flashcard each user reached
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Helper: keep updated_at current on every UPDATE
-- ----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;


-- ============================================================================
-- 1) allowed_users
-- ============================================================================
create table if not exists public.allowed_users (
  id                bigint generated always as identity primary key,

  -- Normalized Telegram username: lowercase, no leading "@".
  -- Used ONLY for the first match. Normalization is enforced by a trigger,
  -- so "@User123", "user123" and " USER123 " are all stored as "user123".
  username          text unique,

  -- Permanent identity, filled automatically on the user's first /start.
  telegram_user_id  bigint unique,

  status            text not null default 'active',

  first_name        text,
  last_name         text,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  activated_at      timestamptz,          -- first successful /start
  last_seen_at      timestamptz,          -- last /start

  constraint allowed_users_status_chk
    check (status in ('active', 'disabled')),

  -- Telegram usernames: letters, digits, underscore (checked after normalization)
  constraint allowed_users_username_format_chk
    check (username is null or username ~ '^[a-z0-9_]{4,32}$'),

  -- A row must be matchable by at least one identity
  constraint allowed_users_identity_chk
    check (username is not null or telegram_user_id is not null),

  constraint allowed_users_tg_id_positive_chk
    check (telegram_user_id is null or telegram_user_id > 0)
);

comment on table  public.allowed_users is 'Users allowed to use the U JO Flashcards bot.';
comment on column public.allowed_users.username is 'Normalized username (lowercase, no @). Used for the first match only.';
comment on column public.allowed_users.telegram_user_id is 'Permanent Telegram identity, saved on first /start.';

-- Normalize username + status on every insert/update (works for CSV import too)
create or replace function public.allowed_users_normalize()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.username   := nullif(lower(regexp_replace(btrim(coalesce(new.username, '')), '^@+', '')), '');
  new.status     := coalesce(nullif(lower(btrim(coalesce(new.status, ''))), ''), 'active');
  new.first_name := nullif(btrim(coalesce(new.first_name, '')), '');
  new.last_name  := nullif(btrim(coalesce(new.last_name, '')), '');
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists allowed_users_normalize_trg on public.allowed_users;
create trigger allowed_users_normalize_trg
  before insert or update on public.allowed_users
  for each row execute function public.allowed_users_normalize();

-- Note: UNIQUE on username and telegram_user_id already creates the indexes
-- used by the bot's lookups. This one helps the "claim" query.
create index if not exists allowed_users_unclaimed_idx
  on public.allowed_users (username)
  where telegram_user_id is null;


-- ============================================================================
-- 2) flashcards
-- ============================================================================
create table if not exists public.flashcards (
  id            bigint generated always as identity primary key,

  -- Free educational text (not a question/answer). Line breaks are kept.
  -- Max 3900 chars so a card always fits in one Telegram message (limit 4096).
  content       text not null,

  category      text,          -- reserved for future filtering
  year          integer,       -- reserved for future filtering

  -- Display order (ascending). Unique so navigation is always unambiguous.
  order_number  integer not null unique,

  is_active     boolean not null default true,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint flashcards_content_not_blank_chk check (length(btrim(content)) > 0),
  constraint flashcards_content_max_len_chk   check (char_length(content) <= 3900),
  constraint flashcards_order_positive_chk    check (order_number > 0),
  constraint flashcards_year_range_chk        check (year is null or year between 1900 and 2100)
);

comment on table public.flashcards is 'Flashcard content shown to authorized users, ordered by order_number.';

create or replace function public.flashcards_normalize()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.content    := btrim(new.content);
  new.category   := nullif(btrim(coalesce(new.category, '')), '');
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists flashcards_normalize_trg on public.flashcards;
create trigger flashcards_normalize_trg
  before insert or update on public.flashcards
  for each row execute function public.flashcards_normalize();

-- Fast "next / previous / first" lookups over active cards only
create index if not exists flashcards_active_order_idx
  on public.flashcards (order_number)
  where is_active;


-- ============================================================================
-- 3) user_progress
-- ============================================================================
create table if not exists public.user_progress (
  id                 bigint generated always as identity primary key,

  telegram_user_id   bigint not null unique
                     references public.allowed_users (telegram_user_id)
                     on update cascade
                     on delete cascade,

  last_flashcard_id  bigint
                     references public.flashcards (id)
                     on delete set null,

  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

comment on table public.user_progress is 'Last flashcard reached by each user.';

drop trigger if exists user_progress_updated_at_trg on public.user_progress;
create trigger user_progress_updated_at_trg
  before update on public.user_progress
  for each row execute function public.set_updated_at();

create index if not exists user_progress_last_flashcard_idx
  on public.user_progress (last_flashcard_id);


-- ============================================================================
-- 4) Security — Row Level Security
-- ----------------------------------------------------------------------------
-- The bot connects server-side with the service_role / secret key, which
-- bypasses RLS. We enable RLS and create NO policies, so the public "anon"
-- key (and anyone who only knows the project URL) can read or write nothing.
-- ============================================================================
alter table public.allowed_users enable row level security;
alter table public.flashcards    enable row level security;
alter table public.user_progress enable row level security;

revoke all on table public.allowed_users from anon, authenticated;
revoke all on table public.flashcards    from anon, authenticated;
revoke all on table public.user_progress from anon, authenticated;

revoke execute on function public.set_updated_at()           from anon, authenticated;
revoke execute on function public.allowed_users_normalize()  from anon, authenticated;
revoke execute on function public.flashcards_normalize()     from anon, authenticated;

-- Done ✅
