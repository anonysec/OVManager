# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Owner-only settings overview: bot state and new-user defaults.

Read-only by design — the panel owns the values; the bot only surfaces what
the running instance was configured with (Settings → Bot / defaults).
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import config
from bot.formatters import esc, plan_label
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import settings_actions
from bot.ui import edit_or_reply


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    if actor.role != "owner":
        await edit_or_reply(update, t(lang, "settings_owner_only"))
        return
    state = t(lang, "settings_enabled") if config.bot_enabled else t(lang, "settings_disabled")
    token = t(lang, "settings_token_set") if config.token else t(lang, "settings_token_missing")
    defaults = plan_label(config.default_days, config.default_traffic_gb, config.default_max_users, lang=lang)
    lines = [
        t(lang, "settings_title"),
        "",
        t(lang, "settings_bot", state=esc(state)),
        t(lang, "settings_token", state=esc(token)),
        "",
        f"<b>{t(lang, 'settings_defaults')}</b>",
        esc(defaults),
        "",
        f"<b>{t(lang, 'settings_plans')}</b>",
    ]
    for name, spec in config.plans.items():
        label = t(lang, f"plan_{name}")
        if label == f"plan_{name}":
            label = name
        lines.append(f"· {esc(label)}  —  {esc(plan_label(*spec, lang=lang))}")
    await edit_or_reply(update, "\n".join(lines), reply_markup=settings_actions(lang=lang))
