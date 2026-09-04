# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.api import Panel
from bot.formatters import esc, fmt_uptime, is_expired
from bot.i18n import lang_of, t
from bot.identity import Actor
from bot.keyboards import node_detail, nodes_actions, nodes_list, status_actions
from bot.ui import edit_or_reply


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    info = await panel.get_info()
    settings = await panel.get_settings()
    users = await panel.get_users()
    nodes = await panel.get_nodes()
    if panel.last_status == 0 and not users and not nodes and not info and not settings:
        await edit_or_reply(update, t(lang, "panel_unreachable"))
        return

    active = sum(1 for u in users if u.get("is_active") and not is_expired(u))
    online = sum(1 for u in users if u.get("online") or int(u.get("active_connections") or 0) > 0)
    expired = sum(1 for u in users if is_expired(u))
    disabled = sum(1 for u in users if not u.get("is_active") and not is_expired(u))
    up_nodes = sum(1 for n in nodes if n.get("status"))

    lines = [
        f"<b>{t(lang, 'panel')}</b>",
        t(
            lang,
            "version_uptime",
            version=esc(settings.get("panel_version") or "—"),
            uptime=esc(fmt_uptime(info.get("uptime") or 0)),
        ),
        t(
            lang,
            "cpu_ram_disk",
            cpu=esc(_pct(info.get("cpu"))),
            ram=esc(_pct(info.get("memory_percent"))),
            disk=esc(_pct(info.get("disk_percent"))),
        ),
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
    panel = Panel(actor.token)
    nodes = await panel.get_nodes()
    if not nodes:
        if panel.last_status == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
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
    await edit_or_reply(update, "\n".join(lines).rstrip(), reply_markup=nodes_list(nodes, lang=lang))


async def show_node_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, node_id: int) -> None:
    lang = lang_of(update, context)
    panel = Panel(actor.token)
    nodes = await panel.get_nodes()
    node = next((n for n in nodes if int(n.get("id") or 0) == node_id), None)
    result = await panel.node_status(node_id)
    if not result.get("success"):
        if panel.last_status == 0 or result.get("status") == 0:
            await edit_or_reply(update, t(lang, "panel_unreachable"))
        else:
            await edit_or_reply(update, t(lang, "node_gone"), reply_markup=nodes_actions(lang=lang))
        return
    data = result.get("data") or {}
    info = data.get("node_info") or data
    sessions = data.get("session_diagnostics") or {}
    name = (node or {}).get("name") or f"#{node_id}"
    live = sessions.get("live_count", info.get("live_count", "—"))
    lines = [
        f"<b>{esc(name)}</b>",
        t(
            lang,
            "node_detail_status",
            status=esc(
                t(lang, "status_online") if info.get("openvpn_running", (node or {}).get("status")) else t(lang, "status_offline")
            ),
        ),
        t(lang, "node_detail_cpu", cpu=esc(_pct(info.get("cpu_usage")))),
        t(lang, "node_detail_mem", mem=esc(_pct(info.get("memory_usage")))),
        t(lang, "node_detail_live", live=esc(live)),
        t(lang, "node_detail_version", version=esc(info.get("version") or data.get("version") or "—")),
    ]
    await edit_or_reply(update, "\n".join(lines), reply_markup=node_detail(node_id, lang=lang))


def _pct(value) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "—"
