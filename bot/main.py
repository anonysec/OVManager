import logging
import sys
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from bot.handlers import handle_message, handle_callback, handle_start
from bot.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def async_init():
    """Initialize the bot configuration and return the Application."""
    config.load_from_env()
    config.load_from_db()

    if not config.token:
        log.error("BOT_TOKEN not set (set via Settings page)")
        return None

    if not config.bot_enabled:
        log.info("Bot is disabled in settings — not starting")
        return None

    app = Application.builder().token(config.token).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("new", handle_message))
    app.add_handler(CommandHandler("n", handle_message))
    app.add_handler(CommandHandler("status", handle_message))
    app.add_handler(CommandHandler("s", handle_message))
    app.add_handler(CommandHandler("users", handle_message))
    app.add_handler(CommandHandler("u", handle_message))
    app.add_handler(CommandHandler("renew", handle_message))
    app.add_handler(CommandHandler("r", handle_message))
    app.add_handler(CommandHandler("edit", handle_message))
    app.add_handler(CommandHandler("e", handle_message))
    app.add_handler(CommandHandler("help", handle_message))
    app.add_handler(CommandHandler("dupnode", handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot initialized successfully")
    return app


async def run_bot_async():
    """Run the bot asynchronously."""
    app = await async_init()
    if app:
        log.info("Starting bot polling...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        # Wait forever - the updater handles the event loop
        await asyncio.Future()
    else:
        log.warning("Bot not started - check Settings page")


def main():
    """Run the bot."""
    log.info("Bot starting up...")
    asyncio.run(run_bot_async())


if __name__ == "__main__":
    main()