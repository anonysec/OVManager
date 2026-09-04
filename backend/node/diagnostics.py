# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Session diagnostics and login health monitoring.

Provides detailed visibility into user sessions, active connections,
login health status, and per-user login diagnostics.
"""

import asyncio
import datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import User
from backend.node.requests import NodeRequests


async def get_active_connection_counts(db: Session) -> dict[str, int]:
    """Query all active nodes for live connection counts per user.

    Returns {username: active_count} across all reachable nodes.
    CNs are numeric user IDs — we map back to usernames via the user table.
    """
    nodes = crud.get_active_nodes(db)
    counts: dict[str, int] = {}

    # Build id→username map for fast lookup
    all_users = crud.get_all_users(db)
    id_to_name = {str(u.id): u.name for u in all_users}

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=crud.node_api_key(node), use_tls=node.use_tls)
        return node, req.get_sessions(hours=1)

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)
    for item in raw:
        if isinstance(item, Exception):
            continue
        node_data, data = item
        if not isinstance(data, dict):
            continue
        for sess in data.get("live_sessions") or []:
            cn = sess.get("common_name", "")
            # CN is the numeric user ID — direct map to username
            username = id_to_name.get(cn, cn)
            counts[username] = counts.get(username, 0) + 1

    return counts


async def get_user_session_diagnostics(user_id: int, db: Session, hours: int = 8) -> dict:
    """Get detailed session info for one user across all nodes. Uses numeric ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"username": str(user_id), "found": False}

    nodes = crud.get_active_nodes(db)
    node_rows = []
    cn = str(user.id)

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=crud.node_api_key(node), use_tls=node.use_tls)
        return node, req.get_sessions(hours=hours)

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)
    total_live = 0
    total_stale = 0
    total_auth = 0

    for item in raw:
        if isinstance(item, Exception):
            continue
        node_data, data = item
        if not isinstance(data, dict):
            node_rows.append({"node": node_data.name, "reachable": False})
            continue
        live = [s for s in (data.get("live_sessions") or []) if s.get("common_name") == cn]
        stale = [s for s in (data.get("stale_markers") or []) if s.get("common_name") == cn]
        node_rows.append(
            {
                "node": node_data.name,
                "reachable": True,
                "live_sessions": live,
                "stale_markers": stale,
                "live_count": len(live),
                "stale_marker_count": len(stale),
                "auth_errors": int(data.get("auth_errors") or 0),
            }
        )
        total_live += len(live)
        total_stale += len(stale)
        total_auth += int(data.get("auth_errors") or 0)

    return {
        "username": user.name,
        "user_id": user.id,
        "found": True,
        "nodes": node_rows,
        "totals": {
            "live_count": total_live,
            "stale_marker_count": total_stale,
            "auth_errors": total_auth,
        },
    }


async def disconnect_user_on_all_nodes(name: str, user_id: int, db: Session) -> dict:
    """Disconnect a user from all active nodes. Uses numeric user ID as CN."""
    nodes = crud.get_active_nodes(db)
    results = []
    cn = str(user_id)

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=crud.node_api_key(node), use_tls=node.use_tls)
        return {"node": node.name, "result": req.disconnect_user(cn)}

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)
    for item in raw:
        if isinstance(item, Exception):
            results.append({"error": str(item)})
        else:
            results.append(item)
    return {"user": name, "nodes": results}


