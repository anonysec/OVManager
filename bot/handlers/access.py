# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from bot.i18n import lang_of, t
from bot.identity import Actor, resolve

log = logging.getLogger(__name__)

_RATE_LIMIT = 24
_RATE_WINDOW = 60.0
_hits: dict[int, list[float]] = {}


def _rate_ok(uid: int) -> bool:
    now = time.monotonic()
    bucket = [t_hit for t_hit in _hits.get(uid, []) if now - t_hit < _RATE_WINDOW]
    if len(bucket) >= _RATE_LIMIT:
        _hits[uid] = bucket
        return False
    bucket.append(now)
    _hits[uid] = bucket
    return True


async def actor_of(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Actor | None:
    user = update.effective_user
    if user is None:
        return None
    cached = context.user_data.get("actor")
    if isinstance(cached, Actor) and cached.telegram_id == user.id:
        return cached
    actor = await resolve(user.id)
    if actor:
        context.user_data["actor"] = actor
    return actor


async def require_actor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Actor | None:
    lang = lang_of(update, context)
    user = update.effective_user
    if user and not _rate_ok(user.id):
        await _reply(update, t(lang, "rate_limited"))
        return None
    actor = await actor_of(update, context)
    if actor is None:
        await _reply(update, t(lang, "denied"))
        return None
    return actor


async def _reply(update: Update, text: str) -> None:
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass
        try:
            await query.edit_message_text(text)
            return
        except Exception:
            pass
    message = update.effective_message
    if message:
        await message.reply_text(text)
