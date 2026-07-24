import re
import time
import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.ovmanager import OVManager
from bot.config import config

logger = logging.getLogger(__name__)
api = OVManager()

# {user_id: (state_str, timestamp)} — waiting for plain-text input
USER_STATES = {}
STATE_TTL = 300  # 5 minutes

def _cleanup_states():
    """Remove stale USER_STATES entries older than STATE_TTL seconds."""
    now = time.time()
    stale = [uid for uid, (_, ts) in USER_STATES.items() if now - ts > STATE_TTL]
    for uid in stale:
        del USER_STATES[uid]

def _set_state(uid, state):
    _cleanup_states()
    USER_STATES[uid] = (state, time.time())

def _pop_state(uid):
    _cleanup_states()
    entry = USER_STATES.pop(uid, None)
    return entry[0] if entry else None

PLANS = {
    "bronze": (30, 200, 1),
    "silver": (30, 200, 2),
    "gold": (0, 0, 0),
}

HELP_TEXT = """🤖 <b>OVManager Bot</b>

<b>Users</b>
<code>/n</code> or <code>/new</code> &lt;name&gt; [days] [traffic] [users]
<code>/u</code> or <code>/users</code> [name]
<code>/r</code> or <code>/renew</code> &lt;name&gt; [days] [traffic] [users]
<code>/e</code> or <code>/edit</code> &lt;name&gt; [days] [traffic] [users]

<b>System</b>
<code>/s</code> or <code>/status</code>
<code>/help</code>

0 = unlimited | [] = optional"""

USERS_PER_PAGE = 10


def _parse_args(text: str):
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower() if parts else ""
    if cmd in ("n", "new"):
        mode = "new"
    elif cmd in ("s", "status"):
        mode = "status"
    elif cmd in ("u", "users"):
        mode = "users"
    elif cmd in ("r", "renew"):
        mode = "renew"
    elif cmd in ("e", "edit"):
        mode = "edit"
    elif cmd in ("help",):
        mode = "help"
    else:
        mode = None
    args = parts[1:] if len(parts) > 1 else []
    return mode, args


def _fmt_bytes(b):
    if b is None:
        return "♾️"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _days_remaining(expiry):
    if not expiry:
        return None, "♾️ Unlimited"
    try:
        exp = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    except (ValueError, TypeError):
        return None, "❓ Unknown"
    delta = (exp - date.today()).days
    if delta < 0:
        return delta, f"❌ Expired {abs(delta)}d ago"
    elif delta == 0:
        return delta, "🔥 Expires today"
    elif delta <= 3:
        return delta, f"⚠️ {delta}d left"
    elif delta <= 14:
        return delta, f"⚡ {delta}d left"
    else:
        return delta, f"🔋 {delta}d left"


async def _auth(update: Update) -> bool:
    uid = update.effective_user.id
    admins = await api.get_admins()
    for a in admins:
        if a.get("telegram_id") == uid:
            return True
    settings = await api.get_settings()
    if settings.get("owner_telegram_id") == uid:
        return True
    return False


def _is_owner(uid: int) -> bool:
    s = api._get_settings_from_db()
    return s.get("owner_telegram_id") == uid


def _hub_kb():
    return [
        [InlineKeyboardButton("➕ New", callback_data="hub_new"),
         InlineKeyboardButton("🖥️ Status", callback_data="hub_status")],
        [InlineKeyboardButton("👥 Users", callback_data="users_page_0"),
         InlineKeyboardButton("❓ Help", callback_data="hub_help")],
    ]


