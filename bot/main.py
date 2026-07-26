import logging
import signal
import asyncio
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from bot.handlers import handle_message, handle_callback, handle_start
from bot.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def async_init():
    """Initialize the bot configuration and return the Application."""
    config.load_from_env()
    config.load_from_db()
    config.resolve_api_url()

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot initialized successfully")
    return app


async def run_bot_async():
    """Run the bot with graceful shutdown."""
    app = await async_init()
    if not app:
        log.warning("Bot not started — check Settings page")
        return

    log.info("Starting bot polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Wait for shutdown signal
    stop = asyncio.Future()

    def _signal_handler():
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows
        except RuntimeError:
            pass  # Not in main thread

    await stop

    # Graceful shutdown
    log.info("Shutting down bot...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    log.info("Bot stopped")


def main():
    """Run the bot."""
    log.info("Bot starting up...")
    asyncio.run(run_bot_async())


def run_bot_threaded():
    """Run bot in a thread-safe manner (for uvicorn startup)."""
    # Check if we're in main thread (call from command line) or a worker thread
    if threading.current_thread() is threading.main_thread():
        main()
    else:
        # In thread: use custom event loop without signal handlers
        _run_bot_in_thread()


def _run_bot_in_thread():
    """Bot loop for thread execution - avoids signal handler issues."""
    log.info("Bot thread starting...")

    # Create a new event loop (no signal handlers)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _bot_loop():
        try:
            app = await async_init()
            if not app:
                log.warning("Bot not started — check Settings page")
                return

            log.info("Starting bot polling (thread mode)...")
            await app.initialize()
            await app.start()
            await app.updater.start_polling()

            # Keep running - start_polling() starts background task, we wait forever
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Bot error: %s", e)
        finally:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception:
                pass
            log.info("Bot stopped")

    try:
        loop.run_until_complete(_bot_loop())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
