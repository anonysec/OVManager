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
    context.user_data["flow"] = {"kind": "create", "step": "name"}
    suggested = await Panel(actor.token).next_username()
    hint = (
        f"Suggested name from your prefix: <code>{esc(suggested)}</code>\n"
        "Send that, type another name, or tap <b>Suggest name</b>."
        if suggested
        else "Type a username (3–64 letters, numbers or underscores)."
    )
    message = update.effective_message
    if message and not update.callback_query:
        await message.reply_text("Creating a user. Tap Cancel to stop.", reply_markup=main_menu(in_flow=True))
    await edit_or_reply(update, f"<b>New user</b>\n\n{hint}", reply_markup=name_prompt())


async def handle_create_text(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, text: str) -> None:
    flow = _flow(context)
    step = flow.get("step")
    if step == "name":
        await _accept_name(update, context, actor, text)
        return
    if step == "days":
        await _accept_int(update, context, actor, text, "days", 0, 3650, "traffic", "How many GB of traffic? Send 0 for unlimited.")
        return
    if step == "traffic":
        await _accept_int(update, context, actor, text, "traffic", 0, 100_000, "logins", "How many simultaneous devices? Send 0 for unlimited.")
        return
    if step == "logins":
        await _accept_int(update, context, actor, text, "logins", 0, 1000, "confirm", None)
        await _show_confirm(update, context)
        return
    await edit_or_reply(update, "Use the buttons below, or tap Cancel.")


async def handle_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    flow = context.user_data.get("flow")
    if not isinstance(flow, dict) or flow.get("kind") != "create":
        return False
    if data == "auto":
        await answer(update)
        name = await Panel(actor.token).next_username()
        if not name:
            await edit_or_reply(
                update,
                "No username prefix is configured for your account.\nType a name instead.",
            )
            return True
        await _accept_name(update, context, actor, name)
        return True
    if data.startswith("plan:"):
        await answer(update)
        plan = data.split(":", 1)[1]
        if plan == "custom":
            flow.update(step="days")
            await edit_or_reply(update, "Custom plan — how many days should this user last?\nSend 0 for no expiry.")
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
        await answer(update, "Creating…")
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
    name = raw.strip().replace(" ", "_")
    if not _NAME_RE.match(name):
        await edit_or_reply(
            update,
            "That name isn't valid. Use 3–64 letters, numbers or underscores, no spaces.",
        )
        return
    existing = await Panel(actor.token).get_user(name=name)
    if existing:
        await edit_or_reply(update, f"<b>{esc(name)}</b> already exists. Pick another name.")
        return
    flow = _flow(context)
    flow["name"] = name
    flow["step"] = "plan"
    await edit_or_reply(
        update,
        f"Username <b>{esc(name)}</b>.\n\nChoose a plan, or tap Custom to set the numbers yourself.",
        reply_markup=plan_picker(),
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
    prompt: str | None,
) -> None:
    try:
        value = int(raw.strip())
    except ValueError:
        await edit_or_reply(update, "Send a whole number.")
        return
    if value < lo or value > hi:
        await edit_or_reply(update, f"Send a number between {lo} and {hi}.")
        return
    flow = _flow(context)
    flow[field] = value
    flow["step"] = next_step
    if prompt:
        await edit_or_reply(update, prompt)


async def _show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = _flow(context)
    name = flow.get("name") or "?"
    days = int(flow.get("days") or 0)
    traffic = int(flow.get("traffic") or 0)
    logins = int(flow.get("logins") or 0)
    await edit_or_reply(
        update,
        f"<b>Create {esc(name)}</b>\n\n{esc(plan_label(days, traffic, logins))}\n\nCreate this user?",
        reply_markup=confirm_create(),
    )


async def _commit(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
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
        await edit_or_reply(update, f"Could not create the user.\n{esc(result.get('msg') or 'Unknown error')}")
        return
    data = result.get("data") or {}
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if uuid:
        await edit_or_reply(update, f"Created <b>{esc(name)}</b>.")
        await show_user(update, context, actor, uuid)
        return
    await edit_or_reply(update, f"Created <b>{esc(name)}</b>. Open Users to see the card.")
