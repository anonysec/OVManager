# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Reply and inline keyboards. Labels are the primary interface."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

BTN_USERS = "Users"
BTN_NEW = "New user"
BTN_STATUS = "Status"
BTN_NODES = "Nodes"
BTN_CANCEL = "Cancel"

MENU_BUTTONS = (BTN_USERS, BTN_NEW, BTN_STATUS, BTN_NODES, BTN_CANCEL)


def main_menu(*, in_flow: bool = False) -> ReplyKeyboardMarkup:
    rows = [[BTN_USERS, BTN_NEW], [BTN_STATUS, BTN_NODES]]
    if in_flow:
        rows.append([BTN_CANCEL])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows]
    )


def home_actions() -> InlineKeyboardMarkup:
    return inline(
        [
            [("Browse users", "users:0"), ("Create user", "new")],
            [("Panel status", "status"), ("Nodes", "nodes")],
        ]
    )


def users_nav(page: int, total_pages: int, *, has_users: bool) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    pager: list[tuple[str, str]] = []
    if page > 0:
        pager.append(("Previous", f"users:{page - 1}"))
    if page + 1 < total_pages:
        pager.append(("Next", f"users:{page + 1}"))
    if pager:
        rows.append(pager)
    extra = [("Create user", "new")]
    if has_users:
        extra.insert(0, ("Search — type a name", "search"))
    rows.append(extra)
    return inline(rows)


def user_actions(user: dict) -> InlineKeyboardMarkup:
    uuid = user["uuid"]
    toggle = "Enable" if not user.get("is_active") else "Disable"
    return inline(
        [
            [("Extend", f"ext:{uuid}"), ("Config", f"cfg:{uuid}")],
            [(toggle, f"tog:{uuid}"), ("Sub link", f"sub:{uuid}")],
            [("Disconnect", f"dis:{uuid}"), ("Delete", f"del:{uuid}")],
            [("Back to list", "users:0")],
        ]
    )


def extend_actions(uuid: str) -> InlineKeyboardMarkup:
    return inline(
        [
            [("+30 days", f"e30:{uuid}"), ("+90 days", f"e90:{uuid}")],
            [("+10 GB", f"eb10:{uuid}"), ("+100 GB", f"eb100:{uuid}")],
            [("Reset usage", f"rst:{uuid}")],
            [("Back", f"u:{uuid}")],
        ]
    )


def confirm_delete(uuid: str) -> InlineKeyboardMarkup:
    return inline([[("Delete user", f"okd:{uuid}"), ("Keep", f"u:{uuid}")]])


def confirm_create() -> InlineKeyboardMarkup:
    return inline([[("Create", "okc"), ("Cancel", "cancel")]])


def name_prompt() -> InlineKeyboardMarkup:
    return inline([[("Use suggested name", "auto")]])


def plan_picker() -> InlineKeyboardMarkup:
    return inline(
        [
            [("Standard", "plan:standard"), ("Team", "plan:team")],
            [("Unlimited", "plan:unlimited"), ("Custom", "plan:custom")],
        ]
    )


def node_picker(uuid: str, nodes: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(n.get("name") or f"Node {n.get('id')}", f"dl:{uuid}:{n['id']}")] for n in nodes]
    rows.append([("Back", f"u:{uuid}")])
    return inline(rows)


def back_to_user(uuid: str) -> InlineKeyboardMarkup:
    return inline([[("Back to user", f"u:{uuid}")], [("User list", "users:0")]])


def status_actions() -> InlineKeyboardMarkup:
    return inline([[("Refresh", "status"), ("Users", "users:0")]])


def nodes_actions() -> InlineKeyboardMarkup:
    return inline([[("Refresh", "nodes"), ("Status", "status")]])
