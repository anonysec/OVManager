# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc, expiry_label, status_label, user_card
from bot.identity import Actor
from bot.keyboards import back_to_user, user_actions, users_nav
from bot.ui import edit_or_reply

PAGE_SIZE = 8


def _sort_users(users: list[dict]) -> list[dict]:
    def key(user: dict):
        status = status_label(user)
        rank = {"Online": 0, "Active": 1, "Disabled": 2, "Expired": 3}.get(status, 4)
        return (rank, (user.get("name") or "").lower())

    return sorted(users, key=key)


def _page(users: list[dict], page: int) -> tuple[list[dict], int, int]:
    total = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE) if users else 1
    page = max(0, min(page, total - 1))
    start = page * PAGE_SIZE
    return users[start : start + PAGE_SIZE], page, total


def _list_markup(slice_: list[dict], page: int, total_pages: int, total: int) -> InlineKeyboardMarkup:
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
    extra = users_nav(page, total_pages, has_users=total > 0)
    rows.extend(extra.inline_keyboard)
    return InlineKeyboardMarkup(rows)


def _list_text(users: list[dict], slice_: list[dict], page: int, total_pages: int) -> str:
    if not users:
        return "No users yet.\nTap <b>New user</b> to create the first one."
    lines = [f"<b>Users</b>  ·  {len(users)} total  ·  page {page + 1}/{total_pages}", ""]
    for user in slice_:
        lines.append(f"· {esc(user.get('name'))}  —  {esc(status_label(user))}, {esc(expiry_label(user.get('expiry_date')))}")
    lines.append("")
    lines.append("Tap a name, or type one to search.")
    return "\n".join(lines)


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, page: int = 0) -> None:
    users = _sort_users(await Panel(actor.token).get_users())
    slice_, page, total_pages = _page(users, page)
    await edit_or_reply(
        update,
        _list_text(users, slice_, page, total_pages),
        reply_markup=_list_markup(slice_, page, total_pages, len(users)),
    )


async def show_user(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> None:
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user:
        await edit_or_reply(update, "That user is no longer available.", reply_markup=users_nav(0, 1, has_users=False))
        return
    sub = await panel.get_sub_url(user["uuid"])
    await edit_or_reply(update, user_card(user, sub_url=sub), reply_markup=user_actions(user))


async def search_users(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, query: str) -> None:
    panel = Panel(actor.token)
    matches = await panel.search_users(query)
    if not matches:
        await edit_or_reply(
            update,
            f"No user matching <b>{esc(query)}</b>.\nType another name, or open the Users list.",
            reply_markup=users_nav(0, 1, has_users=True),
        )
        return
    if len(matches) == 1:
        await show_user(update, context, actor, matches[0]["uuid"])
        return
    lines = [f"<b>{len(matches)} matches</b> for {esc(query)}", ""]
    buttons: list[list[InlineKeyboardButton]] = []
    for user in matches[:16]:
        lines.append(f"· {esc(user.get('name'))}  —  {esc(status_label(user))}")
        buttons.append([InlineKeyboardButton(user.get("name") or "?", callback_data=f"u:{user['uuid']}")])
    buttons.append([InlineKeyboardButton("User list", callback_data="users:0")])
    await edit_or_reply(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def prompt_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["flow"] = {"kind": "search"}
    await edit_or_reply(update, "Type the username — or the first few letters.")
