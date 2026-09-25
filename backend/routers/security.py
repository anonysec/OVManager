# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.auth.authz import require_owner
from backend.db import crud
from backend.db.engine import get_db
from backend.db.models import User
from backend.node.requests import node_client
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/security", tags=["Security"])


def _get_panel_tz(db: Session) -> ZoneInfo:
    """Return the operator-configured timezone from DB, falling back to UTC."""
    try:
        settings = crud.get_settings(db)
        tz_name = (getattr(settings, "timezone", None) or "UTC").strip() or "UTC"
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, Exception):
        return ZoneInfo("UTC")


# An event this recent means the client is still retrying right now.
_ONGOING_WINDOW_S = 3600


def _cn_to_username(db: Session) -> dict[str, str]:
    """Map OpenVPN common names (panel user ids) to usernames."""
    try:
        return {str(u.id): u.name for u in db.query(User).all()}
    except Exception:
        return {}


def _classify_line(message: str) -> tuple[str, str, str]:
    """Same severity split the node applies (core/openvpn/sessions.py).

    Kept here so a node that predates the classification release is still
    reported honestly: a disabled user's reconnect must not read as a security
    failure just because the node is old.
    """
    table = (
        ("is disabled", "disabled", "policy", "user disabled in the panel"),
        ("disabled;", "disabled", "policy", "user disabled in the panel"),
        ("USERS_DIR missing", "fail_closed", "failure", "node user state missing"),
        ("could not verify", "takeover_failed", "failure", "old session not terminated"),
        ("management unavailable", "mgmt_degraded", "warn", "management unavailable"),
        ("GLOBAL_CHECK_FAILED", "global_check", "policy", "panel policy check failed"),
        ("GLOBAL_REJECT", "global_policy", "policy", "panel rejected the connection"),
        ("max login reached", "max_logins", "policy", "max logins reached"),
    )
    for needle, action, severity, reason in table:
        if needle in message:
            return action, severity, reason
    # The strict max-login hook line carries the limit, not the words
    # "max login reached": "CN=1 ... limit=2 active=2 status=2; REJECT".
    if "REJECT" in message and re.search(r"\blimit=", message):
        return "max_logins", "policy", "max logins reached"
    if "REJECT" in message:
        return "other", "warn", "unclassified reject"
    if "FAILED" in message:
        return "check_failed", "warn", "policy check failed"
    return "event", "policy", "session event"


