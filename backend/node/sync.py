"""Background sync operations — traffic collection, limit pushing, cleanup.

Called by the APScheduler jobs and by maintenance endpoints.
"""

import asyncio
import hashlib
import json
from functools import partial

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import Node
from backend.node.fanout import chunk_by_size, gather_nodes, run_bounded
from backend.node.requests import node_client, panel_id_for

PUSH_HASH_KEY = "push_hash"
DEFAULT_BATCH_SIZE = 100
MAX_PUSH_BYTES = 1_048_576  # one bulk chunk stays well under a megabyte


async def get_users_used_traffic(node: Node, db: Session) -> dict:
    nr = node_client(node, panel_id=panel_id_for(db))
    return await run_in_threadpool(nr.get_usage) or {}


_last_pushed_limits: dict[tuple[int, int], int] = {}


def _push_hash(uid: str, name: str, max_logins: int) -> str:
    """sha256 over the state this sweep pushes for one user on one node.

    Scope: limits sweeps only — PKI pushes (certificate pins, renewals) are
    intentionally unhashed and always go out in full.
    """
    return hashlib.sha256(f"{uid}|{name}|{int(max_logins or 0)}".encode()).hexdigest()


def _stored_push_hashes(user) -> dict[str, str]:
    try:
        data = json.loads(user.node_usage or "{}")
    except ValueError:
        return {}
    stored = data.get(PUSH_HASH_KEY)
    return stored if isinstance(stored, dict) else {}


def _merge_push_hashes(db: Session, entries: list[tuple[object, dict[str, str]]]) -> None:
    """Persist per-node push hashes into ``users.node_usage['push_hash']``.

    Guarded per row (same rule as the traffic collector): a node_usage write
    that landed under us wins, and the pair is simply re-pushed next sweep.
    """
    for user, new_hashes in entries:
        old_state = user.node_usage or "{}"
        try:
            data = json.loads(old_state)
        except ValueError:
            data = {}
        merged = dict(data.get(PUSH_HASH_KEY) or {})
        if all(merged.get(k) == v for k, v in new_hashes.items()):
            continue
        merged.update(new_hashes)
        data[PUSH_HASH_KEY] = merged
        db.execute(
            text("UPDATE users SET node_usage = :new WHERE id = :uid AND COALESCE(node_usage, '{}') = :old"),
            # canonical payload, raw bind: the write is sorted/compact, the
            # ``= :old`` guard must still match the row as it is stored
            {"new": json.dumps(data, sort_keys=True, separators=(",", ":")), "uid": user.id, "old": old_state},
        )
    db.commit()


def _batch_size(db: Session) -> int:
    raw = crud.get_kv(db, "sync.batch_size")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_BATCH_SIZE


def _push_limits_batch(node, pairs: list[tuple[object, object, int]], panel_id: str | None = None) -> dict:
    """Push one chunk of (user, cn, max_logins) to a node via /sync/users.

    Falls back to per-user PUTs only when the node predates the bulk
    route (404) — keeps upgrades from regressing the sweep.
    """
    from backend.node.requests import LONG_TIMEOUT

    req = node_client(node, panel_id=panel_id)
    payload = {"users": [{"id": str(u.id), "max_logins": int(u.max_logins or 0)} for _, u, _want in pairs]}
    r = req._request("post", "/sync/users", json=payload, timeout=LONG_TIMEOUT, require_success=False)  # noqa: SLF001
    if r is None:
        return {"node": node.name, "applied": 0, "failed": len(pairs), "success": False}
    data = (r or {}).get("data") or {}
    applied = int(data.get("applied") or 0)
    failed_items = data.get("failed") or []
    return {
        "node": node.name,
        "applied": applied,
        "failed": len(failed_items),
        "success": applied + len(failed_items) >= len(pairs) and not failed_items,
        "failed_items": failed_items,
    }


