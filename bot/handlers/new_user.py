# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from bot.config import config
from bot.handlers.common import _safe_handler, api


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
            [
                InlineKeyboardButton("➕ Another", callback_data="hub_new"),
                InlineKeyboardButton("👤 Details", callback_data=f"user_{name}"),
                InlineKeyboardButton("🏠 Main", callback_data="hub_main"),
            ],
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


@_safe_handler
async def _handle_new(update: Update, args: list):
    try:
        if not args:
            await update.message.reply_text(
                "📋 New User\nSelect plan:",
                reply_markup=InlineKeyboardMarkup(_plan_kb("plan")),
            )
            return
        name = args[0]
        # Days validation
        try:
            days = int(args[1]) if len(args) > 1 else config.default_days
            if not (0 <= days <= 3650):
                raise ValueError("Days out of range (0-3650)")
        except ValueError as e:
            await update.message.reply_text(f"❌ Invalid days: {e}. Must be between 0 and 3650.")
            return

        # Traffic validation
        if len(args) > 2:
            try:
                traffic = int(args[2])
                if not (0 <= traffic <= 100000):
                    raise ValueError("Traffic out of range (0-100000 GB)")
            except ValueError as e:
                await update.message.reply_text(f"❌ Invalid traffic: {e}. Must be between 0 and 100000.")
                return
        else:
            traffic = config.default_traffic_gb

        # Max users validation
        if len(args) > 3:
            try:
                max_users = int(args[3])
                if not (0 <= max_users <= 100):
                    raise ValueError("Max users out of range (0-100)")
            except ValueError as e:
                await update.message.reply_text(f"❌ Invalid max users: {e}. Must be between 0 and 100.")
                return
        else:
            max_users = config.default_max_users
        await _do_plan_create(update, name, days, traffic, max_users)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Error in _handle_new")
        await update.message.reply_text("⚠️ Failed to create user, check logs.")
