# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Owner-only user edit flow: fix quota, expiry or device limit in place.

The panel's PUT /users/{uuid} supports full edits, but the bot previously
exposed no path to it (update_user() was dead code) — a typo'd quota could
only be fixed from the panel. Bounded to three fields with the same ranges
as the create flow; admins keep extend/reset/toggle only.
"""

from __future__ import annotations

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc
from bot.handlers.access import ensure_panel_ok
from bot.handlers.users import show_user
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import back_to_user, confirm_edit, edit_fields
from bot.ui import answer, edit_or_reply

GB = 1073741824

_FIELDS = {
    "traffic": {"lo": 0, "hi": 100_000, "prompt": "edit_value_traffic"},
    "expiry": {"lo": 1, "hi": 3650, "prompt": "edit_value_expiry"},
    "devices": {"lo": 0, "hi": 1000, "prompt": "edit_value_devices"},
}


def _flow(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    flow = context.user_data.get("flow")
    if not isinstance(flow, dict) or flow.get("kind") != "edit":
        return None
    return flow


async def start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> None:
    lang = lang_of(update, context)
    if actor.role != "owner":
        await edit_or_reply(update, t(lang, "edit_owner_only"))
        return
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(update, t(lang, "user_not_found"), reply_markup=back_to_user(uuid, lang=lang))
        return
    context.user_data["flow"] = {"kind": "edit", "step": "field", "uuid": uuid, "name": user.get("name") or ""}
    await edit_or_reply(
        update,
        t(lang, "edit_title", name=esc(user.get("name") or t(lang, "this_user"))),
        reply_markup=edit_fields(lang=lang),
    )


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    flow = _flow(context)
    if data.startswith("edt:"):
        await answer(update)
        await start_edit(update, context, actor, data[4:])
        return True
    if flow is None:
        return False
    lang = lang_of(update, context)
    if data.startswith("edf:"):
        await answer(update)
        field = data[4:]
        spec = _FIELDS.get(field)
        if spec is None:
            return True
        flow["field"] = field
        flow["step"] = "value"
        await edit_or_reply(update, t(lang, spec["prompt"]))
        return True
    if data == "edo":
        await answer(update, t(lang, "updating"))
        await _commit(update, context, actor)
        return True
    if data == "edc":
        await answer(update)
        context.user_data.pop("flow", None)
        await show_user(update, context, actor, flow.get("uuid") or "")
        return True
    return False


async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, text: str) -> None:
    lang = lang_of(update, context)
    flow = _flow(context)
    if flow is None or flow.get("step") != "value":
        await edit_or_reply(update, t(lang, "create_use_buttons"))
        return
    spec = _FIELDS.get(flow.get("field") or "")
    if spec is None:
        context.user_data.pop("flow", None)
        return
    try:
        value = int(text.strip())
    except ValueError:
        await edit_or_reply(update, t(lang, "create_need_int"))
        return
    if value < spec["lo"] or value > spec["hi"]:
        await edit_or_reply(update, t(lang, "create_need_range", lo=spec["lo"], hi=spec["hi"]))
        return
    flow["value"] = value
    flow["step"] = "confirm"
    await edit_or_reply(
        update,
        t(lang, "edit_confirm", name=esc(flow.get("name") or "?"), value=esc(_describe(flow, lang))),
        reply_markup=confirm_edit(lang=lang),
    )


def _describe(flow: dict, lang: str) -> str:
    field = flow.get("field")
    value = int(flow.get("value") or 0)
    if field == "traffic":
        return t(lang, "plan_traffic", gb=value) if value else t(lang, "plan_traffic_unlim")
    if field == "expiry":
        return t(lang, "plan_days", days=value)
    return t(lang, "plan_devices", n=value) if value else t(lang, "plan_devices_unlim")


async def _commit(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    flow = _flow(context)
    if flow is None or flow.get("step") != "confirm":
        return
    if actor.role != "owner":
        context.user_data.pop("flow", None)
        await edit_or_reply(update, t(lang, "edit_owner_only"))
        return
    uuid = flow.get("uuid") or ""
    name = flow.get("name") or ""
    field = flow.get("field")
    value = int(flow.get("value") or 0)
    payload: dict = {}
    if field == "traffic":
        payload["total"] = None if value == 0 else value * GB
    elif field == "expiry":
        payload["expiry_date"] = (date.today() + timedelta(days=value)).isoformat()
    elif field == "devices":
        payload["max_logins"] = value
    else:
        context.user_data.pop("flow", None)
        return
    panel = Panel(actor.token)
    result = await panel.update_user(uuid, name, **payload)
    context.user_data.pop("flow", None)
    if not await ensure_panel_ok(update, context, actor, result):
        return
    if result.get("success"):
        await edit_or_reply(update, t(lang, "edit_ok", name=esc(name)))
        await show_user(update, context, actor, uuid)
    else:
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "update_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
