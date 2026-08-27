# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc
from bot.handlers.users import show_user
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import back_to_user, confirm_delete, extend_actions, node_picker
from bot.ui import answer, edit_or_reply

GB = 1073741824


async def dispatch_action(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    if data.startswith("ext:"):
        lang = lang_of(update, context)
        await answer(update)
        uuid = data[4:]
        user = await Panel(actor.token).get_user(uuid=uuid)
        name = (user or {}).get("name") or t(lang, "this_user")
        await edit_or_reply(update, t(lang, "extend_title", name=esc(name)), reply_markup=extend_actions(uuid, lang=lang))
        return True
    if data.startswith("e30:"):
        return await _extend(update, context, actor, data[4:], days=30)
    if data.startswith("e90:"):
        return await _extend(update, context, actor, data[4:], days=90)
    if data.startswith("eb10:"):
        return await _extend(update, context, actor, data[5:], bytes_=10 * GB)
    if data.startswith("eb100:"):
        return await _extend(update, context, actor, data[6:], bytes_=100 * GB)
    if data.startswith("rst:"):
        return await _reset(update, context, actor, data[4:])
    if data.startswith("tog:"):
        return await _toggle(update, context, actor, data[4:])
    if data.startswith("dis:"):
        return await _disconnect(update, context, actor, data[4:])
    if data.startswith("del:"):
        return await _ask_delete(update, context, actor, data[4:])
    if data.startswith("okd:"):
        return await _delete(update, context, actor, data[4:])
    if data.startswith("sub:"):
        return await _sub(update, context, actor, data[4:])
    if data.startswith("cfg:"):
        return await _cfg(update, context, actor, data[4:])
    if data.startswith("dl:"):
        return await _download(update, context, actor, data[3:])
    return False


async def _extend(
    update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str, *, days: int = 0, bytes_: int = 0
) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "updating"))
    result = await Panel(actor.token).extend_user(uuid, days=days, bytes_=bytes_)
    if result.get("success"):
        msg = t(lang, "updated_days", days=days) if days else t(lang, "updated_gb", gb=bytes_ // GB)
        await edit_or_reply(update, msg, reply_markup=back_to_user(uuid, lang=lang))
    else:
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "update_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
    return True


async def _reset(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "resetting"))
    result = await Panel(actor.token).reset_usage(uuid)
    msg = t(lang, "reset_ok") if result.get("success") else (result.get("msg") or t(lang, "reset_fail"))
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid, lang=lang))
    return True


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user:
        await edit_or_reply(update, t(lang, "user_not_found"))
        return True
    new_status = not bool(user.get("is_active"))
    result = await panel.set_status(uuid, user.get("name") or "", new_status)
    if not result.get("success"):
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "status_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
        return True
    await show_user(update, context, actor, uuid)
    return True


async def _disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "disconnecting"))
    result = await Panel(actor.token).disconnect(uuid)
    msg = t(lang, "disconnect_ok") if result.get("success") else (result.get("msg") or t(lang, "disconnect_fail"))
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid, lang=lang))
    return True


async def _ask_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    user = await Panel(actor.token).get_user(uuid=uuid)
    name = (user or {}).get("name") or t(lang, "this_user")
    await edit_or_reply(
        update,
        t(lang, "delete_ask", name=esc(name)),
        reply_markup=confirm_delete(uuid, lang=lang),
    )
    return True


async def _delete(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "deleting"))
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    name = (user or {}).get("name") or t(lang, "this_user")
    result = await panel.delete_user(uuid)
    if result.get("success"):
        await edit_or_reply(update, t(lang, "delete_ok", name=esc(name)))
    else:
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "delete_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
    return True


async def _sub(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    url = await panel.get_sub_url(uuid)
    if not url:
        await edit_or_reply(update, t(lang, "sub_missing"), reply_markup=back_to_user(uuid, lang=lang))
        return True
    name = (user or {}).get("name") or t(lang, "this_user")
    await edit_or_reply(
        update,
        t(lang, "sub_for", name=esc(name), url=esc(url)),
        reply_markup=back_to_user(uuid, lang=lang),
    )
    return True


async def _cfg(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    nodes = await panel.get_nodes()
    if not nodes:
        await edit_or_reply(update, t(lang, "no_nodes"), reply_markup=back_to_user(uuid, lang=lang))
        return True
    name = (user or {}).get("name") or t(lang, "this_user")
    await edit_or_reply(
        update,
        t(lang, "cfg_pick", name=esc(name)),
        reply_markup=node_picker(uuid, nodes, lang=lang),
    )
    return True


async def _download(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, rest: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "preparing"))
    try:
        uuid, node_id_s = rest.rsplit(":", 1)
        node_id = int(node_id_s)
    except ValueError:
        await edit_or_reply(update, t(lang, "dl_invalid"))
        return True
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    nodes = await panel.get_nodes()
    node = next((n for n in nodes if int(n.get("id") or 0) == node_id), None)
    body = await panel.download_ovpn(uuid, node_id)
    message = update.effective_message
    if not body:
        await edit_or_reply(update, t(lang, "dl_fail"), reply_markup=back_to_user(uuid, lang=lang))
        return True
    filename = f"{(user or {}).get('name') or 'user'}-{(node or {}).get('name') or node_id}.ovpn"
    if message:
        await message.reply_document(document=InputFile(BytesIO(body), filename=filename))
    await edit_or_reply(update, t(lang, "dl_sent", filename=esc(filename)), reply_markup=back_to_user(uuid, lang=lang))
    return True
