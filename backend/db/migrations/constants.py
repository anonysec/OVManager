"""Schema version and the locks/DDL shared by every step."""

from __future__ import annotations

import threading

from sqlalchemy.dialects import sqlite as sqlite_dialect

SCHEMA_VERSION = 22

VERSION_TABLE = "schema_version"

_sqlite = sqlite_dialect.dialect()
_ddl_compiler = _sqlite.ddl_compiler(_sqlite, None)

_EXTRA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        actor TEXT,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)",
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_node_health_ts ON node_health_snapshots(ts)",
    "CREATE INDEX IF NOT EXISTS idx_node_health_node_ts ON node_health_snapshots(node_id, ts)",
    """
    CREATE TABLE IF NOT EXISTS traffic_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        total_used REAL NOT NULL,
        active_connections INTEGER NOT NULL,
        online_users INTEGER NOT NULL,
        active_users INTEGER NOT NULL,
        total_users INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)",
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_security_snapshots_ts ON security_snapshots(ts)",
    """
    CREATE TABLE IF NOT EXISTS login_attempts (
        key_hash TEXT PRIMARY KEY,
        attempts TEXT NOT NULL DEFAULT '[]',
        updated REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_traffic_daily (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        bytes INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, day)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_traffic_day ON user_traffic_daily(day)",
)

_lock = threading.Lock()
