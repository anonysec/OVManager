# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Reply and inline keyboards. Labels are the primary interface."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.i18n import DEFAULT_LANG, LANG_NAMES, LOCALES, t


def main_menu(*, in_flow: bool = False, lang: str = DEFAULT_LANG) -> ReplyKeyboardMarkup:
    rows = [
        [t(lang, "btn_users"), t(lang, "btn_new")],
        [t(lang, "btn_status"), t(lang, "btn_nodes")],
        [t(lang, "btn_language")],
    ]
    if in_flow:
        rows.append([t(lang, "btn_cancel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows])


def home_actions(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline(
        [
            [(t(lang, "home_browse"), "users:0"), (t(lang, "home_create"), "new")],
            [(t(lang, "home_status"), "status"), (t(lang, "home_nodes"), "nodes")],
            [(t(lang, "home_language"), "lang")],
        ]
    )


def language_menu() -> ReplyKeyboardMarkup:
    names = list(LANG_NAMES.values())
    return ReplyKeyboardMarkup(
        [[names[0], names[1]], [names[2], names[3]]],
        resize_keyboard=True,
        is_persistent=True,
    )


def language_picker(*, lang: str | None = None, with_back: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    pair: list[tuple[str, str]] = []
    for code in LOCALES:
        mark = "✓ " if lang == code else ""
        pair.append((f"{mark}{LANG_NAMES[code]}", f"lang:{code}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    if with_back and lang:
        rows.append([(t(lang, "act_back"), "home")])
    return inline(rows)


def users_nav(page: int, total_pages: int, *, has_users: bool, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    pager: list[tuple[str, str]] = []
    if page > 0:
        pager.append((t(lang, "nav_prev"), f"users:{page - 1}"))
    if page + 1 < total_pages:
        pager.append((t(lang, "nav_next"), f"users:{page + 1}"))
    if pager:
        rows.append(pager)
    extra = [(t(lang, "home_create"), "new")]
    if has_users:
        extra.insert(0, (t(lang, "search_hint"), "search"))
    rows.append(extra)
    return inline(rows)


def user_actions(user: dict, *, is_owner: bool = False, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    uuid = user["uuid"]
    toggle = t(lang, "act_enable") if not user.get("is_active") else t(lang, "act_disable")
    rows = [
        [(t(lang, "act_extend"), f"ext:{uuid}"), (t(lang, "act_config"), f"cfg:{uuid}")],
        [(toggle, f"tog:{uuid}"), (t(lang, "act_sub"), f"sub:{uuid}")],
        [(t(lang, "act_disconnect"), f"dis:{uuid}"), (t(lang, "act_delete"), f"del:{uuid}")],
    ]
    if is_owner:
        rows.append([(t(lang, "act_edit"), f"edt:{uuid}")])
    rows.append([(t(lang, "act_back_list"), "users:0")])
    return inline(rows)


def extend_actions(uuid: str, *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline(
        [
            [(t(lang, "act_plus_30d"), f"e30:{uuid}"), (t(lang, "act_plus_90d"), f"e90:{uuid}")],
            [(t(lang, "act_plus_10gb"), f"eb10:{uuid}"), (t(lang, "act_plus_100gb"), f"eb100:{uuid}")],
            [(t(lang, "act_reset"), f"rst:{uuid}")],
            [(t(lang, "act_back"), f"u:{uuid}")],
        ]
    )


def confirm_delete(uuid: str, *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_delete_confirm"), f"okd:{uuid}"), (t(lang, "act_keep"), f"u:{uuid}")]])


def after_delete(uuid: str, *, name: str = "", lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline(
        [
            [(t(lang, "act_undo", name=name), f"undo:{uuid}")],
            [(t(lang, "act_back_list"), "users:0")],
        ]
    )


def confirm_create(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_create"), "okc"), (t(lang, "btn_cancel"), "cancel")]])


def name_prompt(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_suggest"), "auto")]])


def plan_picker(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline(
        [
            [(t(lang, "plan_standard"), "plan:standard"), (t(lang, "plan_team"), "plan:team")],
            [(t(lang, "plan_unlimited"), "plan:unlimited"), (t(lang, "plan_custom"), "plan:custom")],
        ]
    )


def node_picker(uuid: str, nodes: list[dict], *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    rows = [[(n.get("name") or t(lang, "node_fallback", id=n.get("id")), f"dl:{uuid}:{n['id']}")] for n in nodes]
    rows.append([(t(lang, "act_back"), f"u:{uuid}")])
    return inline(rows)


def back_to_user(uuid: str, *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_back_user"), f"u:{uuid}")], [(t(lang, "user_list"), "users:0")]])


def status_actions(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_refresh"), "status"), (t(lang, "btn_users"), "users:0")]])


def nodes_actions(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_refresh"), "nodes"), (t(lang, "btn_status"), "status")]])


def nodes_list(nodes: list[dict], *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    rows = [[(n.get("name") or t(lang, "node_fallback", id=n.get("id")), f"ns:{n['id']}")] for n in nodes]
    rows.append([(t(lang, "act_refresh"), "nodes"), (t(lang, "btn_status"), "status")])
    return inline(rows)


def node_detail(node_id: int, *, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_back"), "nodes")]])


def edit_fields(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline(
        [
            [(t(lang, "edit_field_traffic"), "edf:traffic"), (t(lang, "edit_field_expiry"), "edf:expiry")],
            [(t(lang, "edit_field_devices"), "edf:devices")],
        ]
    )


def confirm_edit(*, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return inline([[(t(lang, "act_save"), "edo"), (t(lang, "btn_cancel"), "edc")]])
