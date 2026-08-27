# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Shared Telegram send/edit helpers."""

from __future__ import annotations

from telegram import Update
from telegram.error import BadRequest


async def answer(update: Update, text: str | None = None) -> None:
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer(text)
    except Exception:
        pass


async def edit_or_reply(update: Update, text: str, *, reply_markup=None, parse_mode: str = "HTML") -> None:
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
        except Exception:
            pass
    message = update.effective_message
    if message:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
