import asyncio
import json

from sqlalchemy import text

from backend.db import crud
from backend.db.engine import get_db
from backend.logger import logger
from backend.node.task import change_user_status_on_all_nodes, get_users_used_traffic
from backend.operations import live
from backend.operations.usage_history import record_daily_bytes


async def enforce_user_limits():
    """Disable users who are expired or exceeded traffic."""
    db = next(get_db())

    try:
        expired_users = crud.get_expired_users(db)
        exceeded_users = crud.get_users_exceeded_traffic(db)

        users_to_disable = list({u.id: u for u in expired_users + exceeded_users}.values())

        for user in users_to_disable:
            user.is_active = False
        db.commit()

        if users_to_disable:
            nodes = crud.get_active_nodes(db)
            await asyncio.gather(
                *[
                    change_user_status_on_all_nodes(user_id=u.id, name=u.name, status=False, db=db, nodes=nodes)
                    for u in users_to_disable
                ],
                return_exceptions=True,
            )
            live.publish("users", {"op": "enforce", "disabled": len(users_to_disable)})

    except Exception as e:
        db.rollback()
        logger.error("Error in users expiration check -> %s", e)

    finally:
        db.close()


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
        delta = 0
        for skey, cur in sessions.items():
            last = int(prev_state.get(skey, 0) or 0)
            delta += (cur - last) if cur >= last else cur
        new_state = {k: int(v) for k, v in sessions.items()}
        return delta, new_state

    if isinstance(sessions, dict):
        prev_int = int(prev_state or 0) if not isinstance(prev_state, dict) else 0
        cur_total = int(sum(sessions.values()))
        delta = cur_total - prev_int if cur_total >= prev_int else cur_total
        new_state = {k: int(v) for k, v in sessions.items()}
        return delta, new_state

    prev_int = int(prev_state or 0) if not isinstance(prev_state, dict) else 0
    cur_total = int(legacy_total)
    delta = cur_total - prev_int if cur_total >= prev_int else cur_total
    return delta, cur_total


def _extract_username(client_name: str, node_name: str, known_names=None) -> str:
    """Resolve a node-reported key to a panel username.

    Nodes key payloads by bare username (numeric CNs are mapped client-side
    to usernames before sending). So an exact match wins; the `-node`
    suffix strip exists only for legacy CNs. Unknown keys pass through
    untouched so the caller's warning names the real key — the old
    rsplit("-", 1) fallback mangled dashed usernames ("john-doe" → "john")
    and silently unbilled them.
    """
    if known_names is not None and client_name in known_names:
        return client_name
    suffix = f"-{node_name}"
    if client_name.endswith(suffix):
        return client_name[: -len(suffix)]
    return client_name


def _load_node_usage(user) -> dict:
    """Safely parse the user's per-node usage map from JSON."""
    try:
        parsed = json.loads(user.node_usage or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _apply_user_traffic(db, user_id: int, expected_used, expected_state: str, new_used: int, new_state: str, delta: int) -> bool:
    """Persist one user's traffic only if the row still holds the loaded values.

    A concurrent reset-usage or delete changes those values, so a stale
    update becomes a no-op instead of resurrecting old numbers. The daily
    history row is written only when the user row was actually updated, so a
    deleted user cannot reappear as an orphan ``user_traffic_daily`` row.
    """
    result = db.execute(
        text(
            "UPDATE users SET used = :new_used, node_usage = :new_state "
            "WHERE id = :uid AND used IS :old_used AND node_usage IS :old_state"
        ),
        {
            "uid": int(user_id),
            "new_used": int(new_used),
            "new_state": new_state,
            "old_used": expected_used,
            "old_state": expected_state,
        },
    )
    if result.rowcount != 1:
        return False
    if delta:
        record_daily_bytes(db, int(user_id), int(delta))
    return True


async def _collect_node_traffic(node, all_users: dict, db, id_to_name: dict | None = None) -> bool:
    """Collect traffic data from a single node and update user records.

    Billing prefers the node's lifetime `totals` (banked + live): it bills
    growth of one cumulative counter per (node, user), so short sessions,
    disconnect tails and offline-completed bytes are all captured, while
    resets and daemon restarts can only shrink it (bills zero, never
    negative). First sight (or post-reset) baselines without billing.
    Nodes too old to send `totals` fall back to per-session deltas.

    Returns True when the node's state was committed.
    """
    usage = await get_users_used_traffic(node, db=db)
    if not usage:
        return False

    per_user_total = usage.get("users", {}) or {}
    per_user_sessions = usage.get("sessions", {}) or {}
    totals_map = usage.get("totals", {}) or {}
    if not per_user_total and not totals_map:
        return False

    id_to_name = id_to_name or {}
    known = set(all_users)
    pending: dict[int, dict] = {}
    for client_key in set(per_user_total) | set(totals_map):
        username = _extract_username(client_key, node.name, known)
        user = all_users.get(username)
        if user is None and str(client_key).isdigit():
            username = id_to_name.get(str(client_key), username)
            user = all_users.get(username)
        if user is None:
            logger.warning("User not found: %s (node %s)", client_key, node.name)
            continue

        entry = pending.get(user.id)
        node_usage = entry["node_usage"] if entry else _load_node_usage(user)
        state = node_usage.get(node.name)
        totals_now = totals_map.get(client_key)
        if totals_now is not None:
            try:
                cur_total = int(totals_now)
            except (TypeError, ValueError):
                cur_total = None
            prev = state.get("total") if isinstance(state, dict) else None
            if cur_total is not None and isinstance(prev, (int, float)):
                delta = max(cur_total - int(prev), 0)
            else:
                delta = 0  # (re)baseline: reset, first sight, legacy state
            node_usage[node.name] = {"total": cur_total if cur_total is not None else 0}
        else:
            sessions = per_user_sessions.get(client_key) or per_user_sessions.get(username)
            if isinstance(state, dict) and "total" in state:
                delta, new_state = 0, state
            else:
                delta, new_state = _compute_session_delta(sessions, state, per_user_total.get(client_key, 0))
            node_usage[node.name] = new_state

        delta = max(int(delta), 0)
        if entry is None:
            entry = {"user": user, "delta": 0, "node_usage": node_usage}
            pending[user.id] = entry
        entry["delta"] += delta

        logger.debug(
            "[%s] node=%s total=%s delta=%d",
            username,
            node.name,
            totals_now if totals_now is not None else int(per_user_total.get(client_key, 0)),
            delta,
        )

    for user_id, entry in pending.items():
        user = entry["user"]
        old_used = user.used or 0
        old_state = user.node_usage or "{}"
        new_state = json.dumps(entry["node_usage"])
        if entry["delta"] == 0 and new_state == old_state:
            continue
        if not _apply_user_traffic(db, user_id, old_used, old_state, old_used + entry["delta"], new_state, entry["delta"]):
            logger.info(
                "Traffic update skipped for %s: counters changed concurrently (reset or delete)",
                user.name,
            )

    db.commit()
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
        id_to_name = dict(crud.get_user_id_name_pairs(db))

        any_updated = False
        for node in nodes:
            try:
                any_updated = (await _collect_node_traffic(node, all_users, db, id_to_name)) or any_updated
            except Exception as e:
                db.rollback()
                logger.error(
                    "Error while processing node %s -> %s",
                    node.address,
                    e,
                    exc_info=True,
                )

        if any_updated:
            live.publish("usage", {"op": "sync"})
            await enforce_user_limits()

    except Exception as e:
        db.rollback()
        logger.error("Error in check_user_used_traffic -> %s", e, exc_info=True)
    finally:
        db.close()
