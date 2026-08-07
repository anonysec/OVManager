from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from bot.handlers.common import api, _fmt_bytes, _days_remaining, _safe_handler

USERS_PER_PAGE = 10


def _is_expired(u):
    exp = u.get("expiry_date")
    if not exp:
        return False
    try:
        d = date.fromisoformat(exp) if isinstance(exp, str) else exp
        return d < date.today()
    except (ValueError, TypeError):
        return False


def _build_users_page(users, page):
    total = len(users)
    start = page * USERS_PER_PAGE
    end = min(start + USERS_PER_PAGE, total)
    page_users = users[start:end]
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    lines = [f"👥 Users ({total}) — pg {page+1}/{total_pages}", ""]
    for i, u in enumerate(page_users, start + 1):
        name = u.get("name", "?")
        expired = _is_expired(u)
        icon = "🟢" if (u.get("is_active") and not expired) else ("❌" if expired else "🔴")
        dr = _days_remaining(u.get("expiry_date"))[1]
        lines.append(f"{i}. {icon} {name} — {dr}")
    user_row = [InlineKeyboardButton(u.get("name", "?"), callback_data=f"user_{u['uuid'] or u['name']}")
                for u in page_users]
    nav = []
    row = []
    for b in user_row:
        row.append(b)
        if len(row) == 2:
            nav.append(row)
            row = []
    if row:
        nav.append(row)
    page_btns = []
    if page > 0:
        page_btns.append(InlineKeyboardButton("◀️ Prev", callback_data=f"users_page_{page-1}"))
    if end < total:
        page_btns.append(InlineKeyboardButton("Next ▶️", callback_data=f"users_page_{page+1}"))
    if page_btns:
        nav.append(page_btns)
    nav.append([InlineKeyboardButton("➕ New", callback_data="hub_new"),
                InlineKeyboardButton("🔍 Search", callback_data="hub_search"),
                InlineKeyboardButton("🏠 Main", callback_data="hub_main")])
    return "\n".join(lines), nav


@_safe_handler
async def _handle_users(update: Update, args: list):
    try:
        users = await api.get_users()
        if args:
            name = args[0]
            for u in users:
                if u.get("name") == name:
                    return await _show_user(update, u)
            name_lower = name.lower()
            for u in users:
                if u.get("name", "").lower().startswith(name_lower):
                    return await _show_user(update, u)
            await update.message.reply_text(f"❌ User '{name}' not found")
            return
        if not users:
            await update.message.reply_text("No users yet.")
            return
        text, kb = _build_users_page(users, 0)
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Error in _handle_users")
        await update.message.reply_text("⚠️ Failed to load users, check logs.")


@_safe_handler
async def _show_user(update: Update, u: dict):
    try:
        name = u.get("name", "?")
        uuid = u.get("uuid", name)
        expired = _is_expired(u)
        if expired:
            status_icon = "❌ Expired"
        elif u.get("is_active"):
            status_icon = "🟢 Active"
        else:
            status_icon = "🔴 Disabled"
        total = u.get("total")
        used = u.get("used") or 0
        total_s = _fmt_bytes(total) if total else "♾️ Unlimited"
        used_s = _fmt_bytes(used)
        pct = f" ({used / total * 100:.0f}%)" if total and total > 0 else ""
        max_l = u.get("max_logins", 1)
        max_s = "♾️" if max_l == 0 else str(max_l)
        dr = _days_remaining(u.get("expiry_date"))[1]
        # Get sub URL
        sub_url = await api.get_sub_url(name)
        msg = (
            f"👤 <b>{name}</b>\n\n"
            f"Status:  {status_icon}\n"
            f"Usage:   {used_s} / {total_s}{pct}\n"
            f"Expiry:  {dr}\n"
            f"Logins:  {max_s}"
        )
        if sub_url:
            msg += f"\n<a href=\"{sub_url}\">🔗 Sub</a>"
        kb = [
            [InlineKeyboardButton("📋 Config", callback_data=f"cfg_{uuid}"),
             InlineKeyboardButton("🔄 Renew", callback_data=f"renew_{uuid}")],
            [InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{uuid}"),
             InlineKeyboardButton("🔄 Toggle", callback_data=f"tog_{uuid}")],
            [InlineKeyboardButton("🔗 Copy Sub URL", callback_data=f"sub_{uuid}"),
             InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{uuid}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="users_page_0"),
             InlineKeyboardButton("🏠 Main", callback_data="hub_main")],
        ]
        await update.message.reply_text(msg, parse_mode="HTML",
                                        reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Error in _show_user")
        await update.message.reply_text("⚠️ Failed to show user details.")