def _parse_log_line(line: str, common_name: str = "", panel_tz: ZoneInfo = None) -> dict:
    """Convert a raw ovnode-mlogin line to a clean event object.

    Only used for nodes older than the classification release: a current node
    sends structured ``events`` with a real epoch timestamp.
    """
    if panel_tz is None:
        panel_tz = ZoneInfo("UTC")
    cn = common_name
    m_cn = re.search(r"CN=([^\s]+)", line)
    if m_cn:
        cn = m_cn.group(1)
    action, severity, reason = _classify_line(line)
    limit = re.search(r"(?:limit|global_limit)=([^\s;]+)", line)
    active = re.search(r"(?:global_active|active_files)=([^\s;]+)", line)
    msg = re.search(r"msg=([^\n]+)$", line)
    # journal line format: Jul 03 06:20:02 host tag: ... (server timezone is UTC)
    local_time = None
    ts = 0.0
    m_time = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", line)
    if m_time:
        try:
            year = datetime.now(UTC).year
            dt = datetime.strptime(f"{year} {m_time.group(1)} {m_time.group(2)} {m_time.group(3)}", "%Y %b %d %H:%M:%S")
            dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
            ts = dt_utc.timestamp()
            local_time = dt_utc.astimezone(panel_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            local_time = None
            ts = 0.0
    return {
        "ts": ts,
        "time_local": local_time,
        "common_name": cn,
        "action": action,
        "severity": severity,
        "active": active.group(1) if active else None,
        "limit": limit.group(1) if limit else None,
        "reason": (msg.group(1).strip() if msg else reason),
        "line": line,
    }


def _legacy_events(data: dict, node_name: str, panel_tz: ZoneInfo, id_to_name: dict[str, str]) -> list[dict]:
    """Events from a node that predates structured diagnostics.

    The old node counts every reject as an "auth error" and only returns the
    last line per identity, so the panel re-applies the same classification to
    the text it can see and treats the rest as policy. The node is flagged as
    unclassified so the UI can say the exact numbers arrive after an update.
    """
    le = data.get("last_error")
    rows: list[dict] = []
    if isinstance(le, dict):
        raw = [{**_parse_log_line(v, k, panel_tz)} for k, v in le.items()]
    elif le:
        raw = [_parse_log_line(le, panel_tz=panel_tz)]
    else:
        raw = []
    now = datetime.now(UTC).timestamp()
    for ev in raw:
        cn = ev.get("common_name") or ""
        ts = float(ev.get("ts") or 0)
        known = id_to_name.get(cn)
        rows.append(
            {
                "node": node_name,
                "cn": cn,
                "user": known or cn,
                # False = this identity no longer exists in the panel, so the
                # client is reconnecting with a certificate the panel dropped.
                "user_known": bool(known),
                "action": ev.get("action") or "event",
                "severity": ev.get("severity") or "warn",
                "reason": ev.get("reason") or "connection rejected",
                "peer": "",
                "ts": ts,
                "time_local": ev.get("time_local"),
                "ongoing": bool(ts and now - ts <= _ONGOING_WINDOW_S),
                "classified": False,
            }
        )
    return rows


def _node_events(data: dict, node_name: str, panel_tz: ZoneInfo, id_to_name: dict[str, str]) -> list[dict]:
    """Structured events from a current node, normalized for the UI."""
    now = datetime.now(UTC).timestamp()
    rows: list[dict] = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        cn = str(ev.get("cn") or "")
        peer = str(ev.get("peer") or "")
        ts = float(ev.get("ts") or 0)
        known_user = id_to_name.get(cn) if cn else None
        local_time = (
            datetime.fromtimestamp(ts, UTC).astimezone(panel_tz).strftime("%Y-%m-%d %H:%M:%S")
            if ts
            else None
        )
        rows.append(
            {
                "node": node_name,
                "cn": cn,
                # A CN with no matching user is a client reconnecting with a
                # certificate the panel dropped; the UI labels it as such. A
                # CN-less TLS failure has no identity to label — it is a peer.
                "user": known_user or cn or peer,
                "user_known": bool(known_user) if cn else None,
                "action": ev.get("action") or "event",
                "severity": ev.get("severity") or "warn",
                "reason": ev.get("reason") or "connection event",
                "peer": peer,
                "ts": ts,
                "time_local": local_time,
                # Still being retried: the client hit this in the last hour.
                "ongoing": bool(ts and now - ts <= _ONGOING_WINDOW_S),
                "classified": True,
            }
        )
    return rows


@router.get("/summary", response_model=ResponseModel)
async def security_summary(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    nodes = crud.get_all_nodes(db)
    panel_tz = _get_panel_tz(db)
    tz_name = str(panel_tz)
    id_to_name = _cn_to_username(db)

    async def node_diag(node):
        req = node_client(node)
        data = await run_in_threadpool(req.get_sessions, None, hours)
        return node.name, data or {}

    results = await asyncio.gather(*[node_diag(n) for n in nodes], return_exceptions=True)
    per_node = []
    events: list[dict] = []
    unclassified_nodes: list[str] = []
    totals = {"auth_failures": 0, "policy_rejects": 0, "warn_events": 0, "stale_markers": 0, "rejects": 0}
    for item in results:
        if isinstance(item, Exception):
            continue
        node_name, data = item
        stale = int(data.get("stale_marker_count") or 0)
        rejects = int(data.get("rejects") or 0)
        node_events = (
            _node_events(data, node_name, panel_tz, id_to_name)
            if data.get("events")
            else _legacy_events(data, node_name, panel_tz, id_to_name)
        )
        if data.get("events"):
            auth_failures = int(data.get("auth_errors") or 0)
            policy_rejects = int(data.get("policy_rejects") or 0)
            warn_events = int(data.get("warn_rejects") or 0)
            classified = True
        else:
            # Old node: it counts every reject as an auth error and only
            # exposes the last line per identity. Re-classify the text we can
            # see and treat the remainder as policy, which is what a reject on
            # a 1.0.x node practically always is.
            seen_failures = sum(1 for e in node_events if e["severity"] == "failure")
            seen_warns = sum(1 for e in node_events if e["severity"] == "warn")
            auth_failures = seen_failures
            warn_events = seen_warns
            policy_rejects = max(0, rejects - seen_failures - seen_warns)
            classified = False
        totals["auth_failures"] += auth_failures
        totals["policy_rejects"] += policy_rejects
        totals["warn_events"] += warn_events
        totals["stale_markers"] += stale
        totals["rejects"] += rejects
        if not classified:
            unclassified_nodes.append(node_name)

        events.extend(node_events)
        per_node.append(
            {
                "node": node_name,
                # Kept for older frontends; the split below is what the UI uses.
                "auth_errors": auth_failures,
                "auth_failures": auth_failures,
                "policy_rejects": policy_rejects,
                "warn_events": warn_events,
                "rejects": rejects,
                "stale_markers": stale,
                "live": int(data.get("live_count") or 0),
                "ongoing": sum(1 for e in node_events if e["ongoing"]),
                "classified": classified,
            }
        )

    events.sort(key=lambda e: float(e.get("ts") or 0), reverse=True)
    top = Counter(e["user"] for e in events if e.get("user"))
    ongoing_users = sorted({e["user"] for e in events if e["ongoing"] and e.get("user")})
    return ResponseModel(
        success=True,
        msg="Security summary",
        data={
            "hours": hours,
            "timezone": tz_name,
            # Danger bucket: real TLS/auth failures and node-side breakage.
            "auth_errors": totals["auth_failures"],
            "auth_failures": totals["auth_failures"],
            # Informational: disabled users, max logins, panel policy.
            "policy_rejects": totals["policy_rejects"],
            "warn_events": totals["warn_events"],
            "rejects": totals["rejects"],
            "stale_markers": totals["stale_markers"],
            "per_node": per_node,
            "events": events[:100],
            "ongoing_users": ongoing_users,
            # Nodes older than the classification release: their rejects are
            # split by the panel, not reported by the node.
            "unclassified_nodes": unclassified_nodes,
            "last_errors": events[:50],
            "top_common_names": top.most_common(20),
        },
    )
