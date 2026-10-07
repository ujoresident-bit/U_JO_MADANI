"""U JO Flashcards Bot — entry point.

Run:  python bot.py
Uses Telegram long polling. python-telegram-bot retries automatically on
network errors, and on Render the worker is restarted if the process exits.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults

from config import ConfigError, load_config
from database import Database, DatabaseError
from handlers import register_handlers

log = logging.getLogger("ujo")

DB_KEEPALIVE_SECONDS = 6 * 60 * 60  # light query so the database never looks idle


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    # httpx logs full request URLs at INFO, and Telegram URLs contain the bot
    # token. Keep these quiet so the token never reaches the logs.
    for noisy in ("httpx", "httpcore", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _db_keepalive(db: Database) -> None:
    while True:
        await asyncio.sleep(DB_KEEPALIVE_SECONDS)
        try:
            await db.ping()
            log.debug("Database keepalive OK.")
        except DatabaseError:
            log.warning("Database keepalive failed (will retry later).")


async def on_startup(app: Application) -> None:
    db: Database = app.bot_data["db"]
    try:
        await db.ping()
        log.info("Database connected.")
    except DatabaseError:
        log.error("Database connection failed at startup. The bot will keep running and retry per request.")

    await app.bot.set_my_commands(
        [BotCommand("start", "الصفحة الرئيسية"), BotCommand("help", "طريقة الاستخدام")]
    )
    app.create_task(_db_keepalive(db), name="db-keepalive")
    log.info("Bot started successfully as @%s", app.bot.username)


def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        logging.basicConfig(level=logging.INFO)
        logging.critical(str(exc))
        sys.exit(1)

    setup_logging(config.log_level)
    log.info("Starting U JO Flashcards Bot…")

    db = Database(config.supabase_url, config.supabase_key)

    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .defaults(
            Defaults(
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                protect_content=True,  # no forwarding, copying or saving
            )
        )
        .connect_timeout(15)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(10)
        .get_updates_read_timeout(40)
        .post_init(on_startup)
        .build()
    )
    app.bot_data["db"] = db
    register_handlers(app)

    # Blocks until SIGTERM/SIGINT (Render sends SIGTERM on redeploy).
    app.run_polling(
        allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
        timeout=30,               #
