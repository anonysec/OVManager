# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import asyncio
import json

from backend.db import crud
from backend.db.engine import get_db
from backend.logger import logger
from backend.node.task import change_user_status_on_all_nodes, get_users_used_traffic
from backend.operations import live


async def enforce_user_limits():
    """Disable users who are expired or exceeded traffic."""
    db = next(get_db())

    try:
        expired_users = crud.get_expired_users(db)
        exceeded_users = crud.get_users_exceeded_traffic(db)

        users_to_disable = list({u.id: u for u in expired_users + exceeded_users}.values())

        # Disable all users in the DB first, then push to nodes concurrently.
        # Eliminates the per-user asyncio.sleep(0.5) that could run for minutes
        # on large user counts and exceed the 10-minute cron interval.
        for user in users_to_disable:
            user.is_active = False
        db.commit()

        # Push status to all nodes concurrently (gather all at once)
        if users_to_disable:
            await asyncio.gather(
                *[change_user_status_on_all_nodes(user_id=u.id, name=u.name, status=False, db=db) for u in users_to_disable],
                return_exceptions=True,
            )
            # Let live subscribers (admin dashboards) see the flips immediately.
            live.publish("users", {"op": "enforce", "disabled": len(users_to_disable)})

    except Exception as e:
        db.rollback()
        logger.error("Error in users expiration check -> %s", e)

    finally:
        db.close()


# ── Traffic delta computation ────────────────────────────────────


def _compute_session_delta(
    sessions: dict | None,
    prev_state: dict | int | None,
    legacy_total: float | int,
) -> tuple[int, dict | int]:
    """Compute the traffic delta for one user on one node.

    Returns (delta_bytes, new_state) where new_state is the updated
    per-session map (or legacy int total if sessions data unavailable).

    The delta logic handles three cases:
    1. Per-session diff — both current and previous are dicts (accurate path)
    2. First-time sessions — sessions dict exists but prev is absent/legacy
    3. Legacy fallback — no per-session data from the node
    """
    if isinstance(sessions, dict) and isinstance(prev_state, dict):
        # Per-session diff (accurate path).
        delta = 0
        for skey, cur in sessions.items():
            last = int(prev_state.get(skey, 0) or 0)
            delta += (cur - last) if cur >= last else cur
        new_state = {k: int(v) for k, v in sessions.items()}
        return delta, new_state

    if isinstance(sessions, dict):
        # First time we see sessions for this node.
        prev_int = int(prev_state or 0) if not isinstance(prev_state, dict) else 0
        cur_total = int(sum(sessions.values()))
        delta = cur_total - prev_int if cur_total >= prev_int else cur_total
        new_state = {k: int(v) for k, v in sessions.items()}
        return delta, new_state

    # Legacy fallback: node didn't send per-session data.
    prev_int = int(prev_state or 0) if not isinstance(prev_state, dict) else 0
    cur_total = int(legacy_total)
    delta = cur_total - prev_int if cur_total >= prev_int else cur_total
    return delta, cur_total


def _extract_username(client_name: str, node_name: str) -> str:
    """Extract the panel username from an OpenVPN client CN.

    CNs are named "<username>-<node_name>". We strip the exact node suffix
    (not just rsplit on "-") so usernames containing dashes work correctly.
    """
    suffix = f"-{node_name}"
    if client_name.endswith(suffix):
        return client_name[: -len(suffix)]
    # Fallback for legacy/unexpected names
    return client_name.rsplit("-", 1)[0]


def _load_node_usage(user) -> dict:
    """Safely parse the user's per-node usage map from JSON."""
    try:
        parsed = json.loads(user.node_usage or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


# ── Main traffic collection loop ─────────────────────────────────


async def _collect_node_traffic(node, all_users: dict, db) -> bool:
    """Collect traffic data from a single node and update user records.

    Returns True when new usage counters were committed (so callers can emit
    a "usage" live event), False when the node had nothing new to offer.
    """
    usage = await get_users_used_traffic(node, db=db)
    if not usage:
        return False

    per_user_total = usage.get("users", {}) or {}
    per_user_sessions = usage.get("sessions", {}) or {}
    if not per_user_total:
        return False

    for client_name, total_bytes in per_user_total.items():
        username = _extract_username(client_name, node.name)
        user = all_users.get(username)

        if not user:
            logger.warning("User not found: %s", username)
            continue

        node_usage = _load_node_usage(user)
        prev_state = node_usage.get(node.name)
        sessions = per_user_sessions.get(client_name)

        delta, new_state = _compute_session_delta(sessions, prev_state, total_bytes)
        delta = max(delta, 0)

        user.used = (user.used or 0) + delta
        node_usage[node.name] = new_state
        user.node_usage = json.dumps(node_usage)

        logger.info(
            "[%s] node=%s total=%d delta=%d",
            username,
            node.name,
            int(total_bytes),
            delta,
        )

    db.commit()
    logger.info("Traffic data committed for node %s", node.address)
    return True


async def check_user_used_traffic():
    """Poll all nodes for traffic usage and update user records.

    Runs every 5 minutes as a background job. For each node, fetches the
    current byte counters, computes per-session deltas (to avoid
    double-counting on session disconnect/reconnect), and persists the
    updated totals.
    """
    db = next(get_db())

    try:
        nodes = crud.get_all_nodes(db)
        if not nodes:
            logger.warning("No nodes found")
            return

        all_users = {u.name: u for u in crud.get_all_users(db)}

        any_updated = False
        for node in nodes:
            try:
                any_updated = (await _collect_node_traffic(node, all_users, db)) or any_updated
            except Exception as e:
                db.rollback()
                logger.error(
                    "Error while processing node %s -> %s",
                    node.address,
                    e,
                    exc_info=True,
                )

        # Usage numbers changed → nudge live dashboards to refetch.
        if any_updated:
            live.publish("usage", {"op": "sync"})

    except Exception as e:
        db.rollback()
        logger.error("Error in check_user_used_traffic -> %s", e, exc_info=True)
    finally:
        db.close()
