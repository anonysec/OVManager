# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Pure text helpers — no Telegram or HTTP imports."""

from __future__ import annotations

import html
from datetime import date, datetime

from bot.i18n import DEFAULT_LANG, t


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt_bytes(raw, *, lang: str = DEFAULT_LANG) -> str:
    if raw is None:
        return t(lang, "unlimited")
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


def expiry_label(value, *, lang: str = DEFAULT_LANG) -> str:
    exp = parse_expiry(value)
    if exp is None:
        return t(lang, "no_expiry")
    # Far-future sentinel used by the panel for "unlimited".
    if exp.year >= 2099:
        return t(lang, "no_expiry")
    delta = (exp - date.today()).days
    if delta < 0:
        return t(lang, "expired_ago", days=abs(delta))
    if delta == 0:
        return t(lang, "expires_today")
    if delta == 1:
        return t(lang, "days_left_one")
    return t(lang, "days_left", days=delta)


def is_expired(user: dict) -> bool:
    exp = parse_expiry(user.get("expiry_date"))
    if exp is None or exp.year >= 2099:
        return False
    return exp < date.today()


def is_unlimited_expiry(value) -> bool:
    exp = parse_expiry(value)
    return exp is None or exp.year >= 2099


def status_rank(user: dict) -> int:
    if is_expired(user):
        return 3
    if not user.get("is_active"):
        return 2
    if user.get("online") or int(user.get("active_connections") or 0) > 0:
        return 0
    return 1


def status_label(user: dict, *, lang: str = DEFAULT_LANG) -> str:
    if is_expired(user):
        return t(lang, "status_expired")
    if user.get("is_active"):
        if user.get("online") or int(user.get("active_connections") or 0) > 0:
            return t(lang, "status_online")
        return t(lang, "status_active")
    return t(lang, "status_disabled")


def usage_line(user: dict, *, lang: str = DEFAULT_LANG) -> str:
    used = fmt_bytes(user.get("used") or 0, lang=lang)
    total = user.get("total")
    if not total:
        return t(lang, "usage_unlimited", used=used)
    pct = 0
    try:
        pct = min(100, int(round(100 * float(user.get("used") or 0) / float(total))))
    except (TypeError, ValueError, ZeroDivisionError):
        pct = 0
    return t(lang, "usage_quota", used=used, total=fmt_bytes(total, lang=lang), pct=pct)


def logins_label(user: dict, *, lang: str = DEFAULT_LANG) -> str:
    max_logins = int(user.get("max_logins") or 0)
    active = int(user.get("active_connections") or 0)
    cap = t(lang, "unlimited") if max_logins == 0 else str(max_logins)
    return f"{active} / {cap}"


def plan_label(days: int, traffic_gb: int, max_logins: int, *, lang: str = DEFAULT_LANG) -> str:
    d = t(lang, "no_expiry") if days == 0 else t(lang, "plan_days", days=days)
    traffic = t(lang, "plan_traffic_unlim") if traffic_gb == 0 else t(lang, "plan_traffic", gb=traffic_gb)
    if max_logins == 0:
        devices = t(lang, "plan_devices_unlim")
    elif max_logins == 1:
        devices = t(lang, "plan_devices_one")
    else:
        devices = t(lang, "plan_devices", n=max_logins)
    return f"{d} · {traffic} · {devices}"


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


def user_card(user: dict, *, sub_url: str | None = None, lang: str = DEFAULT_LANG) -> str:
    name = esc(user.get("name") or t(lang, "card_unknown"))
    lines = [
        f"<b>{name}</b>",
        "",
        f"{t(lang, 'card_status')}    {esc(status_label(user, lang=lang))}",
        f"{t(lang, 'card_usage')}     {esc(usage_line(user, lang=lang))}",
        f"{t(lang, 'card_expiry')}    {esc(expiry_label(user.get('expiry_date'), lang=lang))}",
        f"{t(lang, 'card_devices')}   {esc(logins_label(user, lang=lang))}",
    ]
    owner = user.get("owner")
    if owner:
        lines.append(f"{t(lang, 'card_owner')}     {esc(owner)}")
    if sub_url:
        lines.extend(["", f'<a href="{esc(sub_url)}">{t(lang, "card_sub")}</a>'])
    return "\n".join(lines)
