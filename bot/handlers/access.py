# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from bot.i18n import lang_of, t
from bot.identity import Actor, resolve
from bot.ui import edit_or_reply

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


async def ensure_panel_ok(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, result: dict) -> bool:
    """Central transport/auth guard for panel results.

    Returns True when the caller may proceed (real success OR a meaningful
    API error the caller should surface). Returns False after handling the
    two cases callers must never show raw: revoked sessions (401 → drop the
    cached actor/token, ask for one more tap with a fresh session) and an
    unreachable panel (status 0 → distinct message, not an empty list).
    """
    from bot.identity import invalidate_token

    lang = lang_of(update, context)
    status = (result or {}).get("status")
    if status == 401:
        invalidate_token(actor.token)
        context.user_data.pop("actor", None)
        await edit_or_reply(update, t(lang, "session_expired"))
        return False
    if status == 0:
        await edit_or_reply(update, t(lang, "panel_unreachable"))
        return False
    return True
