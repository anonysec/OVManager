from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.access import require_actor
from bot.handlers.actions import dispatch_action
from bot.handlers.create import handle_create_callback, handle_create_text, start_create
from bot.handlers.edit import handle_edit_callback, handle_edit_text
from bot.handlers.home import apply_language, show_home, show_languages
from bot.handlers.settings import show_settings
from bot.handlers.status import show_node_detail, show_nodes, show_status
from bot.handlers.users import prompt_search, search_users, show_user, show_users
from bot.i18n import has_lang, lang_of, menu_action, t
from bot.states import clear_flow, get_flow
from bot.ui import answer, edit_or_reply

log = logging.getLogger(__name__)


async def on_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any /command other than /start /help: point back at the menu instead
    of dropping it silently (filters.COMMAND never reaches on_text)."""
    if not update.effective_message:
        return
    try:
        if not has_lang(update, context):
            await show_languages(update, context, first=True)
            return
        actor = await require_actor(update, context)
        if actor is None:
            return
        clear_flow(context)
        await show_home(update, context, actor)
    except Exception:
        log.exception("Unknown-command handler failed")
        try:
            await edit_or_reply(update, t(lang_of(update, context), "error"))
        except Exception:
            pass


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    try:
        await _on_text(update, context)
    except Exception:
        log.exception("Text handler failed")
        await edit_or_reply(update, t(lang_of(update, context), "error"))


async def _on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    text = (update.effective_message.text or "").strip()
    action = menu_action(text)

    if action and action.startswith("lang:"):
        await apply_language(update, context, action.split(":", 1)[1])
        return
    if action == "language":
        clear_flow(context)
        await show_languages(update, context)
        return
    if not has_lang(update, context):
        await show_languages(update, context, first=True)
        return

    actor = await require_actor(update, context)
    if actor is None:
        return
    flow = get_flow(context)

    if action == "cancel":
        clear_flow(context)
        await show_home(update, context, actor)
        return
    if action == "users":
        clear_flow(context)
        await show_users(update, context, actor)
        return
    if action == "new":
        await start_create(update, context, actor)
        return
    if action == "status":
        clear_flow(context)
        await show_status(update, context, actor)
        return
    if action == "nodes":
        clear_flow(context)
        await show_nodes(update, context, actor)
        return
    if action == "settings":
        clear_flow(context)
        await show_settings(update, context, actor)
        return

    if flow and flow.get("kind") == "create":
        await handle_create_text(update, context, actor, text)
        return
    if flow and flow.get("kind") == "edit":
        await handle_edit_text(update, context, actor, text)
        return
    if flow and flow.get("kind") == "search":
        clear_flow(context)
        await search_users(update, context, actor, text)
        return

    await search_users(update, context, actor, text)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    data = query.data or ""
    try:
        if data == "lang":
            await answer(update)
            await show_languages(update, context)
            return
        if data.startswith("lang:"):
            await apply_language(update, context, data.split(":", 1)[1])
            return
        if not has_lang(update, context):
            await answer(update)
            await show_languages(update, context, first=True)
            return
        actor = await require_actor(update, context)
        if actor is None:
            return
        lang = lang_of(update, context)
        if await handle_create_callback(update, context, actor, data):
            return
        if await handle_edit_callback(update, context, actor, data):
            return
        if data in {"home", "cancel"}:
            await answer(update)
            clear_flow(context)
            await show_home(update, context, actor)
            return
        if data == "new":
            await answer(update)
            await start_create(update, context, actor)
            return
        if data == "status":
            await answer(update)
            await show_status(update, context, actor)
            return
        if data == "nodes":
            await answer(update)
            await show_nodes(update, context, actor)
            return
        if data == "settings":
            await answer(update)
            clear_flow(context)
            await show_settings(update, context, actor)
            return
        if data == "search":
            await answer(update)
            await prompt_search(update, context)
            return
        if data.startswith("users:"):
            from bot.callbacks import int_arg

            await answer(update)
            await show_users(update, context, actor, int_arg(data.split(":", 1)[1]))
            return
        if data.startswith("u:"):
            from bot.callbacks import uuid_arg

            await answer(update)
            uuid = uuid_arg(data[2:])
            if uuid is None:
                await edit_or_reply(update, t(lang, "user_not_found"))
                return
            await show_user(update, context, actor, uuid)
            return
        if data.startswith("ns:"):
            from bot.callbacks import int_arg

            await answer(update)
            await show_node_detail(update, context, actor, int_arg(data.split(":", 1)[1]))
            return
        if await dispatch_action(update, context, actor, data):
            return
        await answer(update)
        await edit_or_reply(update, t(lang, "unknown_action"))
    except Exception:
        log.exception("Callback failed: %s", data)
        await answer(update)
        await edit_or_reply(update, t(lang_of(update, context), "error"))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(t(lang_of(update, context), "error"))
        except Exception:
            pass
