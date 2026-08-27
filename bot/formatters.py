# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Pure text helpers — no Telegram or HTTP imports."""

from __future__ import annotations

import html
from datetime import date, datetime


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt_bytes(raw) -> str:
    if raw is None:
        return "Unlimited"
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return "—"
    if amount < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} PB"


def parse_expiry(value) -> date | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def expiry_label(value) -> str:
    exp = parse_expiry(value)
    if exp is None:
        return "No expiry"
    # Far-future sentinel used by the panel for "unlimited".
    if exp.year >= 2099:
        return "No expiry"
    delta = (exp - date.today()).days
    if delta < 0:
        return f"Expired {abs(delta)}d ago"
    if delta == 0:
        return "Expires today"
    if delta == 1:
        return "1 day left"
    return f"{delta} days left"


def is_expired(user: dict) -> bool:
    exp = parse_expiry(user.get("expiry_date"))
    if exp is None or exp.year >= 2099:
        return False
    return exp < date.today()


def is_unlimited_expiry(value) -> bool:
    exp = parse_expiry(value)
    return exp is None or exp.year >= 2099


def status_label(user: dict) -> str:
    if is_expired(user):
        return "Expired"
    if user.get("is_active"):
        if user.get("online") or int(user.get("active_connections") or 0) > 0:
            return "Online"
        return "Active"
    return "Disabled"


def usage_line(user: dict) -> str:
    used = fmt_bytes(user.get("used") or 0)
    total = user.get("total")
    if not total:
        return f"{used} / Unlimited"
    pct = 0
    try:
        pct = min(100, int(round(100 * float(user.get("used") or 0) / float(total))))
    except (TypeError, ValueError, ZeroDivisionError):
        pct = 0
    return f"{used} / {fmt_bytes(total)}  ({pct}%)"


def logins_label(user: dict) -> str:
    max_logins = int(user.get("max_logins") or 0)
    active = int(user.get("active_connections") or 0)
    cap = "Unlimited" if max_logins == 0 else str(max_logins)
    return f"{active} / {cap}"


def plan_label(days: int, traffic_gb: int, max_logins: int) -> str:
    d = "No expiry" if days == 0 else f"{days} days"
    t = "Unlimited traffic" if traffic_gb == 0 else f"{traffic_gb} GB"
    m = "Unlimited devices" if max_logins == 0 else f"{max_logins} device" + ("" if max_logins == 1 else "s")
    return f"{d} · {t} · {m}"


def fmt_uptime(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def user_card(user: dict, *, sub_url: str | None = None) -> str:
    name = esc(user.get("name") or "unknown")
    lines = [
        f"<b>{name}</b>",
        "",
        f"Status    {esc(status_label(user))}",
        f"Usage     {esc(usage_line(user))}",
        f"Expiry    {esc(expiry_label(user.get('expiry_date')))}",
        f"Devices   {esc(logins_label(user))}",
    ]
    owner = user.get("owner")
    if owner:
        lines.append(f"Owner     {esc(owner)}")
    if sub_url:
        lines.extend(["", f'<a href="{esc(sub_url)}">Subscription link</a>'])
    return "\n".join(lines)
