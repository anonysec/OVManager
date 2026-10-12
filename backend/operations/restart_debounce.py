"""Debounced node restarts: structural edits set one flag, one consumer fans out.

A structural change (tunnel address, protocol, control port, PKI push) needs a
node restart to take effect. Doing that restart inside the edit handler blocks
the request on an unreachable node and restarts once per field. Instead the
edit only sets a flag in ``settings_kv``; a worker job fans the restart out on
its own cadence, clears the flag when every node reports success, and backs off
on a partial failure so a down node is retried without hammering it.
"""

from __future__ import annotations

import asyncio
import json
import time

from backend.db import crud
from backend.db.engine import SessionLocal
from backend.logger import logger
from backend.node.requests import node_client, panel_id_for

RESTART_FLAG_KEY = "sync.restart_debounce"
RETRY_BASE_SECONDS = 30
MAX_BACKOFF_SECONDS = 300  # 5m cap on the retry delay


def _write_flag(db, flag: int, reason: str, attempts: int, next_retry_at: float, done: list[str] | None = None) -> None:
    payload = json.dumps(
        {
            "flag": flag,
            "reason": reason,
            "attempts": attempts,
            "updated_at": time.time(),
            "next_retry_at": next_retry_at,
            "done": sorted(done or []),
        }
    )
    crud.set_kv(db, RESTART_FLAG_KEY, payload)
    db.commit()


def _read_raw(db) -> str | None:
    return crud.get_kv(db, RESTART_FLAG_KEY)


def mark_restart_pending(db, reason: str) -> None:
    """Set the restart flag (idempotent — N edits collapse to one flag).

    A fresh structural edit also clears any backoff, so the newest change is
    retried promptly rather than waiting out a stale node's cooldown.
    """
    _write_flag(db, 1, reason, 0, 0)


def read_restart_flag(db) -> dict | None:
    raw = _read_raw(db)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("flag") else None


def clear_restart_flag(db) -> None:
    _write_flag(db, 0, "", 0, 0)


def retry_stale_restart_flag(db) -> bool:
    """At startup, re-queue a pending flag whose retry is already due.

    Judged by ``next_retry_at`` (when the retry is owed), not by ``updated_at``
    age: a flag still inside its capped backoff window must keep backing off
    across a worker restart. The consumer's own due-check fires on its first
    run either way — this only clears a backoff that is already past due.
    """
    flag = read_restart_flag(db)
    if not flag:
        return False
    if time.time() >= float(flag.get("next_retry_at", 0) or 0):
        _write_flag(db, 1, flag.get("reason", ""), int(flag.get("attempts", 0) or 0), 0, done=flag.get("done"))
        return True
    return False


async def _restart_all(nodes, pid: str | None) -> list[str]:
    """Fan a restart out to every given node; return the names that succeeded."""
    results = await asyncio.gather(
        *[node_client(n, panel_id=pid).restart_vpn() for n in nodes],
        return_exceptions=True,
    )
    return [
        n.name
        for n, r in zip(nodes, results, strict=True)
        if (not isinstance(r, Exception)) and bool(r) and bool(r.get("success"))
    ]


async def process_restart_debounce() -> None:
    """Consume the restart flag: fan out to the owed nodes only, clear on all-success.

    The flag payload remembers which node names already succeeded (``done``),
    so a partial failure retries only the nodes that are still down.
    """
    db = SessionLocal()
    try:
        flag = read_restart_flag(db)
        if not flag:
            return
        now = time.time()
        if now < float(flag.get("next_retry_at", 0) or 0):
            return  # a failed fan-out is still backing off
        done = set(flag.get("done") or [])
        nodes = [n for n in crud.get_active_nodes(db) if n.name not in done]
        pid = panel_id_for(db)
        succeeded = await _restart_all(nodes, pid)
        done.update(succeeded)
        if len(succeeded) == len(nodes):
            clear_restart_flag(db)
            logger.info("restart-debounce: %s applied on all nodes", flag.get("reason", ""))
        else:
            attempts = int(flag.get("attempts", 0) or 0) + 1
            delay = min(MAX_BACKOFF_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
            _write_flag(db, 1, flag.get("reason", ""), attempts, now + delay, done=sorted(done))
            logger.warning(
                "restart-debounce: %d node(s) still down for %s, retry in %ds",
                len(nodes) - len(succeeded),
                flag.get("reason", ""),
                delay,
            )
    finally:
        db.close()