async def _hub(update: Update):
    await update.message.reply_text("🏠 OVManager Bot", reply_markup=InlineKeyboardMarkup(_hub_kb()))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if not await _auth(update):
            await update.message.reply_text(
                "⛔ Access Denied\nContact your panel admin to link your Telegram ID."
            )
            return
        mode, args = _parse_args(text)
        if mode is None:
            uid = update.effective_user.id
            state = _pop_state(uid)
            if state:
                if state == "search":
                    return await _handle_users(update, [text])
                if state.startswith("new_"):
                    parts = state.split("_")
                    d, t, mu = int(parts[1]), int(parts[2]), int(parts[3])
                    return await _do_plan_create(update, text, d, t, mu)
            return await _hub(update)
        if mode == "new":
            return await _handle_new(update, args)
        elif mode == "status":
            return await _handle_status(update)
        elif mode == "users":
            return await _handle_users(update, args)
        elif mode == "renew":
            return await _handle_renew(update, args)
        elif mode == "edit":
            return await _handle_edit(update, args)
        elif mode == "help":
            return await _handle_help(update)
    except Exception as e:
        logger.exception("Error in handle_message")
        await update.message.reply_text("⚠️ Internal error, check logs.")


# ────────── HELP ──────────

async def _handle_help(update: Update):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


# ────────── NEW USER ──────────

def _plan_kb(action="plan"):
    return [
        [InlineKeyboardButton("🥉 Bronze  30d / 200GB / 1u", callback_data=f"{action}_bronze")],
        [InlineKeyboardButton("🥈 Silver  30d / 200GB / 2u", callback_data=f"{action}_silver")],
        [InlineKeyboardButton("🥇 Gold  Unlimited", callback_data=f"{action}_gold")],
        [InlineKeyboardButton("✏️ Custom", callback_data=f"{action}_custom")],
    ]


async def _do_plan_create(ctx, name: str, days: int, traffic: int, max_users: int):
    """Execute create_user and send result to ctx (Update or CallbackQuery)."""
    result = await api.create_user(name, days, traffic, max_users)
    if result.get("success"):
        msg = (
            f"✅ New user created\n\n"
            f"Username:  {name}\n"
            f"Plan:      {result['days']} / {result['traffic']} / {result['max_users']}\n"
            f"Expires:   {result['exp']}\n"
            f"Status:    🟢 Active"
        )
        kb = [
            [InlineKeyboardButton("➕ Another", callback_data="hub_new"),
             InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
             InlineKeyboardButton("🏠 Main", callback_data="hub_main")],
        ]
        if hasattr(ctx, "edit_message_text"):
            await ctx.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await ctx.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        err = f"❌ {result.get('msg', 'Failed')}"
        if hasattr(ctx, "edit_message_text"):
            await ctx.edit_message_text(err)
        else:
            await ctx.message.reply_text(err)


async def _handle_new(update: Update, args: list):
    try:
        if not args:
            await update.message.reply_text(
                "📋 New User\nSelect plan:",
                reply_markup=InlineKeyboardMarkup(_plan_kb("plan")),
            )
            return
        name = args[0]
        try:
            days = int(args[1]) if len(args) > 1 else config.default_days
        except ValueError:
            days = config.default_days
        if len(args) > 2:
            try:
                traffic = int(args[2])
            except ValueError:
                traffic = config.default_traffic_gb
        else:
            traffic = config.default_traffic_gb
        if len(args) > 3:
            try:
                max_users = int(args[3])
            except ValueError:
                max_users = config.default_max_users
        else:
            max_users = config.default_max_users
        await _do_plan_create(update, name, days, traffic, max_users)
    except Exception as e:
        logger.exception("Error in _handle_new")
        await update.message.reply_text("⚠️ Failed to create user, check logs.")


# ────────── STATUS ──────────

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
        logger.exception("Error in _handle_status")
        await update.message.reply_text("⚠️ Failed to load status, check logs.")


# ────────── USERS (paginated) ──────────

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
        logger.exception("Error in _handle_users")
        await update.message.reply_text("⚠️ Failed to load users, check logs.")


# ────────── SHOW USER ──────────

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
        used = u.get("used", 0)
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
        logger.exception("Error in _show_user")
        await update.message.reply_text("⚠️ Failed to show user details.")


