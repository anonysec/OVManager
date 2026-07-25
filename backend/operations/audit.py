from __future__ import annotations
import time
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

def ensure_audit_table(db: Session) -> None:
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

def log_event(db, action, actor=None, target=None, detail=None):
    if db is None:
        from backend.db.engine import SessionLocal
        db = SessionLocal()
        created = True
    else:
        created = False
    try:
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
    ensure_audit_table(db)
    rows = db.execute(
        text("SELECT id, ts, actor, action, target, detail FROM audit_logs ORDER BY ts DESC LIMIT :limit"),
        {"limit": max(1, min(int(limit or 100), 500))},
    ).fetchall()
    return [{"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "target": r[4], "detail": r[5]} for r in rows]
