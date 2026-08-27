# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.access import require_actor
from bot.handlers.actions import dispatch_action
from bot.handlers.create import handle_create_callback, handle_create_text, start_create
from bot.handlers.home import apply_language, show_home, show_languages
from bot.handlers.status import show_nodes, show_status
from bot.handlers.users import prompt_search, search_users, show_user, show_users
from bot.i18n import lang_of, menu_action, t
from bot.ui import answer, edit_or_reply

log = logging.getLogger(__name__)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await require_actor(update, context)
    if actor is None or not update.effective_message:
        return
    text = (update.effective_message.text or "").strip()
    flow = context.user_data.get("flow") if isinstance(context.user_data.get("flow"), dict) else None
    action = menu_action(text)

    if action == "cancel":
        context.user_data.pop("flow", None)
        await show_home(update, context, actor)
        return
    if action == "users":
        context.user_data.pop("flow", None)
        await show_users(update, context, actor)
        return
    if action == "new":
        await start_create(update, context, actor)
        return
    if action == "status":
        context.user_data.pop("flow", None)
        await show_status(update, context, actor)
        return
    if action == "nodes":
        context.user_data.pop("flow", None)
        await show_nodes(update, context, actor)
        return
    if action == "language":
        context.user_data.pop("flow", None)
        await show_languages(update, context)
        return

    if flow and flow.get("kind") == "create":
        await handle_create_text(update, context, actor, text)
        return
    if flow and flow.get("kind") == "search":
        context.user_data.pop("flow", None)
        await search_users(update, context, actor, text)
        return

    # Anything else is a username search — the everyday operator habit.
    await search_users(update, context, actor, text)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    actor = await require_actor(update, context)
    if actor is None:
        return
    lang = lang_of(update, context)
    data = query.data or ""
    try:
        if data == "lang":
            await answer(update)
            await show_languages(update, context)
            return
        if data.startswith("lang:"):
            await apply_language(update, context, data.split(":", 1)[1])
            return
        if await handle_create_callback(update, context, actor, data):
            return
        if data in {"home", "cancel"}:
            await answer(update)
            context.user_data.pop("flow", None)
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
        if data == "search":
            await answer(update)
            await prompt_search(update, context)
            return
        if data.startswith("users:"):
            await answer(update)
            try:
                page = int(data.split(":", 1)[1])
            except ValueError:
                page = 0
            await show_users(update, context, actor, page)
            return
        if data.startswith("u:"):
            await answer(update)
            await show_user(update, context, actor, data[2:])
            return
        if await dispatch_action(update, context, actor, data):
            return
        await answer(update)
        await edit_or_reply(update, t(lang, "unknown_action"))
    except Exception:
        log.exception("Callback failed: %s", data)
        await answer(update)
        await edit_or_reply(update, t(lang, "error"))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(t(lang_of(update, context), "error"))
        except Exception:
            pass
