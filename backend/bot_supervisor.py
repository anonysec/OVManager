"""Telegram bot supervision: one subprocess, restarted on crash.

A clean exit (rc=0) means disabled (no token / toggled off) and is not
hot-looped: retries are throttled to once per hour. Real crashes (rc!=0)
restart via the per-minute scheduler watchdog.
"""

from __future__ import annotations

import os

from backend.logger import logger

_bot_process = None
_bot_disabled_until: float | None = None
_BOT_DISABLED_RETRY_SECONDS = 3600


def start_bot():
    """Start one supervised Telegram bot subprocess from the app root."""
    global _bot_process
    import subprocess
    import sys

    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bot_path = os.path.join(app_root, "bot", "main.py")
    if not os.path.exists(bot_path):
        return None
    if _bot_process and _bot_process.poll() is None:
        return _bot_process
    try:
        _bot_process = subprocess.Popen(
            [sys.executable, "-m", "bot.main"],
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
        return  # Bot was never started (no bot.main.py)
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
