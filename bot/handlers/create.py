# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.config import config
from bot.formatters import esc, plan_label
from bot.handlers.users import show_user
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import confirm_create, main_menu, name_prompt, plan_picker
from bot.ui import answer, edit_or_reply

_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")


def _flow(context: ContextTypes.DEFAULT_TYPE) -> dict:
    flow = context.user_data.get("flow")
    if not isinstance(flow, dict) or flow.get("kind") != "create":
        flow = {"kind": "create", "step": "name"}
        context.user_data["flow"] = flow
    return flow


async def start_create(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    context.user_data["flow"] = {"kind": "create", "step": "name"}
    suggested = await Panel(actor.token).next_username()
    hint = (
        t(lang, "create_hint_suggest", name=esc(suggested))
        if suggested
        else t(lang, "create_hint_type")
    )
    message = update.effective_message
    if message and not update.callback_query:
        await message.reply_text(t(lang, "create_start"), reply_markup=main_menu(in_flow=True, lang=lang))
    await edit_or_reply(update, t(lang, "create_title", hint=hint), reply_markup=name_prompt(lang=lang))


async def handle_create_text(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, text: str) -> None:
    lang = lang_of(update, context)
    flow = _flow(context)
    step = flow.get("step")
    if step == "name":
        await _accept_name(update, context, actor, text)
        return
    if step == "days":
        await _accept_int(update, context, actor, text, "days", 0, 3650, "traffic", "create_custom_traffic")
        return
    if step == "traffic":
        await _accept_int(update, context, actor, text, "traffic", 0, 100_000, "logins", "create_custom_logins")
        return
    if step == "logins":
        await _accept_int(update, context, actor, text, "logins", 0, 1000, "confirm", None)
        await _show_confirm(update, context)
        return
    await edit_or_reply(update, t(lang, "create_use_buttons"))


async def handle_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    lang = lang_of(update, context)
    flow = context.user_data.get("flow")
    if not isinstance(flow, dict) or flow.get("kind") != "create":
        return False
    if data == "auto":
        await answer(update)
        name = await Panel(actor.token).next_username()
        if not name:
            await edit_or_reply(update, t(lang, "create_no_prefix"))
            return True
        await _accept_name(update, context, actor, name)
        return True
    if data.startswith("plan:"):
        await answer(update)
        plan = data.split(":", 1)[1]
        if plan == "custom":
            flow.update(step="days")
            await edit_or_reply(update, t(lang, "create_custom_days"))
            return True
        spec = config.plans.get(plan) or config.plans.get("standard")
        if not spec:
            spec = (config.default_days, config.default_traffic_gb, config.default_max_users)
        flow["days"], flow["traffic"], flow["logins"] = spec
        flow["plan"] = plan
        flow["step"] = "confirm"
        await _show_confirm(update, context)
        return True
    if data == "okc":
        await answer(update, t(lang, "create_creating"))
        await _commit(update, context, actor)
        return True
    if data == "cancel":
        await answer(update)
        context.user_data.pop("flow", None)
        from bot.handlers.home import show_home

        await show_home(update, context, actor)
        return True
    return False


async def _accept_name(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, raw: str) -> None:
    lang = lang_of(update, context)
    name = raw.strip().replace(" ", "_")
    if not _NAME_RE.match(name):
        await edit_or_reply(update, t(lang, "create_bad_name"))
        return
    existing = await Panel(actor.token).get_user(name=name)
    if existing:
        await edit_or_reply(update, t(lang, "create_exists", name=esc(name)))
        return
    flow = _flow(context)
    flow["name"] = name
    flow["step"] = "plan"
    await edit_or_reply(
        update,
        t(lang, "create_pick_plan", name=esc(name)),
        reply_markup=plan_picker(lang=lang),
    )


async def _accept_int(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    actor: Actor,
    raw: str,
    field: str,
    lo: int,
    hi: int,
    next_step: str,
    prompt_key: str | None,
) -> None:
    lang = lang_of(update, context)
    try:
        value = int(raw.strip())
    except ValueError:
        await edit_or_reply(update, t(lang, "create_need_int"))
        return
    if value < lo or value > hi:
        await edit_or_reply(update, t(lang, "create_need_range", lo=lo, hi=hi))
        return
    flow = _flow(context)
    flow[field] = value
    flow["step"] = next_step
    if prompt_key:
        await edit_or_reply(update, t(lang, prompt_key))


async def _show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = lang_of(update, context)
    flow = _flow(context)
    name = flow.get("name") or "?"
    days = int(flow.get("days") or 0)
    traffic = int(flow.get("traffic") or 0)
    logins = int(flow.get("logins") or 0)
    await edit_or_reply(
        update,
        t(lang, "create_confirm", name=esc(name), plan=esc(plan_label(days, traffic, logins, lang=lang))),
        reply_markup=confirm_create(lang=lang),
    )


async def _commit(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    flow = _flow(context)
    name = flow.get("name")
    if not name:
        await start_create(update, context, actor)
        return
    result = await Panel(actor.token).create_user(
        name,
        int(flow.get("days") or 0),
        int(flow.get("traffic") or 0),
        int(flow.get("logins") or 0),
    )
    context.user_data.pop("flow", None)
    if not result.get("success"):
        await edit_or_reply(
            update,
            t(lang, "create_fail", msg=esc(result.get("msg") or t(lang, "create_unknown_error"))),
        )
        return
    data = result.get("data") or {}
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if uuid:
        await edit_or_reply(update, t(lang, "create_ok", name=esc(name)))
        await show_user(update, context, actor, uuid)
        return
    await edit_or_reply(update, t(lang, "create_ok_list", name=esc(name)))