async def login_health_summary(db: Session, hours: int = 8) -> dict:
    """Aggregate login health across all users and nodes."""
    users = crud.get_all_users(db)
    nodes = crud.get_active_nodes(db)

    # Build id→username map (CN is numeric ID)
    id_to_name = {str(u.id): u.name for u in users}

    # Collect active connection counts
    active_counts = await get_active_connection_counts(db)

    # Collect per-user stale and auth data
    stale_counts: dict[str, int] = {}
    auth_counts: dict[str, int] = {}
    node_rows = []

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=crud.node_api_key(node), use_tls=node.use_tls)
        return node, req.get_sessions(hours=hours)

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)

    for item in raw:
        if isinstance(item, Exception):
            continue
        node_data, data = item
        if not isinstance(data, dict):
            node_rows.append({"node": node_data.name, "reachable": False})
            continue

        # Map CNs (numeric IDs) back to usernames
        for sess in data.get("live_sessions") or []:
            cn = sess.get("common_name", "")
            username = id_to_name.get(cn, cn)
            stale_counts[username] = stale_counts.get(username, 0)

        for marker in data.get("stale_markers") or []:
            cn = marker.get("common_name", "")
            username = id_to_name.get(cn, cn)
            stale_counts[username] = stale_counts.get(username, 0) + 1

        # Auth errors from journal
        for cn, count in (data.get("auth_errors_by_cn") or {}).items():
            if isinstance(count, int):
                auth_counts[cn] = auth_counts.get(cn, 0) + count

        node_rows.append(
            {
                "node": node_data.name,
                "live_count": int(data.get("live_count") or 0),
                "stale_marker_count": int(data.get("stale_marker_count") or 0),
                "auth_errors": int(data.get("auth_errors") or 0),
                "reachable": True,
            }
        )

    rows = []
    for u in users:
        active = int(active_counts.get(u.name, 0))
        max_logins = int(u.max_logins or 0)
        mode = "unlimited" if max_logins == 0 else ("takeover" if max_logins == 1 else "strict")
        full = max_logins > 0 and active >= max_logins
        if not bool(u.is_active):
            status = "inactive"
        elif stale_counts.get(u.name, 0):
            status = "stale"
        elif full and mode == "strict":
            status = "full"
        elif active > 0:
            status = "online"
        else:
            status = "idle"
        stale_count = int(stale_counts.get(u.name, 0))
        if active <= 0 and stale_count <= 0:
            continue
        rows.append(
            {
                "name": u.name,
                "user_id": u.id,
                "active_connections": active,
                "max_logins": max_logins,
                "mode": mode,
                "full": full,
                "is_active": bool(u.is_active),
                "stale_markers": stale_count,
                "auth_events": int(auth_counts.get(u.name, 0)),
                "status": status,
            }
        )

    rows.sort(key=lambda r: (r["status"] != "stale", -r["active_connections"], r["name"].lower()))
    return {
        "users": rows,
        "nodes": node_rows,
        "totals": {
            "shown": len(rows),
            "users": len(users),
            "online": sum(1 for r in rows if r["active_connections"] > 0),
            "full": sum(1 for r in rows if r["full"]),
            "stale": sum(r["stale_markers"] for r in rows),
            "takeover_mode": sum(1 for r in rows if r["mode"] == "takeover"),
        },
    }


async def login_diagnostics(name: str, db: Session, hours: int = 8) -> dict:
    """Detailed no-disconnect login diagnostics for one user."""
    user = crud.get_user_by_name(db, name)
    if not user:
        return {"username": name, "found": False}

    diag = await get_user_session_diagnostics(user.id, db, hours=hours)
    health = await login_health_summary(db, hours=hours)
    health_row = next((u for u in health.get("users", []) if u.get("name") == name), None)

    registry = []
    try:
        rows = db.execute(
            text(
                "SELECT username, common_name, node_name, session_key, trusted_ip, trusted_port, "
                "pool_ip, created_at, updated_at "
                "FROM global_mlogin_sessions WHERE username = :username ORDER BY updated_at DESC"
            ),
            {"username": name},
        ).fetchall()
        for r in rows:
            registry.append(
                {
                    "username": r[0],
                    "common_name": r[1],
                    "node_name": r[2],
                    "session_key": r[3],
                    "trusted_ip": r[4],
                    "trusted_port": r[5],
                    "pool_ip": r[6],
                    "created_at": r[7],
                    "updated_at": r[8],
                    "created_at_utc": datetime.datetime.utcfromtimestamp(float(r[7] or 0)).isoformat() if r[7] else None,
                }
            )
    except Exception:
        registry = []

    used = user.used or 0
    policy = []
    if not bool(user.is_active):
        policy.append("inactive")
    if user.expiry_date and user.expiry_date < datetime.date.today():
        policy.append("expired")
    if user.total is not None and used >= user.total:
        policy.append("traffic_limit_reached")
    if not policy:
        policy.append("ok")

    active = int((health_row or {}).get("active_connections") or diag.get("totals", {}).get("live_count") or 0)
    max_logins = int(user.max_logins or 0)
    if max_logins == 0:
        recommendation = "Unlimited login mode; no max-login block expected."
    elif max_logins == 1:
        recommendation = "Takeover mode: new connection should disconnect old session and be allowed."
    elif active >= max_logins:
        recommendation = "Strict mode is full; disconnect a session or increase max logins."
    else:
        recommendation = "User is below max-login limit. If connection fails, check node logs/config."

    return {
        "username": name,
        "found": True,
        "policy": policy,
        "max_logins": max_logins,
        "mode": "unlimited" if max_logins == 0 else ("takeover" if max_logins == 1 else "strict"),
        "active_connections": active,
        "global_registry": registry,
        "global_registry_error": None,
        "nodes": diag.get("nodes", []),
        "totals": diag.get("totals", {}),
        "health": health_row,
        "recommendation": recommendation,
    }
