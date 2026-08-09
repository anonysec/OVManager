from __future__ import annotations
import time
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

# Set to True once the table has been confirmed to exist, so log_event()
# does not call CREATE TABLE IF NOT EXISTS on every write.
_table_ready: bool = False


def ensure_audit_table(db: Session) -> None:
    """Create the audit_logs table and index if not already present.

    Called once at startup (via app.py's startup_event). log_event() skips
    this check after the first successful call.
    """
    global _table_ready
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            actor TEXT,
            action TEXT NOT NULL,
            target TEXT,
            detail TEXT
        )
    """))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)"))
    db.commit()
    _table_ready = True


def log_event(db, action, actor=None, target=None, detail=None):
    global _table_ready
    if db is None:
        from backend.db.engine import SessionLocal
        db = SessionLocal()
        created = True
    else:
        created = False
    try:
        # Only create the table if startup didn't do it yet (e.g. first boot
        # before migrations, or tests that skip startup).
        if not _table_ready:
            ensure_audit_table(db)
        db.execute(
            text("INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (:ts, :actor, :action, :target, :detail)"),
            {"ts": time.time(), "actor": actor, "action": action, "target": target, "detail": detail},
        )
        db.commit()
    finally:
        if created:
            db.close()


def recent_events(db, limit=100):
    if not _table_ready:
        ensure_audit_table(db)
    rows = db.execute(
        text("SELECT id, ts, actor, action, target, detail FROM audit_logs ORDER BY ts DESC LIMIT :limit"),
        {"limit": max(1, min(int(limit or 100), 500))},
    ).fetchall()
    return [{"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "target": r[4], "detail": r[5]} for r in rows]
