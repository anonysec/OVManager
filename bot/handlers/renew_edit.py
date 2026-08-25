# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import logging
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from bot.handlers.common import _safe_handler, api


@_safe_handler
async def _handle_renew(update: Update, args: list):
    try:
        if not args:
            await update.message.reply_text(
                "Usage: /r <name> [days] [traffic] [users]\n  /r user1          → pick plan\n  /r user1 30 200 2 → full renew"
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
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🥉 Bronze  30d / 200GB / 1u", callback_data=f"renew_{uuid}_bronze")],
                        [InlineKeyboardButton("🥈 Silver  30d / 200GB / 2u", callback_data=f"renew_{uuid}_silver")],
                        [InlineKeyboardButton("🥇 Gold  Unlimited", callback_data=f"renew_{uuid}_gold")],
                        [InlineKeyboardButton("✏️ Custom", callback_data=f"renew_{uuid}_custom")],
                    ]
                ),
            )
            return
        # Days validation
        try:
            days = int(args[1]) if len(args) > 1 and args[1] else 30
            if not (0 <= days <= 3650):
                raise ValueError("Days out of range (0-3650)")
        except ValueError as e:
            await update.message.reply_text(f"❌ Invalid days: {e}. Must be between 0 and 3650.")
            return

        # Traffic validation
        try:
            traffic = int(args[2]) if len(args) > 2 and args[2] else 200
            if not (0 <= traffic <= 100000):
                raise ValueError("Traffic out of range (0-100000 GB)")
        except ValueError as e:
            await update.message.reply_text(f"❌ Invalid traffic: {e}. Must be between 0 and 100000.")
            return

        # Max users validation
        try:
            max_users = int(args[3]) if len(args) > 3 and args[3] else 1
            if not (0 <= max_users <= 100):
                raise ValueError("Max users out of range (0-100)")
        except ValueError as e:
            await update.message.reply_text(f"❌ Invalid max users: {e}. Must be between 0 and 100.")
            return
        result = await api.renew_user(name, days, traffic, max_users)
        if result.get("success"):
            d_s = "♾️" if days == 0 else f"{days}d"
            t_s = "♾️" if traffic == 0 else f"{traffic}GB"
            m_s = "♾️" if max_users == 0 else str(max_users)
            msg = f"✅ {name} renewed — {d_s} / {t_s} / {m_s}\nExpires: {result['expiry_date']}"
            kb = [
                [
                    InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
                    InlineKeyboardButton("🏠 Main", callback_data="hub_main"),
                ]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(f"❌ {result.get('msg', 'Failed')}")
    except Exception:
        logger = logging.getLogger(__name__)
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
    kb = [
        [
            InlineKeyboardButton("👤 Details", callback_data=f"user_{uuid}"),
            InlineKeyboardButton("🏠 Main", callback_data="hub_main"),
        ]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))


@_safe_handler
async def _handle_edit(update: Update, args: list):
    try:
        if len(args) < 1:
            await update.message.reply_text(
                "Usage: /e <name> [days] [traffic] [users]\nExample: /e user1 60 500 3\n0 = no change"
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
            kb = [
                [
                    InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
                    InlineKeyboardButton("🏠 Main", callback_data="hub_main"),
                ]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(f"❌ {result.get('msg', 'Failed')}")
    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception("Error in _handle_edit")
        await update.message.reply_text("⚠️ Failed to edit user.")
