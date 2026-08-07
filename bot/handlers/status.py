from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot.handlers.common import api, _safe_handler


@_safe_handler
async def _handle_status(update: Update):
    try:
        info = await api.get_status()
        nodes = await api.get_nodes()
        users = await api.get_users()
        active = sum(1 for u in users if u.get("is_active"))
        suspended = sum(1 for u in users if not u.get("is_active"))
        lines = ["🖥️ Server Status", ""]
        lines.append("Panel:     🟢 Online")
        if info:
            uptime = info.get("uptime", 0)
            d = uptime // 86400
            lines.append(f"Uptime:    {d}d")
        lines.append(f"Nodes:     {len(nodes)}")
        lines.append(f"Users:     🟢 {active}  🔴 {suspended}")
        lines.append("")
        for n in nodes:
            st = "🟢" if n.get("status") else "🔴"
            lines.append(f"── {n.get('name', '?')} ──")
            lines.append(f"  {st}  {n.get('address', '?')}")
        kb = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="hub_status"),
             InlineKeyboardButton("👥 Users", callback_data="users_page_0"),
             InlineKeyboardButton("🏠 Main", callback_data="hub_main")],
        ]
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Error in _handle_status")
        await update.message.reply_text("⚠️ Failed to load status, check logs.")
