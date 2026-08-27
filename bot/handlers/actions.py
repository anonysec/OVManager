# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc
from bot.handlers.users import show_user
from bot.identity import Actor
from bot.keyboards import back_to_user, confirm_delete, extend_actions, node_picker
from bot.ui import answer, edit_or_reply

GB = 1073741824


async def dispatch_action(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    if data.startswith("ext:"):
        await answer(update)
        uuid = data[4:]
        user = await Panel(actor.token).get_user(uuid=uuid)
        name = (user or {}).get("name") or "user"
        await edit_or_reply(update, f"Extend <b>{esc(name)}</b>", reply_markup=extend_actions(uuid))
        return True
    if data.startswith("e30:"):
        return await _extend(update, actor, data[4:], days=30)
    if data.startswith("e90:"):
        return await _extend(update, actor, data[4:], days=90)
    if data.startswith("eb10:"):
        return await _extend(update, actor, data[5:], bytes_=10 * GB)
    if data.startswith("eb100:"):
        return await _extend(update, actor, data[6:], bytes_=100 * GB)
    if data.startswith("rst:"):
        return await _reset(update, actor, data[4:])
    if data.startswith("tog:"):
        return await _toggle(update, context, actor, data[4:])
    if data.startswith("dis:"):
        return await _disconnect(update, actor, data[4:])
    if data.startswith("del:"):
        return await _ask_delete(update, actor, data[4:])
    if data.startswith("okd:"):
        return await _delete(update, actor, data[4:])
    if data.startswith("sub:"):
        return await _sub(update, actor, data[4:])
    if data.startswith("cfg:"):
        return await _cfg(update, actor, data[4:])
    if data.startswith("dl:"):
        return await _download(update, actor, data[3:])
    return False


async def _extend(update: Update, actor: Actor, uuid: str, *, days: int = 0, bytes_: int = 0) -> bool:
    await answer(update, "Updating…")
    result = await Panel(actor.token).extend_user(uuid, days=days, bytes_=bytes_)
    if result.get("success"):
        what = f"+{days} days" if days else f"+{bytes_ // GB} GB"
        await edit_or_reply(update, f"Updated. {esc(what)}.", reply_markup=back_to_user(uuid))
    else:
        await edit_or_reply(update, esc(result.get("msg") or "Could not update this user."), reply_markup=back_to_user(uuid))
    return True


async def _reset(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update, "Resetting…")
    result = await Panel(actor.token).reset_usage(uuid)
    msg = "Usage counters reset." if result.get("success") else (result.get("msg") or "Reset failed.")
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid))
    return True


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user:
        await edit_or_reply(update, "User not found.")
        return True
    new_status = not bool(user.get("is_active"))
    result = await panel.set_status(uuid, user.get("name") or "", new_status)
    if not result.get("success"):
        await edit_or_reply(update, esc(result.get("msg") or "Could not change status."), reply_markup=back_to_user(uuid))
        return True
    await show_user(update, context, actor, uuid)
    return True


async def _disconnect(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update, "Disconnecting…")
    result = await Panel(actor.token).disconnect(uuid)
    msg = "Disconnect requested on every node." if result.get("success") else (result.get("msg") or "Disconnect failed.")
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid))
    return True


async def _ask_delete(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update)
    user = await Panel(actor.token).get_user(uuid=uuid)
    name = (user or {}).get("name") or "this user"
    await edit_or_reply(
        update,
        f"Delete <b>{esc(name)}</b>?\nThey will be removed from every node. You can undo this from the panel for a couple of minutes.",
        reply_markup=confirm_delete(uuid),
    )
    return True


async def _delete(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update, "Deleting…")
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    name = (user or {}).get("name") or "User"
    result = await panel.delete_user(uuid)
    if result.get("success"):
        await edit_or_reply(update, f"Deleted <b>{esc(name)}</b>.")
    else:
        await edit_or_reply(update, esc(result.get("msg") or "Delete failed."), reply_markup=back_to_user(uuid))
    return True


async def _sub(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    url = await panel.get_sub_url(uuid)
    if not url:
        await edit_or_reply(update, "No subscription URL is configured on the panel.", reply_markup=back_to_user(uuid))
        return True
    name = (user or {}).get("name") or "user"
    await edit_or_reply(
        update,
        f"Subscription for <b>{esc(name)}</b>\n<code>{esc(url)}</code>",
        reply_markup=back_to_user(uuid),
    )
    return True


async def _cfg(update: Update, actor: Actor, uuid: str) -> bool:
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    nodes = await panel.get_nodes()
    if not nodes:
        await edit_or_reply(update, "No nodes are configured.", reply_markup=back_to_user(uuid))
        return True
    name = (user or {}).get("name") or "user"
    await edit_or_reply(update, f"Download a config for <b>{esc(name)}</b>.", reply_markup=node_picker(uuid, nodes))
    return True


async def _download(update: Update, actor: Actor, rest: str) -> bool:
    await answer(update, "Preparing file…")
    try:
        uuid, node_id_s = rest.rsplit(":", 1)
        node_id = int(node_id_s)
    except ValueError:
        await edit_or_reply(update, "Invalid download request.")
        return True
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    nodes = await panel.get_nodes()
    node = next((n for n in nodes if int(n.get("id") or 0) == node_id), None)
    body = await panel.download_ovpn(uuid, node_id)
    message = update.effective_message
    if not body:
        await edit_or_reply(
            update,
            "Could not generate the config. Check that the node is online and the user is active.",
            reply_markup=back_to_user(uuid),
        )
        return True
    filename = f"{(user or {}).get('name') or 'user'}-{(node or {}).get('name') or node_id}.ovpn"
    if message:
        await message.reply_document(document=InputFile(BytesIO(body), filename=filename))
    await edit_or_reply(update, f"Sent <b>{esc(filename)}</b>.", reply_markup=back_to_user(uuid))
    return True
