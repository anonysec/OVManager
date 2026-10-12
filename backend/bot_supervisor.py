"""Telegram bot supervision: one subprocess, restarted on crash.

A clean exit (rc=0) means disabled (no token / toggled off), so those retries
are throttled to once per hour instead of hot-looping; rc!=0 restarts on the
per-minute scheduler watchdog.
"""

from __future__ import annotations

import os

from backend.logger import logger

_bot_process = None
_bot_disabled_until: float | None = None
_BOT_DISABLED_RETRY_SECONDS = 3600


def _bot_would_run() -> bool:
    """Would the bot child actually poll? Same rules bot/main.py applies.

    A fresh probe config rather than the module singleton: the supervisor must
    not decide on a token/flag state the bot process loaded earlier.
    """
    from backend.bot.config import BotConfig

    probe = BotConfig()
    probe.load_from_env()
    probe.load_from_db()
    return bool(probe.token and probe.bot_enabled)


def _suppressed() -> bool:
    """Low-resource mode skips a bot that cannot run anyway.

    On a small box with no Telegram bot configured, the spawn plus the
    per-minute watchdog is pure overhead: the child would exit 0 immediately
    and the watchdog would throttle its retries to hourly. A configured bot is
    untouched — start it, watch it, restart it.
    """
    from backend.config import low_resource_enabled

    return low_resource_enabled() and not _bot_would_run()


def start_bot():
    """Start one supervised Telegram bot subprocess from the app root."""
    global _bot_process
    import subprocess
    import sys

    if _suppressed():
        _bot_process = None
        return None
    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bot_path = os.path.join(app_root, "backend", "bot", "main.py")
    if not os.path.exists(bot_path):
        return None
    if _bot_process and _bot_process.poll() is None:
        return _bot_process
    try:
        _bot_process = subprocess.Popen(
            [sys.executable, "-m", "backend.bot.main"],
            cwd=app_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )
        logger.info("Telegram bot process started (pid=%s)", _bot_process.pid)
        return _bot_process
    except OSError as exc:
        logger.error("Could not start Telegram bot: %s", exc)
        return None


def _watchdog_bot():
    """Restart the bot process if it has died. Called by scheduler every minute."""
    global _bot_process, _bot_disabled_until
    if _bot_process is None:
        # Nothing to watch — and suppression is re-evaluated on every tick,
        # never latched from startup: with the flag on and no bot configured
        # the tick spawns nothing, but an operator who turns the bot on later
        # gets it started on the next minute, no panel restart. Flag off:
        # unchanged, the lifespan owns the first spawn.
        from backend.config import low_resource_enabled

        if low_resource_enabled() and _bot_would_run():
            start_bot()
        return
    if _suppressed():
        return  # low mode, bot no longer configured: do not resurrect it
    rc = _bot_process.poll()
    if rc is None:
        _bot_disabled_until = None
        return
    if rc == 0:
        import time

        now = time.monotonic()
        if _bot_disabled_until is not None and now < _bot_disabled_until:
            return
        _bot_disabled_until = now + _BOT_DISABLED_RETRY_SECONDS
        logger.info("Telegram bot disabled (no token or turned off) — will retry in 1h")
        return
    _bot_disabled_until = None
    logger.warning("Telegram bot exited (rc=%s) — restarting", rc)
    start_bot()
