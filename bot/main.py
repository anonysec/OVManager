# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Telegram operator bot entrypoint.

The panel starts this as ``python -m bot.main``. A standalone container can
run ``python main.py`` from the bot package directory.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot.api import close_client
from bot.config import config
from bot.handlers import handle_start, on_callback, on_error, on_text, on_unknown_command

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")


async def build_app() -> Application | None:
    config.load_from_env()
    config.load_from_db()
    config.resolve_api_url()

    if not config.token:
        log.error("No bot token — set it in Settings → Bot, or BOT_TOKEN.")
        return None
    # Honour the Settings toggle when we can see the panel database.
    # A standalone container (token in env, no local DB) is treated as enabled.
    if not config.bot_enabled:
        try:
            from backend.db.engine import SessionLocal

            SessionLocal().close()
        except Exception:
            config.bot_enabled = True
        if not config.bot_enabled:
            log.info("Bot is disabled in Settings — not polling.")
            return None

    app = Application.builder().token(config.token).build()
    # /start is the only command. Everything else is the menu or typed search.
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # Unknown /commands would otherwise vanish silently (the TEXT filter
    # above skips commands) — point back at the menu instead.
    app.add_handler(MessageHandler(filters.COMMAND, on_unknown_command))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    return app


async def run() -> None:
    app = await build_app()
    if app is None:
        return
    log.info("Starting Telegram operator bot")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])

    stop = asyncio.get_running_loop().create_future()

    def _stop() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except (NotImplementedError, RuntimeError):
            pass

    await stop
    log.info("Stopping bot")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await close_client()
    log.info("Bot stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
