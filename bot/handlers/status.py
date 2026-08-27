# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc, fmt_uptime, is_expired
from bot.identity import Actor
from bot.keyboards import nodes_actions, status_actions
from bot.ui import edit_or_reply


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
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
        "<b>Panel</b>",
        f"Version {esc(settings.get('panel_version') or '—')}  ·  up {esc(fmt_uptime(info.get('uptime') or 0))}",
        f"CPU {esc(_pct(info.get('cpu')))}  ·  RAM {esc(_pct(info.get('memory_percent')))}  ·  Disk {esc(_pct(info.get('disk_percent')))}",
        "",
        "<b>Users</b>",
        f"{len(users)} total  ·  {active} active  ·  {online} online",
        f"{disabled} disabled  ·  {expired} expired",
        "",
        "<b>Nodes</b>",
        f"{up_nodes} online / {len(nodes)} configured" if nodes else "No nodes configured.",
    ]
    for node in nodes[:8]:
        mark = "up" if node.get("status") else "down"
        addr = node.get("address") or "—"
        port = node.get("ovpn_port") or node.get("port") or ""
        where = f"{addr}:{port}" if port else addr
        lines.append(f"· {esc(node.get('name'))}  {mark}  {esc(where)}")
    await edit_or_reply(update, "\n".join(lines), reply_markup=status_actions())


async def show_nodes(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    nodes = await Panel(actor.token).get_nodes()
    if not nodes:
        await edit_or_reply(update, "No nodes configured yet.", reply_markup=nodes_actions())
        return
    lines = [f"<b>Nodes</b>  ·  {len(nodes)}", ""]
    for node in nodes:
        mark = "Online" if node.get("status") else "Offline"
        proto = (node.get("protocol") or "tcp").upper()
        addr = node.get("address") or "—"
        port = node.get("ovpn_port") or ""
        lines.append(f"<b>{esc(node.get('name'))}</b>  —  {mark}")
        lines.append(f"{esc(addr)}:{esc(port)}  {esc(proto)}")
        lines.append("")
    await edit_or_reply(update, "\n".join(lines).rstrip(), reply_markup=nodes_actions())


def _pct(value) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "—"
