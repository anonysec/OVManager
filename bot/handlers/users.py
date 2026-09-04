# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc, expiry_label, status_label, status_rank, user_card
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import user_actions, users_nav
from bot.ui import edit_or_reply

PAGE_SIZE = 8


def _sort_users(users: list[dict]) -> list[dict]:
    return sorted(users, key=lambda user: (status_rank(user), (user.get("name") or "").lower()))


def _page(users: list[dict], page: int) -> tuple[list[dict], int, int]:
    total = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE) if users else 1
    page = max(0, min(page, total - 1))
    start = page * PAGE_SIZE
    return users[start : start + PAGE_SIZE], page, total


def _list_markup(slice_: list[dict], page: int, total_pages: int, total: int, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for user in slice_:
        label = user.get("name") or "?"
        pair.append(InlineKeyboardButton(label, callback_data=f"u:{user['uuid']}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    extra = users_nav(page, total_pages, has_users=total > 0, lang=lang)
    rows.extend(extra.inline_keyboard)
    return InlineKeyboardMarkup(rows)


def _list_text(users: list[dict], slice_: list[dict], page: int, total_pages: int, lang: str) -> str:
    if not users:
        return t(lang, "users_empty", new=t(lang, "btn_new"))
    lines = [t(lang, "users_header", count=len(users), page=page + 1, pages=total_pages), ""]
    for user in slice_:
        lines.append(
            f"· {esc(user.get('name'))}  —  {esc(status_label(user, lang=lang))}, "
            f"{esc(expiry_label(user.get('expiry_date'), lang=lang))}"
        )
    lines.append("")
    lines.append(t(lang, "users_hint"))
    return "\n".join(lines)


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, page: int = 0) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    users = _sort_users(await panel.get_users())
    if not users and panel.last_status == 0:
        await edit_or_reply(update, t(lang, "panel_unreachable"))
        return
    slice_, page, total_pages = _page(users, page)
    await edit_or_reply(
        update,
        _list_text(users, slice_, page, total_pages, lang),
        reply_markup=_list_markup(slice_, page, total_pages, len(users), lang),
    )


async def show_user(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(
                update,
                t(lang, "user_gone"),
                reply_markup=users_nav(0, 1, has_users=False, lang=lang),
            )
        return
    sub = await panel.get_sub_url(user["uuid"])
    await edit_or_reply(
        update,
        user_card(user, sub_url=sub, lang=lang),
        reply_markup=user_actions(user, is_owner=actor.role == "owner", lang=lang),
    )


async def search_users(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, query: str) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    matches = await panel.search_users(query)
    if not matches:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(
                update,
                t(lang, "search_none", query=esc(query)),
                reply_markup=users_nav(0, 1, has_users=True, lang=lang),
            )
        return
    if len(matches) == 1:
        await show_user(update, context, actor, matches[0]["uuid"])
        return
    lines = [t(lang, "search_many", count=len(matches), query=esc(query)), ""]
    buttons: list[list[InlineKeyboardButton]] = []
    for user in matches[:16]:
        lines.append(f"· {esc(user.get('name'))}  —  {esc(status_label(user, lang=lang))}")
        buttons.append([InlineKeyboardButton(user.get("name") or "?", callback_data=f"u:{user['uuid']}")])
    buttons.append([InlineKeyboardButton(t(lang, "user_list"), callback_data="users:0")])
    await edit_or_reply(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def prompt_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = lang_of(update, context)
    context.user_data["flow"] = {"kind": "search"}
    await edit_or_reply(update, t(lang, "search_prompt"))