async def sync_all_user_limits(db: Session) -> dict:
    """Push changed max_login limits to every reachable node.

    Offline nodes (status=False) are skipped — pushing to them only burns
    timeouts every 30 minutes. They re-sync on next successful contact
    (add/update flows) or via the manual maintenance sync-limits endpoint.

    One bulk POST /sync/users per node per sweep (chunked at settings_kv
    ``sync.batch_size``, default 100, and under 1MB) instead of one PUT per
    user per node: N×M → N/chunk requests. The per-pair cache still tracks
    exact (node,user) successes so failures stay dirty, and each success is
    also recorded as a durable sha256 ``push_hash`` in the user's
    node_usage JSON so a panel restart does not re-push every unchanged
    user.
    """
    global _last_pushed_limits
    users = crud.get_all_users(db)
    nodes = crud.get_active_nodes(db)
    desired = {(n.id, u.id): int(u.max_logins or 0) for n in nodes for u in users}
    todo: list[tuple[object, object, str]] = []
    hash_cache: dict[int, dict[str, str]] = {}  # parse node_usage once per user, not per pair
    for n, u in ((n, u) for n in nodes for u in users):
        if _last_pushed_limits.get((n.id, u.id)) == desired[(n.id, u.id)]:
            continue  # already confirmed pushed this process lifetime
        want = _push_hash(str(u.id), u.name, u.max_logins)
        if u.id not in hash_cache:
            hash_cache[u.id] = _stored_push_hashes(u)
        if hash_cache[u.id].get(str(n.id)) == want:
            _last_pushed_limits[(n.id, u.id)] = desired[(n.id, u.id)]
            continue  # durable hash survives restarts
        todo.append((n, u, want))
    skipped = len(desired) - len(todo)

    by_node: dict[int, tuple[object, list]] = {}
    for n, u, want in todo:
        by_node.setdefault(n.id, (n, []))[1].append((n, u, want))
    pid = panel_id_for(db)
    size = _batch_size(db)

    def _pair_bytes(pair) -> int:
        _, u, _want = pair
        return len(json.dumps({"id": str(u.id), "max_logins": int(u.max_logins or 0)})) + 1

    jobs: list[tuple[object, list, str | None]] = []
    for n, pairs in by_node.values():
        for chunk in chunk_by_size(pairs, size, MAX_PUSH_BYTES, _pair_bytes):
            jobs.append((n, chunk, pid))

    raw = await asyncio.gather(*(run_bounded(_push_limits_batch, *j) for j in jobs), return_exceptions=True)
    results = []
    for item in raw:
        if isinstance(item, Exception):
            results.append({"success": False, "error": str(item)})
        else:
            results.append(item)

    kept = {pair: val for pair, val in _last_pushed_limits.items() if pair in desired}
    applied_total = 0
    fresh: dict[int, tuple[object, dict[str, str]]] = {}
    for (n, pairs, _pid), item in zip(jobs, raw, strict=True):
        if not isinstance(item, Exception) and item.get("success"):
            applied_total += int(item.get("applied") or 0)
            for _, u, want in pairs:
                kept[(n.id, u.id)] = int(u.max_logins or 0)
                fresh.setdefault(u.id, (u, {}))[1][str(n.id)] = want
        else:
            failed_items = [] if isinstance(item, Exception) else (item.get("failed_items") or [])
            if failed_items:
                results.append({"node": n.name, "success": False, "failed": failed_items})
    _last_pushed_limits = kept
    if fresh:
        _merge_push_hashes(db, list(fresh.values()))
    return {
        "total": len(results),
        "success": sum(1 for r in results if r.get("success")),
        "skipped": skipped,
        "applied": applied_total,
        "results": results,
    }


async def clean_stale_sessions_all_nodes(db: Session) -> dict:
    """Remove stale markers, including dead ones for users that also hold a
    healthy session (previously skipped forever: one stuck dead marker plus
    one live session read as "full")."""
    nodes = crud.get_all_nodes(db)
    results = []
    pid = panel_id_for(db)

    def work(node):
        req = node_client(node, panel_id=pid)
        data = req.get_sessions(hours=8)
        if not isinstance(data, dict):
            return {"node": node.name, "success": False, "error": "diagnostics unavailable", "removed": []}
        live_cns = {s.get("common_name") for s in (data.get("live_sessions") or []) if s.get("common_name")}
        stale_cns = sorted({m.get("common_name") for m in (data.get("stale_markers") or []) if m.get("common_name")})
        removed = []
        for cn in stale_cns:
            res = req.disconnect_user(cn, only_stale=(cn in live_cns))
            if isinstance(res, dict):
                removed.extend(res.get("removed_markers") or [])
        return {"node": node.name, "success": True, "removed": removed}

    raw = await gather_nodes([partial(work, n) for n in nodes])
    for item in raw:
        if isinstance(item, Exception):
            results.append({"success": False, "error": str(item)})
        else:
            results.append(item)
    return {"nodes": results, "removed_total": sum(len(r.get("removed") or []) for r in results)}
