import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.handlers.common import (
    api, _get_plans, _set_state, _pop_state, _periodic_cleanup,
    _check_rate_limit, _hub_kb, _hub, _auth, _safe_handler,
    _parse_args, _is_owner, HELP_TEXT,
)
from bot.handlers.users import _build_users_page, _show_user, _is_expired
from bot.handlers.status import _handle_status
from bot.handlers.renew_edit import _execute_renew
from bot.handlers.new_user import _plan_kb, _do_plan_create, _handle_new

logger = logging.getLogger(__name__)


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
            return
        elif data == "hub_new":
            await query.edit_message_text(
                "📋 New User\nSelect plan:",
                reply_markup=InlineKeyboardMarkup(_plan_kb("plan")),
            )
            return
        elif data == "hub_status":
            await _handle_status(query)
            return
        elif data == "hub_help":
            await query.edit_message_text(HELP_TEXT, parse_mode="HTML")
            return
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
            if plan in _get_plans():
                d, t, mu = _get_plans()[plan]
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
            for p in list(_get_plans().keys()) + ["custom"]:
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
            d, t, mu = _get_plans()[plan]
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
    finally:
        _periodic_cleanup()
