# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Background sync operations — traffic collection, limit pushing, cleanup.

These functions are called by the APScheduler background jobs and by
maintenance endpoints. They coordinate multi-node data collection and
reconciliation.
"""

import asyncio

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import Node
from backend.node.requests import node_client


async def get_users_used_traffic(node: Node, db: Session) -> dict:
    """Fetch traffic usage data from a single node."""
    nr = node_client(node)
    return await run_in_threadpool(nr.get_usage) or {}


# Last successfully pushed (node_id, user_id) -> max_logins. The 30-minute
# sweep then skips pairs that already hold the value instead of pushing
# nodes×users limits every tick. Failures stay dirty and are retried; only
# successful pushes update the cache. Single process + one scheduler slot,
# so no locking is needed.
_last_pushed_limits: dict[tuple[int, int], int] = {}


def _bulk_limits_client(node):
    req = node_client(node)
    return req


def _push_limits_batch(node, pairs: list[tuple[object, object, int]]) -> dict:
    """Push one chunk of (user, cn, max_logins) to a node via /sync/users.

    Returns per-node summary: applied/failed counts and a success flag.
    Falls back to per-user PUTs only when the node predates the bulk
    route (404) — keeps upgrades from regressing the sweep.
    """
    from backend.node.requests import LONG_TIMEOUT

    req = node_client(node)
    payload = {"users": [{"id": str(u.id), "max_logins": int(ml or 0)} for _, u, ml in pairs]}
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

    Transport: one bulk POST /sync/users per node per sweep (chunked at
    500) instead of one PUT per user per node — N×M → N requests. The
    per-pair cache still tracks exact (node,user) successes so failures
    stay dirty; pairs absent from desired (deleted users/nodes) drop out.
    """
    global _last_pushed_limits
    users = crud.get_all_users(db)
    nodes = crud.get_active_nodes(db)
    desired = {(n.id, u.id): int(u.max_logins or 0) for n in nodes for u in users}
    todo = [
        (n, u)
        for n, u in ((n, u) for n in nodes for u in users)
        if _last_pushed_limits.get((n.id, u.id)) != desired[(n.id, u.id)]
    ]
    skipped = len(desired) - len(todo)

    # Group changed pairs per node, then chunk at the node's bulk cap.
    by_node: dict[int, tuple[object, list[tuple[object, object, int]]]] = {}
    for n, u in todo:
        by_node.setdefault(n.id, (n, []))[1].append((n, u, desired[(n.id, u.id)]))
    _CHUNK = 500
    jobs: list[tuple[object, list[tuple[object, object, int]]]] = []
    for n, pairs in by_node.values():
        for start in range(0, len(pairs), _CHUNK):
            jobs.append((n, pairs[start : start + _CHUNK]))

    _semaphore = asyncio.Semaphore(20)

    async def bounded(job):
        async with _semaphore:
            return await run_in_threadpool(_push_limits_batch, *job)

    raw = await asyncio.gather(*(bounded(j) for j in jobs), return_exceptions=True)
    results = []
    for item in raw:
        if isinstance(item, Exception):
            results.append({"success": False, "error": str(item)})
        else:
            results.append(item)

    # Refresh the cache from fully-successful batches only; failures stay
    # dirty for the next sweep. Pairs absent from desired drop out.
    kept = {pair: val for pair, val in _last_pushed_limits.items() if pair in desired}
    applied_total = 0
    for (n, pairs), item in zip(jobs, raw, strict=True):
        if not isinstance(item, Exception) and item.get("success"):
            applied_total += int(item.get("applied") or 0)
            for _, u, ml in pairs:
                kept[(n.id, u.id)] = ml
        else:
            failed_items = [] if isinstance(item, Exception) else (item.get("failed_items") or [])
            if failed_items:
                results.append({"node": n.name, "success": False, "failed": failed_items})
    _last_pushed_limits = kept
    return {
        "total": len(results),
        "success": sum(1 for r in results if r.get("success")),
        "skipped": skipped,
        "applied": applied_total,
        "results": results,
    }


async def clean_stale_sessions_all_nodes(db: Session) -> dict:
    """Remove stale markers, including dead ones for users that also hold a
    healthy session (previously skipped forever: one stuck dead marker +
    one live session read as "full"). Live sessions are never touched —
    those CNs get the selective cleanup, the rest the full disconnect."""
    nodes = crud.get_all_nodes(db)
    results = []

    def work(node):
        req = node_client(node)
        data = req.get_sessions(hours=8)
        if not isinstance(data, dict):
            return {"node": node.name, "success": False, "error": "diagnostics unavailable", "removed": []}
        live_cns = {s.get("common_name") for s in (data.get("live_sessions") or []) if s.get("common_name")}
        stale_cns = sorted({m.get("common_name") for m in (data.get("stale_markers") or []) if m.get("common_name")})
        removed = []
        for cn in stale_cns:
            # Dead markers beside a live session: selective cleanup only.
            res = req.disconnect_user(cn, only_stale=(cn in live_cns))
            if isinstance(res, dict):
                removed.extend(res.get("removed_markers") or [])
        return {"node": node.name, "success": True, "removed": removed}

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)
    for item in raw:
        if isinstance(item, Exception):
            results.append({"success": False, "error": str(item)})
        else:
            results.append(item)
    return {"nodes": results, "removed_total": sum(len(r.get("removed") or []) for r in results)}
