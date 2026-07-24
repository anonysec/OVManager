from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.engine import SessionLocal
from backend.logger import logger
from backend.node.requests import NodeRequests


def ensure_metrics_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS node_health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            node_id INTEGER,
            node_name TEXT,
            cpu REAL,
            memory REAL,
            live_count INTEGER,
            latency_ms REAL,
            reachable INTEGER NOT NULL DEFAULT 0
        )
    """))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_node_health_ts ON node_health_snapshots(ts)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_node_health_node_ts ON node_health_snapshots(node_id, ts)"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS traffic_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            total_used REAL NOT NULL,
            active_connections INTEGER NOT NULL,
            online_users INTEGER NOT NULL,
            active_users INTEGER NOT NULL,
            total_users INTEGER NOT NULL
        )
    """))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS security_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            auth_errors INTEGER NOT NULL,
            rejects INTEGER NOT NULL,
            stale_markers INTEGER NOT NULL,
            offline_nodes INTEGER NOT NULL,
            full_users INTEGER NOT NULL,
            inactive_users INTEGER NOT NULL
        )
    """))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_security_snapshots_ts ON security_snapshots(ts)"))
    db.commit()


async def _node_snapshot(node) -> dict[str, Any]:
    start = time.perf_counter()
    req = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
    try:
        info, sessions = await asyncio.gather(
            run_in_threadpool(req.get_node_info),
            run_in_threadpool(req.get_sessions, None, 8),
            return_exceptions=True,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        if isinstance(info, Exception) or not isinstance(info, dict):
            info = {}
        if isinstance(sessions, Exception) or not isinstance(sessions, dict):
            sessions = {}
        reachable = bool(info)
        return {
            "node_id": node.id,
            "node_name": node.name,
            "cpu": float(info.get("cpu_usage") or 0),
            "memory": float(info.get("memory_usage") or 0),
            "live_count": int(sessions.get("live_count") or 0),
            "latency_ms": latency_ms,
            "reachable": 1 if reachable else 0,
            "auth_errors": int(sessions.get("auth_errors") or 0),
            "rejects": int(sessions.get("rejects") or 0),
            "stale_markers": int(sessions.get("stale_marker_count") or 0),
        }
    except Exception as e:
        logger.warning("metrics: node snapshot failed for %s: %s", node.name, e)
        return {
            "node_id": node.id,
            "node_name": node.name,
            "cpu": 0,
            "memory": 0,
            "live_count": 0,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "reachable": 0,
            "auth_errors": 0,
            "rejects": 0,
            "stale_markers": 0,
        }


async def collect_metrics() -> None:
    """Collect a compact operational snapshot for graphs and trend widgets."""
    db = SessionLocal()
    now = time.time()
    try:
        ensure_metrics_tables(db)
        nodes = crud.get_all_nodes(db)
        users = crud.get_all_users(db)
        node_rows = await asyncio.gather(*[_node_snapshot(node) for node in nodes], return_exceptions=True)
        clean_rows = [r for r in node_rows if isinstance(r, dict)]

        active_connections = sum(int(r.get("live_count") or 0) for r in clean_rows)
        auth_errors = sum(int(r.get("auth_errors") or 0) for r in clean_rows)
        rejects = sum(int(r.get("rejects") or 0) for r in clean_rows)
        stale_markers = sum(int(r.get("stale_markers") or 0) for r in clean_rows)
        offline_nodes = sum(1 for r in clean_rows if not r.get("reachable"))
        online_users = active_connections
        # Historical `online_users` is approximated by active connection count;
        # current online users still comes from /users which computes live counts.
        active_users = sum(1 for u in users if bool(u.is_active))
        inactive_users = len(users) - active_users
        full_users = 0
        total_used = sum(float(u.used or 0) for u in users)

        for row in clean_rows:
            db.execute(text("""
                INSERT INTO node_health_snapshots
                    (ts, node_id, node_name, cpu, memory, live_count, latency_ms, reachable)
                VALUES
                    (:ts, :node_id, :node_name, :cpu, :memory, :live_count, :latency_ms, :reachable)
            """), {"ts": now, **row})

        db.execute(text("""
            INSERT INTO traffic_snapshots
                (ts, total_used, active_connections, online_users, active_users, total_users)
            VALUES
                (:ts, :total_used, :active_connections, :online_users, :active_users, :total_users)
        """), {
            "ts": now,
            "total_used": total_used,
            "active_connections": active_connections,
            "online_users": online_users,
            "active_users": active_users,
            "total_users": len(users),
        })

        db.execute(text("""
            INSERT INTO security_snapshots
                (ts, auth_errors, rejects, stale_markers, offline_nodes, full_users, inactive_users)
            VALUES
                (:ts, :auth_errors, :rejects, :stale_markers, :offline_nodes, :full_users, :inactive_users)
        """), {
            "ts": now,
            "auth_errors": auth_errors,
            "rejects": rejects,
            "stale_markers": stale_markers,
            "offline_nodes": offline_nodes,
            "full_users": full_users,
            "inactive_users": inactive_users,
        })

        # Keep roughly 30 days at 5-minute interval.
        cutoff = now - 30 * 24 * 3600
        for table in ("node_health_snapshots", "traffic_snapshots", "security_snapshots"):
            db.execute(text(f"DELETE FROM {table} WHERE ts < :cutoff"), {"cutoff": cutoff})
        db.commit()
        logger.info("metrics: snapshot collected nodes=%s active_connections=%s", len(clean_rows), active_connections)
    except Exception as e:
        db.rollback()
        logger.error("metrics: collect failed: %s", e, exc_info=True)
    finally:
        db.close()


def history(db: Session, hours: int = 24) -> dict[str, Any]:
    ensure_metrics_tables(db)
    cutoff = time.time() - max(1, min(int(hours or 24), 24 * 30)) * 3600
    traffic = db.execute(text("""
        SELECT ts, total_used, active_connections, online_users, active_users, total_users
        FROM traffic_snapshots WHERE ts >= :cutoff ORDER BY ts ASC
    """), {"cutoff": cutoff}).fetchall()
    security = db.execute(text("""
        SELECT ts, auth_errors, rejects, stale_markers, offline_nodes, full_users, inactive_users
        FROM security_snapshots WHERE ts >= :cutoff ORDER BY ts ASC
    """), {"cutoff": cutoff}).fetchall()
    node_rows = db.execute(text("""
        SELECT ts, node_id, node_name, cpu, memory, live_count, latency_ms, reachable
        FROM node_health_snapshots WHERE ts >= :cutoff ORDER BY ts ASC
    """), {"cutoff": cutoff}).fetchall()
    return {
        "traffic": [
            {"ts": r[0], "total_used": r[1], "active_connections": r[2], "online_users": r[3], "active_users": r[4], "total_users": r[5]}
            for r in traffic
        ],
        "security": [
            {"ts": r[0], "auth_errors": r[1], "rejects": r[2], "stale_markers": r[3], "offline_nodes": r[4], "full_users": r[5], "inactive_users": r[6]}
            for r in security
        ],
        "nodes": [
            {"ts": r[0], "node_id": r[1], "node_name": r[2], "cpu": r[3], "memory": r[4], "live_count": r[5], "latency_ms": r[6], "reachable": bool(r[7])}
            for r in node_rows
        ],
    }
