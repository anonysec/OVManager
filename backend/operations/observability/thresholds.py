"""Threshold alerts: days-left, usage %, and node CPU (D2).

Fed by the 5-minute metrics collector — the same job that already runs the
node-down check — so no second scheduler exists for this. Every evaluation
recomputes the conditions from the database: ``/notifications/`` reads
:func:`threshold_items` too, which makes the inbox rows current by
construction.

Telegram needs a de-dupe on top: a condition that persists must page once,
not every five minutes. The per-type signature kept in :data:`_notified` is
the threshold equivalent of ``node_alerts._alerted_down`` — recorded only
after Telegram accepts the message, dropped as soon as the condition clears.
That gives exactly the required behaviour: second run silent, a failed send
retried next tick, and a cleared-then-returned condition announced again.

Node-down is not repeated here: ``node_alerts`` already owns that event,
toggled by ``settings.notify_node_down``. The expiry event is gated by
``settings.notify_expiry`` (same switch as the daily summary), usage and CPU
carry their own ``alert_usage_enabled`` / ``alert_cpu_enabled`` flags.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.migrations.schema import table_names
from backend.logger import logger
from backend.operations.observability.notifier import send_telegram

DEFAULT_DAYS_LEFT = 3
DEFAULT_USAGE_PCT = 80
DEFAULT_CPU_PCT = 85
SUMMARY_LIMIT = 10  # titles per message; the rest collapse into "+N more"

# Threshold type -> signature of the last condition set Telegram accepted.
_notified: dict[str, str] = {}

# Quota warnings already reach the inbox from the client's own derivation
# (with their "Quota warnings (80%+)" pref), so usage rows are Telegram-only.
INBOX_TYPES = frozenset({"threshold_expiry", "threshold_cpu"})


def _clamp(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _latest_node_cpu(db: Session) -> list[tuple[int, str, float]]:
    """Latest recorded CPU per node; empty when the snapshot table is absent."""
    try:
        if "node_health_snapshots" not in table_names(db):
            return []
        rows = db.execute(
            text(
                "SELECT node_id, node_name, cpu FROM node_health_snapshots "
                "WHERE id IN (SELECT MAX(id) FROM node_health_snapshots GROUP BY node_id)"
            )
        ).fetchall()
        return [(int(r[0]), str(r[1] or f"node-{r[0]}"), float(r[2] or 0)) for r in rows]
    except Exception as exc:
        logger.error("Threshold CPU lookup failed (%s)", type(exc).__name__)
        return []


def threshold_items(db: Session) -> list[dict]:
    """One dict per tripped threshold: ``id``, ``type``, ``level``, ``title``, ``target``.

    Disabled events contribute nothing, so switching an event off also drops
    its inbox rows and its Telegram de-dupe state (the next run forgets it).
    """
    settings = crud.get_settings(db)
    items: list[dict] = []

    expiry_on = bool(getattr(settings, "notify_expiry", True))
    days = _clamp(getattr(settings, "alert_days_left", DEFAULT_DAYS_LEFT), DEFAULT_DAYS_LEFT, 0, 365)
    usage_on = bool(getattr(settings, "alert_usage_enabled", True))
    usage_limit = _clamp(getattr(settings, "alert_usage_pct", DEFAULT_USAGE_PCT), DEFAULT_USAGE_PCT, 1, 100)
    cpu_on = bool(getattr(settings, "alert_cpu_enabled", True))
    cpu_limit = _clamp(getattr(settings, "alert_cpu_pct", DEFAULT_CPU_PCT), DEFAULT_CPU_PCT, 1, 100)

    if expiry_on:
        today = datetime.now(UTC).date()
        deadline = today + timedelta(days=days)
        for user in crud.get_all_users(db):
            if not getattr(user, "is_active", False):
                continue
            expiry = getattr(user, "expiry_date", None)
            if expiry is None or not (today <= expiry <= deadline):
                continue
            left = (expiry - today).days
            items.append(
                {
                    "id": f"expiry:{user.uuid or user.name}",
                    "type": "threshold_expiry",
                    "level": "warning",
                    "target": user.name,
                    "title": f"{user.name} expires in {left} day(s)",
                }
            )

    if usage_on:
        for user in crud.get_all_users(db):
            if not getattr(user, "is_active", False):
                continue
            total = getattr(user, "total", None)
            if not total:
                continue  # no quota (NULL = unlimited) has no percentage
            pct = (getattr(user, "used", None) or 0) / total * 100
            if pct < usage_limit:
                continue
            items.append(
                {
                    "id": f"usage:{user.uuid or user.name}",
                    "type": "threshold_usage",
                    "level": "danger" if pct >= 100 else "warning",
                    "target": user.name,
                    "title": f"{user.name} at {round(pct)}% of quota (warn limit {usage_limit}%)",
                }
            )

    if cpu_on:
        for node_id, name, cpu in _latest_node_cpu(db):
            if cpu < cpu_limit:
                continue
            items.append(
                {
                    "id": f"cpu:{node_id}",
                    "type": "threshold_cpu",
                    "level": "warning",
                    "target": name,
                    "title": f"Node {name} CPU at {round(cpu)}% (warn limit {cpu_limit}%)",
                }
            )

    return items


def _message(group: list[dict]) -> str:
    """One compact line per threshold type: ``"Threshold alert: a; b (+3 more)"``."""
    titles = [item["title"] for item in group]
    shown = titles[:SUMMARY_LIMIT]
    extra = len(titles) - len(shown)
    body = "; ".join(shown) + (f" (+{extra} more)" if extra else "")
    return f"Threshold alert: {body}"


def check_threshold_alerts(db: Session) -> int:
    """Send Telegram for every threshold type that just tripped (or changed).

    Returns the number of messages sent. A type whose condition set matches
    the last accepted signature stays silent; state is only written after
    Telegram says yes, so failures retry on the next tick.
    """
    sent = 0
    try:
        groups: dict[str, list[dict]] = {}
        for item in threshold_items(db):
            groups.setdefault(item["type"], []).append(item)

        for kind, group in groups.items():
            # ids + levels: an unchanged set stays silent, an escalation
            # (warning -> danger) is a change worth one more page.
            signature = "|".join(sorted(f"{item['id']}:{item['level']}" for item in group))
            if _notified.get(kind) == signature:
                continue
            if send_telegram(_message(group), db=db):
                _notified[kind] = signature
                sent += 1

        for kind in [k for k in _notified if k not in groups]:
            del _notified[kind]  # condition cleared: announce again if it returns
    except Exception as exc:
        logger.error("Threshold alerts check failed (%s)", type(exc).__name__)
    return sent
