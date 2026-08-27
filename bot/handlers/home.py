# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatters import esc
from bot.handlers.access import require_actor
from bot.identity import Actor
from bot.keyboards import home_actions, main_menu


def _welcome(actor: Actor) -> str:
    role = "Owner" if actor.role == "owner" else "Operator"
    return (
        f"<b>OVManager</b>\n"
        f"{esc(role)} · {esc(actor.username)}\n\n"
        "Use the menu below, or type a username to find someone.\n"
        "Creating a user is a short conversation — no slash commands needed."
    )


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor | None = None) -> None:
    if actor is None:
        actor = await require_actor(update, context)
        if actor is None:
            return
    context.user_data.pop("flow", None)
    text = _welcome(actor)
    markup = home_actions()
    query = update.callback_query
    if query:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        return
    message = update.effective_message
    if message:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await message.reply_text("What would you like to do?", reply_markup=markup)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_home(update, context)
