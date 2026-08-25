# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Telegram bot handler modules for OVManager.

The package exposes the handlers used by bot/main.py:
    handle_message   - free-text commands (/new, /users, /renew, ...)
    handle_callback  - inline keyboard callback queries
    handle_start     - /start command
"""

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.callbacks import handle_callback as handle_callback
from bot.handlers.common import (
    # Constants
    HELP_TEXT,
    # State management
    _auth,
    # Rate limiting
    _check_rate_limit,
    # Plans
    _hub,
    # Utilities
    _parse_args,
    _periodic_cleanup,
    _pop_state,
)
from bot.handlers.common import (
    # API instance
    api as api,
)
from bot.handlers.new_user import _do_plan_create, _handle_new
from bot.handlers.renew_edit import _handle_edit, _handle_renew
from bot.handlers.status import _handle_status
from bot.handlers.users import _handle_users


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if not await _auth(update):
            await update.message.reply_text("⛔ Access Denied\nContact your panel admin to link your Telegram ID.")
            return
        uid = update.effective_user.id
        if not _check_rate_limit(uid):
            await update.message.reply_text("⚠️ Too many commands. Slow down.")
            return
        mode, args = _parse_args(text)
        if mode is None:
            uid = update.effective_user.id
            state = _pop_state(uid)
            if state:
                if state == "search":
                    return await _handle_users(update, [text])
                if state.startswith("new_"):
                    parts = state.split("_")
                    d, t, mu = int(parts[1]), int(parts[2]), int(parts[3])
                    return await _do_plan_create(update, text, d, t, mu)
            return await _hub(update)
        if mode == "new":
            return await _handle_new(update, args)
        elif mode == "status":
            return await _handle_status(update)
        elif mode == "users":
            return await _handle_users(update, args)
        elif mode == "renew":
            return await _handle_renew(update, args)
        elif mode == "edit":
            return await _handle_edit(update, args)
        elif mode == "help":
            await update.message.reply_text(HELP_TEXT, parse_mode="HTML")
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Error in handle_message")
        await update.message.reply_text("⚠️ Internal error, check logs.")
    finally:
        _periodic_cleanup()


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await _auth(update):
            await update.message.reply_text("⛔ Access Denied")
            return
        await _hub(update)
    finally:
        _periodic_cleanup()
