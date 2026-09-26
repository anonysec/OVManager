from __future__ import annotations

from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.callbacks import action, parse_callback
from bot.formatters import esc
from bot.handlers.access import ensure_panel_ok, fetch_user
from bot.handlers.users import show_user
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import after_delete, back_to_user, confirm_delete, extend_actions, node_picker
from bot.ui import answer, edit_or_reply

GB = 1073741824


async def dispatch_action(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, data: str) -> bool:
    """Route ``"<prefix>:<arg>"`` callbacks via the action registry.

    Returns False when no prefix matches so the caller falls through to
    the next dispatcher (edit flow, user view, …).
    """
    fn, kwargs, arg = parse_callback(data)
    if fn is None:
        return False
    return await fn(update, context, actor, arg, **kwargs)


@action("ext")
async def _show_extend(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    name = user.get("name") or t(lang, "this_user")
    await edit_or_reply(update, t(lang, "extend_title", name=esc(name)), reply_markup=extend_actions(uuid, lang=lang))
    return True


@action("e30", days=30)
@action("e90", days=90)
@action("eb10", bytes_=10 * GB)
@action("eb100", bytes_=100 * GB)
async def _extend(
    update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str, *, days: int = 0, bytes_: int = 0
) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "updating"))
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    result = await panel.extend_user(uuid, days=days, bytes_=bytes_)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
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


@action("rst")
async def _reset(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "resetting"))
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    result = await panel.reset_usage(uuid)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
    msg = t(lang, "reset_ok") if result.get("success") else (result.get("msg") or t(lang, "reset_fail"))
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid, lang=lang))
    return True


@action("tog")
async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    new_status = not bool(user.get("is_active"))
    result = await panel.set_status(uuid, user.get("name") or "", new_status)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
    if not result.get("success"):
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "status_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
        return True
    await show_user(update, context, actor, uuid)
    return True


@action("dis")
async def _disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "disconnecting"))
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    result = await panel.disconnect(uuid)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
    msg = t(lang, "disconnect_ok") if result.get("success") else (result.get("msg") or t(lang, "disconnect_fail"))
    await edit_or_reply(update, esc(msg), reply_markup=back_to_user(uuid, lang=lang))
    return True


@action("del")
async def _ask_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await fetch_user(update, panel, uuid, lang)
    if not user:
        return True
    name = user.get("name") or t(lang, "this_user")
    await edit_or_reply(
        update,
        t(lang, "delete_ask", name=esc(name)),
        reply_markup=confirm_delete(uuid, lang=lang),
    )
    return True


@action("okd")
async def _delete(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "deleting"))
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    name = (user or {}).get("name") or t(lang, "this_user")
    result = await panel.delete_user(uuid)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
    if result.get("success"):
        await edit_or_reply(
            update,
            t(lang, "delete_ok", name=esc(name)),
            reply_markup=after_delete(uuid, name=esc(name), lang=lang),
        )
    else:
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "delete_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
    return True


@action("undo")
async def _undo_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update, t(lang, "restoring"))
    result = await Panel(actor.token).restore_user(uuid)
    if not await ensure_panel_ok(update, context, actor, result):
        return True
    if result.get("success"):
        await edit_or_reply(
            update,
            t(lang, "restored_ok"),
            reply_markup=back_to_user(uuid, lang=lang),
        )
    else:
        await edit_or_reply(
            update,
            esc(result.get("msg") or t(lang, "restore_fail")),
            reply_markup=back_to_user(uuid, lang=lang),
        )
    return True


@action("sub")
async def _sub(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    if not user and panel.last_status == 0:
        await edit_or_reply(update, t(lang, "panel_unreachable"))
        return True
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


@action("cfg")
async def _cfg(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, uuid: str) -> bool:
    lang = lang_of(update, context)
    await answer(update)
    panel = Panel(actor.token)
    user = await panel.get_user(uuid=uuid)
    nodes = await panel.get_nodes()
    if not nodes:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(update, t(lang, "no_nodes"), reply_markup=back_to_user(uuid, lang=lang))
        return True
    name = (user or {}).get("name") or t(lang, "this_user")
    await edit_or_reply(
        update,
        t(lang, "cfg_pick", name=esc(name)),
        reply_markup=node_picker(uuid, nodes, lang=lang),
    )
    return True


@action("dl")
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
    if not user and panel.last_status == 0:
        await edit_or_reply(update, t(lang, "panel_unreachable"))
        return True
    node = next((n for n in nodes if int(n.get("id") or 0) == node_id), None)
    body = await panel.download_ovpn(uuid, node_id)
    message = update.effective_message
    if not body:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(update, t(lang, "dl_fail"), reply_markup=back_to_user(uuid, lang=lang))
        return True
    filename = f"{(user or {}).get('name') or 'user'}-{(node or {}).get('name') or node_id}.ovpn"
    filename = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in filename)
    if message:
        try:
            await message.reply_document(document=InputFile(BytesIO(body), filename=filename))
        except Exception:
            await edit_or_reply(update, t(lang, "dl_fail"), reply_markup=back_to_user(uuid, lang=lang))
            return True
    await edit_or_reply(update, t(lang, "dl_sent", filename=esc(filename)), reply_markup=back_to_user(uuid, lang=lang))
    return True
