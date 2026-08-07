"""Bot handler modules for OVManager Telegram bot.

This package re-exports the public API from the original monolithic handlers.py
for backward compatibility with bot/main.py.

Modules:
    common      - Shared utilities, constants, decorators, state management
    new_user    - New user creation handlers
    status      - Server status handler
    users       - User listing, detail view, search handlers
    renew_edit  - User renew and edit handlers
    callbacks   - All inline callback query handlers
"""

from bot.handlers.common import (
    # State management
    USER_STATES,
    _cleanup_states,
    _set_state,
    _pop_state,
    # Plans
    _get_plans,
    _DEFAULT_PLANS,
    # Rate limiting
    _check_rate_limit,
    _periodic_cleanup,
    # Utilities
    _parse_args,
    _fmt_bytes,
    _days_remaining,
    _auth,
    _is_owner,
    # UI components
    _hub_kb,
    _hub,
    # Decorator
    _safe_handler,
    # Constants
    HELP_TEXT,
    USERS_PER_PAGE,
    # API instance
    api,
)

from bot.handlers.new_user import (
    _plan_kb,
    _do_plan_create,
    _handle_new,
)

from bot.handlers.status import _handle_status
from bot.handlers.users import _build_users_page, _show_user, _is_expired, _handle_users
from bot.handlers.renew_edit import _handle_renew, _execute_renew, _handle_edit
from bot.handlers.callbacks import handle_callback

from telegram import Update
from telegram.ext import ContextTypes


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if not await _auth(update):
            await update.message.reply_text(
                "⛔ Access Denied\nContact your panel admin to link your Telegram ID."
            )
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
    except Exception as e:
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
