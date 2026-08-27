# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc, fmt_uptime, is_expired
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import nodes_actions, status_actions
from bot.ui import edit_or_reply


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    info = await panel.get_info()
    settings = await panel.get_settings()
    users = await panel.get_users()
    nodes = await panel.get_nodes()

    active = sum(1 for u in users if u.get("is_active") and not is_expired(u))
    online = sum(1 for u in users if u.get("online") or int(u.get("active_connections") or 0) > 0)
    expired = sum(1 for u in users if is_expired(u))
    disabled = sum(1 for u in users if not u.get("is_active") and not is_expired(u))
    up_nodes = sum(1 for n in nodes if n.get("status"))

    lines = [
        f"<b>{t(lang, 'panel')}</b>",
        t(lang, "version_uptime", version=esc(settings.get("panel_version") or "—"), uptime=esc(fmt_uptime(info.get("uptime") or 0))),
        t(lang, "cpu_ram_disk", cpu=esc(_pct(info.get("cpu"))), ram=esc(_pct(info.get("memory_percent"))), disk=esc(_pct(info.get("disk_percent")))),
        "",
        f"<b>{t(lang, 'btn_users')}</b>",
        t(lang, "users_stats", total=len(users), active=active, online=online),
        t(lang, "users_extra", disabled=disabled, expired=expired),
        "",
        f"<b>{t(lang, 'btn_nodes')}</b>",
        t(lang, "nodes_stats", up=up_nodes, total=len(nodes)) if nodes else t(lang, "nodes_none"),
    ]
    for node in nodes[:8]:
        mark = t(lang, "node_up") if node.get("status") else t(lang, "node_down")
        addr = node.get("address") or "—"
        port = node.get("ovpn_port") or node.get("port") or ""
        where = f"{addr}:{port}" if port else addr
        lines.append(f"· {esc(node.get('name'))}  {mark}  {esc(where)}")
    await edit_or_reply(update, "\n".join(lines), reply_markup=status_actions(lang=lang))


async def show_nodes(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    nodes = await Panel(actor.token).get_nodes()
    if not nodes:
        await edit_or_reply(update, t(lang, "nodes_none_yet"), reply_markup=nodes_actions(lang=lang))
        return
    lines = [t(lang, "nodes_header", count=len(nodes)), ""]
    for node in nodes:
        mark = t(lang, "status_online") if node.get("status") else t(lang, "status_offline")
        proto = (node.get("protocol") or "tcp").upper()
        addr = node.get("address") or "—"
        port = node.get("ovpn_port") or ""
        lines.append(t(lang, "node_line", name=esc(node.get("name")), mark=mark))
        lines.append(f"{esc(addr)}:{esc(port)}  {esc(proto)}")
        lines.append("")
    await edit_or_reply(update, "\n".join(lines).rstrip(), reply_markup=nodes_actions(lang=lang))


def _pct(value) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "—"