# ────────── RENEW ──────────

async def _handle_renew(update: Update, args: list):
    try:
        if not args:
            await update.message.reply_text(
                "Usage: /r <name> [days] [traffic] [users]\n"
                "  /r user1          → pick plan\n"
                "  /r user1 30 200 2 → full renew"
            )
            return
        name = args[0]
        if len(args) == 1:
            # Look up user UUID for callback data
            users = await api.get_users()
            uuid = name
            for u in users:
                if u.get("name") == name:
                    uuid = u.get("uuid", name)
                    break
            await update.message.reply_text(
                f"🔄 Renew {name}\nSelect plan:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🥉 Bronze  30d / 200GB / 1u", callback_data=f"renew_{uuid}_bronze")],
                    [InlineKeyboardButton("🥈 Silver  30d / 200GB / 2u", callback_data=f"renew_{uuid}_silver")],
                    [InlineKeyboardButton("🥇 Gold  Unlimited", callback_data=f"renew_{uuid}_gold")],
                    [InlineKeyboardButton("✏️ Custom", callback_data=f"renew_{uuid}_custom")],
                ]),
            )
            return
        days = int(args[1]) if len(args) > 1 and args[1] else 30
        traffic = int(args[2]) if len(args) > 2 and args[2] else 200
        max_users = int(args[3]) if len(args) > 3 and args[3] else 1
        result = await api.renew_user(name, days, traffic, max_users)
        if result.get("success"):
            d_s = "♾️" if days == 0 else f"{days}d"
            t_s = "♾️" if traffic == 0 else f"{traffic}GB"
            m_s = "♾️" if max_users == 0 else str(max_users)
            msg = f"✅ {name} renewed — {d_s} / {t_s} / {m_s}\nExpires: {result['expiry_date']}"
            kb = [[InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
                   InlineKeyboardButton("🏠 Main", callback_data="hub_main")]]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(f"❌ {result.get('msg', 'Failed')}")
    except Exception as e:
        logger.exception("Error in _handle_renew")
        await update.message.reply_text("⚠️ Failed to renew user.")


async def _execute_renew(query, uuid: str, name: str, days: int, traffic: int, max_users: int):
    result = await api.renew_user(name, days, traffic, max_users)
    if result.get("success"):
        d_s = "♾️" if days == 0 else f"{days}d"
        t_s = "♾️" if traffic == 0 else f"{traffic}GB"
        m_s = "♾️" if max_users == 0 else str(max_users)
        msg = f"✅ {name} renewed — {d_s} / {t_s} / {m_s}\nExpires: {result['expiry_date']}"
    else:
        msg = f"❌ {result.get('msg', 'Failed')}"
    kb = [[InlineKeyboardButton("👤 Details", callback_data=f"user_{uuid}"),
           InlineKeyboardButton("🏠 Main", callback_data="hub_main")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))


# ────────── EDIT (interactive) ──────────

async def _handle_edit(update: Update, args: list):
    try:
        if len(args) < 1:
            await update.message.reply_text(
                "Usage: /e <name> [days] [traffic] [users]\n"
                "Example: /e user1 60 500 3\n0 = no change"
            )
            return
        name = args[0]
        data = {}
        if len(args) > 1 and args[1]:
            d = int(args[1])
            if d > 0:
                data["expiry_date"] = date.today() + timedelta(days=d)
        if len(args) > 2 and args[2]:
            t = int(args[2])
            data["total"] = t * 1073741824 if t > 0 else None
        if len(args) > 3 and args[3]:
            mu = int(args[3])
            data["max_logins"] = mu if mu > 0 else 0
        if not data:
            await update.message.reply_text("No changes specified.")
            return
        result = await api.update_user(name, data)
        if result.get("success"):
            parts = []
            if "total" in data:
                parts.append("traffic")
            if "expiry_date" in data:
                parts.append(f"expiry → {data['expiry_date']}")
            if "max_logins" in data:
                parts.append(f"logins → {data['max_logins']}")
            msg = f"✅ {name} edited — {', '.join(parts)}"
            kb = [[InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
                   InlineKeyboardButton("🏠 Main", callback_data="hub_main")]]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(f"❌ {result.get('msg', 'Failed')}")
    except Exception as e:
        logger.exception("Error in _handle_edit")
        await update.message.reply_text("⚠️ Failed to edit user.")


