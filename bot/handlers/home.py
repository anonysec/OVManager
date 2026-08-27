# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatters import esc
from bot.handlers.access import require_actor
from bot.i18n import LANG_NAMES, LANG_PROMPT, has_lang, lang_of, set_lang, t
from bot.identity import Actor
from bot.keyboards import home_actions, language_menu, language_picker, main_menu
from bot.ui import answer, edit_or_reply


def _welcome(actor: Actor, lang: str) -> str:
    role = t(lang, "role_owner") if actor.role == "owner" else t(lang, "role_operator")
    return t(lang, "welcome", role=esc(role), username=esc(actor.username))


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor | None = None) -> None:
    if actor is None:
        actor = await require_actor(update, context)
        if actor is None:
            return
    lang = lang_of(update, context)
    context.user_data.pop("flow", None)
    text = _welcome(actor, lang)
    markup = home_actions(lang=lang)
    query = update.callback_query
    if query:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        return
    message = update.effective_message
    if message:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=main_menu(lang=lang),
        )
        await message.reply_text(t(lang, "home_prompt"), reply_markup=markup)


async def show_languages(update: Update, context: ContextTypes.DEFAULT_TYPE, *, first: bool = False) -> None:
    chosen = has_lang(update, context)
    lang = lang_of(update, context) if chosen else None
    text = LANG_PROMPT if first or not chosen else t(lang or "en", "lang_title")
    picker = language_picker(lang=lang, with_back=chosen)
    query = update.callback_query
    if query:
        await edit_or_reply(update, text, reply_markup=picker)
        return
    message = update.effective_message
    if not message:
        return
    if first or not chosen:
        await message.reply_text(text, parse_mode="HTML", reply_markup=language_menu())
        await message.reply_text("English  ·  فارسی  ·  Русский  ·  中文", reply_markup=picker)
        return
    await edit_or_reply(update, text, reply_markup=picker)


async def apply_language(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    lang = set_lang(context, code, update)
    context.user_data.pop("flow", None)
    await answer(update)
    actor = await require_actor(update, context)
    if actor is None:
        return
    message = update.effective_message
    if message:
        await message.reply_text(
            t(lang, "lang_set", name=LANG_NAMES.get(lang, lang)),
            reply_markup=main_menu(lang=lang),
        )
        await message.reply_text(_welcome(actor, lang), parse_mode="HTML", reply_markup=home_actions(lang=lang))


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_lang(update, context):
        await show_languages(update, context, first=True)
        return
    await show_home(update, context)
