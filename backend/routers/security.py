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
    action = "reject" if "REJECT" in line else ("check_failed" if "FAILED" in line else "event")
    if "GLOBAL_REJECT" in line:
        scope = "global"
    elif "LOCAL_REJECT" in line or " REJECT" in line:
        scope = "local"
    else:
        scope = "global" if "GLOBAL" in line else "local"
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
    username = cn.rsplit("-", 1)[0] if "-" in cn else cn
    return {
        "ts": ts,
        "time_local": local_time,
        "username": username,
        "common_name": cn,
        "scope": scope,
        "action": action,
        "active": active.group(1) if active else None,
        "limit": limit.group(1) if limit else None,
        "reason": (msg.group(1).strip() if msg else ("max login reached" if "REJECT" in line else "global check failed")),
        "line": line,
    }


def _legacy_events(data: dict, node_name: str, panel_tz: ZoneInfo, id_to_name: dict[str, str]) -> list[dict]:
    """Events from a node that predates structured diagnostics.

    Every reject is a policy event by assumption: the old node did not report
    TLS failures at all, so showing them as auth errors would be a guess.
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
        rows.append(
            {
                "node": node_name,
                "cn": cn,
                "user": id_to_name.get(cn, ev.get("username") or cn or "(unknown)"),
                "action": ev.get("action") or "event",
                "severity": "policy",
                "reason": ev.get("reason") or "connection rejected",
                "peer": "",
                "ts": ts,
                "time_local": ev.get("time_local"),
                "ongoing": bool(ts and now - ts <= _ONGOING_WINDOW_S),
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
        ts = float(ev.get("ts") or 0)
        local_time = (
            datetime.fromtimestamp(ts, UTC).astimezone(panel_tz).strftime("%Y-%m-%d %H:%M:%S")
            if ts
            else None
        )
        rows.append(
            {
                "node": node_name,
                "cn": cn,
                "user": id_to_name.get(cn) or ("(tls)" if not cn and ev.get("peer") else ""),
                "action": ev.get("action") or "event",
                "severity": ev.get("severity") or "warn",
                "reason": ev.get("reason") or "connection event",
                "peer": ev.get("peer") or "",
                "ts": ts,
                "time_local": local_time,
                # Still being retried: the client hit this in the last hour.
                "ongoing": bool(ts and now - ts <= _ONGOING_WINDOW_S),
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
    totals = {"auth_failures": 0, "policy_rejects": 0, "warn_events": 0, "stale_markers": 0, "rejects": 0}
    for item in results:
        if isinstance(item, Exception):
            continue
        node_name, data = item
        auth_failures = int(data.get("auth_errors") or 0)
        policy_rejects = int(data.get("policy_rejects") or 0)
        warn_events = int(data.get("warn_rejects") or 0)
        stale = int(data.get("stale_marker_count") or 0)
        rejects = int(data.get("rejects") or 0)
        totals["auth_failures"] += auth_failures
        totals["policy_rejects"] += policy_rejects
        totals["warn_events"] += warn_events
        totals["stale_markers"] += stale
        totals["rejects"] += rejects

        node_events = (
            _node_events(data, node_name, panel_tz, id_to_name)
            if data.get("events")
            else _legacy_events(data, node_name, panel_tz, id_to_name)
        )
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
            "last_errors": events[:50],
            "top_common_names": top.most_common(20),
        },
    )