# ────────── CALLBACK ──────────

def _lookup_user_by_uuid_or_name(users, key: str):
    """Find user by uuid or name. Returns user dict or None."""
    for u in users:
        if u.get("uuid") == key or u.get("name") == key:
            return u
    return None


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data

        # ─── Hub ───
        if data == "hub_main":
            await query.edit_message_text("🏠 OVManager Bot", reply_markup=InlineKeyboardMarkup(_hub_kb()))
        elif data == "hub_new":
            await query.edit_message_text(
                "📋 New User\nSelect plan:",
                reply_markup=InlineKeyboardMarkup(_plan_kb("plan")),
            )
        elif data == "hub_status":
            await _handle_status(query)
        elif data == "hub_help":
            await query.edit_message_text(HELP_TEXT, parse_mode="HTML")
        elif data == "hub_search":
            _set_state(update.effective_user.id, "search")
            await query.edit_message_text("🔍 Enter username:")

        # ─── Users paginated ───
        elif data.startswith("users_page_"):
            page = int(data.replace("users_page_", ""))
            users = await api.get_users()
            text, kb = _build_users_page(users, page)
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

        # ─── User detail ───
        elif data.startswith("user_"):
            key = data[len("user_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, key)
            if u:
                await _show_user(query, u)
            else:
                await query.edit_message_text("❌ User not found")
            return

        # ─── New user plans ───
        elif data.startswith("plan_"):
            plan = data.replace("plan_", "")
            if plan == "custom":
                await query.edit_message_text(
                    "✏️ Custom\n\nUse: <code>/n &lt;name&gt; &lt;days&gt; &lt;traffic&gt; &lt;users&gt;</code>\n0 = unlimited",
                    parse_mode="HTML",
                )
                return
            if plan in PLANS:
                d, t, mu = PLANS[plan]
                uname = await api.get_next_username()
                if not uname:
                    if _is_owner(update.effective_user.id):
                        _set_state(update.effective_user.id, f"new_{d}_{t}_{mu}")
                        await query.edit_message_text("No prefix configured. Enter a username:")
                        return
                    await query.edit_message_text(
                        "❌ No prefix configured.\nSet a prefix in Admin settings or use /n <name> directly."
                    )
                    return
                await _do_plan_create(query, uname, d, t, mu)
            else:
                await query.edit_message_text("Unknown plan.")

        # ─── Edit interactive ───
        elif data.startswith("edit_"):
            uuid = data[len("edit_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            if not u:
                await query.edit_message_text("❌ User not found")
                return
            name = u.get("name", uuid)
            await query.edit_message_text(
                f"✏️ Edit {name}\nChoose what to change:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Extend +30d", callback_data=f"ed_days_{uuid}_30"),
                     InlineKeyboardButton("📅 Extend +90d", callback_data=f"ed_days_{uuid}_90")],
                    [InlineKeyboardButton("📊 Traffic 200GB", callback_data=f"ed_traf_{uuid}_200"),
                     InlineKeyboardButton("📊 Traffic 1TB", callback_data=f"ed_traf_{uuid}_1024")],
                    [InlineKeyboardButton("📊 Traffic ♾️", callback_data=f"ed_traf_{uuid}_0")],
                    [InlineKeyboardButton("👥 Logins 1", callback_data=f"ed_log_{uuid}_1"),
                     InlineKeyboardButton("👥 Logins ♾️", callback_data=f"ed_log_{uuid}_0")],
                    [InlineKeyboardButton("⬅️ Back", callback_data=f"user_{uuid}")],
                ]),
            )

        # ─── Edit actions ───
        elif data.startswith("ed_days_"):
            # ed_days_<uuid>_<days>
            try:
                uuid, days_str = data[8:].rsplit("_", 1)
                days = int(days_str)
            except (ValueError, IndexError):
                await query.answer("❌ Invalid data")
                return
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            exp = date(2099, 12, 31) if days == 0 else date.today() + timedelta(days=days)
            r = await api.update_user(name, {"expiry_date": exp})
            s = "♾️" if days == 0 else f"+{days}d"
            await query.edit_message_text(
                f"✅ {name} expiry → {s}" if r.get("success") else f"❌ {r.get('msg')}"
            )
        elif data.startswith("ed_traf_"):
            # ed_traf_<uuid>_<gb>
            try:
                uuid, gb_str = data[8:].rsplit("_", 1)
                gb = int(gb_str)
            except (ValueError, IndexError):
                await query.answer("❌ Invalid data")
                return
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            total = gb * 1073741824 if gb > 0 else None
            r = await api.update_user(name, {"total": total})
            s = "♾️" if gb == 0 else f"{gb}GB"
            await query.edit_message_text(
                f"✅ {name} traffic → {s}" if r.get("success") else f"❌ {r.get('msg')}"
            )
        elif data.startswith("ed_log_"):
            # ed_log_<uuid>_<n>
            try:
                uuid, n_str = data[7:].rsplit("_", 1)
                n = int(n_str)
            except (ValueError, IndexError):
                await query.answer("❌ Invalid data")
                return
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            r = await api.update_user(name, {"max_logins": n})
            s = "♾️" if n == 0 else str(n)
            await query.edit_message_text(
                f"✅ {name} max logins → {s}" if r.get("success") else f"❌ {r.get('msg')}"
            )

        # ─── Renew ───
        elif data.startswith("renew_"):
            rest = data[len("renew_"):]
            # Try to find a plan suffix
            plan = None
            matched_uuid = rest
            for p in list(PLANS.keys()) + ["custom"]:
                if rest.endswith(f"_{p}"):
                    matched_uuid = rest[:-(len(p) + 1)]
                    plan = p
                    break
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, matched_uuid)
            if not u:
                # Fall back: match by name
                for uu in users:
                    if uu.get("name") == matched_uuid:
                        u = uu
                        break
            if not u:
                await query.edit_message_text("❌ User not found")
                return
            name = u.get("name", matched_uuid)
            uuid = u.get("uuid", matched_uuid)
            if plan is None:
                # Plain uuid — show plan picker
                await query.edit_message_text(
                    f"🔄 Renew {name}\nSelect plan:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🥉 Bronze  30d / 200GB / 1u", callback_data=f"renew_{uuid}_bronze")],
                        [InlineKeyboardButton("🥈 Silver  30d / 200GB / 2u", callback_data=f"renew_{uuid}_silver")],
                        [InlineKeyboardButton("🥇 Gold  Unlimited", callback_data=f"renew_{uuid}_gold")],
                        [InlineKeyboardButton("✏️ Custom", callback_data=f"renew_{uuid}_custom")],
                        [InlineKeyboardButton("⬅️ Back", callback_data=f"user_{uuid}")],
                    ]),
                )
                return
            if plan == "custom":
                await query.edit_message_text(
                    f"✏️ Custom renew for {name}\n\n"
                    f"Use: <code>/r {name} &lt;days&gt; &lt;traffic&gt; &lt;users&gt;</code>",
                    parse_mode="HTML",
                )
                return
            d, t, mu = PLANS[plan]
            await _execute_renew(query, uuid, name, d, t, mu)

        # ─── Sub URL ───
        elif data.startswith("sub_"):
            uuid = data[len("sub_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            sub_url = await api.get_sub_url(name)
            if sub_url:
                await query.edit_message_text(
                    f"🔗 Sub URL for {name}:\n<code>{sub_url}</code>",
                    parse_mode="HTML",
                )
            else:
                await query.edit_message_text(
                    "❌ Sub URL not available. Configure subscription settings in panel."
                )

        # ─── Toggle ───
        elif data.startswith("tog_"):
            uuid = data[len("tog_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            result = await api.toggle_user_status(name)
            if result.get("success"):
                s = "🟢 Active" if result["is_active"] else "🔴 Disabled"
                await query.edit_message_text(f"🔄 {name} → {s}")
            else:
                await query.edit_message_text(f"❌ {result.get('msg')}")

        # ─── Config / Download ───
        elif data.startswith("cfg_"):
            # cfg_<uuid> — use UUID to avoid username/underscore issues
            uuid = data[4:]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            nodes = await api.get_nodes()
            kb = [[InlineKeyboardButton(n["name"], callback_data=f"dl_{uuid}_{n['name']}")] for n in nodes]
            if len(nodes) > 1:
                kb.append([InlineKeyboardButton("📦 All", callback_data=f"dlall_{uuid}")])
            kb.append([InlineKeyboardButton("⬅️ Back", callback_data=f"user_{uuid}")])
            await query.edit_message_text(
                f"Download config for {name}:", reply_markup=InlineKeyboardMarkup(kb)
            )

        elif data.startswith("dlall_"):
            uuid = data[len("dlall_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            await query.edit_message_text(f"⏳ Downloading configs for {name}...")
            nodes = await api.get_nodes()
            sent = 0
            for n in nodes:
                content = await api.download_config(name, n["name"])
                if content:
                    fn = f"{name}-{n['name']}.ovpn"
                    await query.message.reply_document(
                        document=content.encode() if isinstance(content, str) else content,
                        filename=fn,
                    )
                    sent += 1
            if sent == 0:
                await query.message.reply_text("❌ No configs generated. Are nodes online?")
            else:
                await query.message.reply_text(f"✅ Sent {sent} config(s).")

        elif data.startswith("dl_"):
            # dl_<uuid>_<nodename> — find node by matching known node names from end
            rest = data[3:]
            nodes = await api.get_nodes()
            node_names = sorted((n["name"] for n in nodes), key=len, reverse=True)
            matched_node = None
            remaining = rest
            for nn in node_names:
                if rest.endswith(f"_{nn}"):
                    matched_node = nn
                    remaining = rest[: -(len(nn) + 1)]
                    break
            if matched_node is None:
                await query.edit_message_text("❌ Invalid download.")
                return
            uuid = remaining
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            await query.edit_message_text(
                f"⏳ Downloading {matched_node} config for {name}..."
            )
            content = await api.download_config(name, matched_node)
            if content:
                fn = f"{name}-{matched_node}.ovpn"
                await query.message.reply_document(
                    document=content.encode() if isinstance(content, str) else content,
                    filename=fn,
                )
            else:
                await query.message.reply_text(f"❌ Failed — is {matched_node} online?")

        # ─── Delete ───
        elif data.startswith("del_"):
            uuid = data[len("del_"):]
            users = await api.get_users()
            u = _lookup_user_by_uuid_or_name(users, uuid)
            name = u.get("name", uuid) if u else uuid
            result = await api.delete_user(name)
            if result.get("success"):
                await query.edit_message_text(f"🗑️ {name} deleted.")
            else:
                await query.edit_message_text(f"❌ {result.get('msg', 'Delete failed')}")

    except Exception as e:
        logger.exception("Error in handle_callback")
        await query.edit_message_text("⚠️ Error, check logs.")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _auth(update):
        await update.message.reply_text("⛔ Access Denied")
        return
    await _hub(update)