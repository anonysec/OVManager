# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Background sync operations — traffic collection, limit pushing, cleanup.

These functions are called by the APScheduler background jobs and by
maintenance endpoints. They coordinate multi-node data collection and
reconciliation.
"""

import asyncio
import time

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import Node
from backend.logger import logger
from backend.node.requests import NodeRequests


async def get_users_used_traffic(node: Node, db: Session) -> dict:
    """Fetch traffic usage data from a single node."""
    nr = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
    return await run_in_threadpool(nr.get_usage) or {}


async def sync_all_user_limits(db: Session) -> dict:
    """Push every user's max_login limit to every node."""
    users = crud.get_all_users(db)
    nodes = crud.get_all_nodes(db)
    results = []
    _semaphore = asyncio.Semaphore(20)

    def work(node, user):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
        cn = str(user.id)
        ok = req.set_user_limit(str(user.id), int(user.max_logins or 0))
        return {
            "node": node.name,
            "user": user.name,
            "common_name": cn,
            "max_logins": int(user.max_logins or 0),
            "success": bool(ok),
        }

    async def bounded_work(node, user):
        async with _semaphore:
            return await run_in_threadpool(work, node, user)

    tasks = [bounded_work(n, u) for n in nodes for u in users]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    for item in raw:
        if isinstance(item, Exception):
            results.append({"success": False, "error": str(item)})
        else:
            results.append(item)
    return {"total": len(results), "success": sum(1 for r in results if r.get("success")), "results": results}


async def clean_stale_sessions_all_nodes(db: Session) -> dict:
    """Remove stale markers where no live session exists."""
    nodes = crud.get_all_nodes(db)
    results = []

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
        data = req.get_sessions(hours=8)
        if not isinstance(data, dict):
            return {"node": node.name, "success": False, "error": "diagnostics unavailable", "removed": []}
        live_cns = {s.get("common_name") for s in (data.get("live_sessions") or []) if s.get("common_name")}
        stale_cns = sorted({m.get("common_name") for m in (data.get("stale_markers") or []) if m.get("common_name")})
        removed = []
        for cn in stale_cns:
            if cn in live_cns:
                continue
            res = req.disconnect_user(cn)
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


async def clean_global_mlogin_registry(db: Session, grace_seconds: int = 30) -> dict:
    """Clean stale panel-side global_mlogin_sessions rows."""
    nodes = crud.get_all_nodes(db)
    live_keys: set[tuple[str, str, str, str]] = set()
    reachable_nodes: set[str] = set()

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
        data = req.get_sessions(hours=1)
        return node, data if isinstance(data, dict) else {}

    raw = await asyncio.gather(*[run_in_threadpool(work, n) for n in nodes], return_exceptions=True)
    for item in raw:
        if isinstance(item, Exception):
            logger.warning("global registry cleanup: node failed: %s", item)
            continue
        node_data, data = item
        if not data:
            continue
        reachable_nodes.add(node_data.name)
        for sess in data.get("live_sessions") or []:
            live_keys.add(
                (
                    node_data.name,
                    str(sess.get("common_name") or ""),
                    str(sess.get("trusted_ip") or ""),
                    str(sess.get("trusted_port") or ""),
                )
            )

    try:
        rows = db.execute(
            text("SELECT id, username, common_name, node_name, trusted_ip, trusted_port, created_at FROM global_mlogin_sessions")
        ).fetchall()
    except Exception:
        return {"reachable_nodes": sorted(reachable_nodes), "removed": [], "kept": [], "message": "registry table missing"}

    now = time.time()
    removed = []
    kept_count = 0
    for row in rows:
        key = (str(row[3] or ""), str(row[2] or ""), str(row[4] or ""), str(row[5] or ""))
        node_name = key[0]
        if node_name not in reachable_nodes:
            kept_count += 1
            continue
        if float(row[6] or 0) > now - int(grace_seconds or 30):
            kept_count += 1
            continue
        if key not in live_keys:
            db.execute(text("DELETE FROM global_mlogin_sessions WHERE id = :id"), {"id": row[0]})
            removed.append(
                {
                    "id": row[0],
                    "username": row[1],
                    "common_name": row[2],
                    "node": row[3],
                    "trusted_ip": row[4],
                    "trusted_port": row[5],
                }
            )
    db.commit()
    return {
        "reachable_nodes": sorted(reachable_nodes),
        "removed": removed,
        "kept_count": kept_count,
        "live_count": len(live_keys),
    }
