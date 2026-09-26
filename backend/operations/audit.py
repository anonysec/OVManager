from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_table_ready: bool = False


def ensure_audit_table(db: Session) -> None:
    """Create the audit_logs table and index if not already present.

    Called once at startup (via app.py's lifespan). log_event() skips this
    check after the first successful call. The DDL itself lives in
    :mod:`backend.db.migrations` so schema creation has one owner.
    """
    global _table_ready
    from backend.db.migrations import ensure_extra_tables

    ensure_extra_tables(db)
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
        if not _table_ready:
            ensure_audit_table(db)
        db.execute(
            text("INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (:ts, :actor, :action, :target, :detail)"),
            {"ts": time.time(), "actor": actor, "action": action, "target": target, "detail": detail},
        )
        db.commit()
    except Exception:
        logger.exception("Could not write audit event %s", action)
        try:
            db.rollback()
        except Exception:
            logger.debug("Audit rollback failed", exc_info=True)
    finally:
        if created:
            db.close()


def recent_events(db, limit=100, actor: str | None = None, action: str | None = None):
    """Return recent audit events, newest first.

    When ``actor`` is given, only events performed by that actor are returned
    — non-owner admins must not see other tenants' activity (targets can
    contain other admins' usernames). ``action`` is a prefix filter
    (``user`` matches ``user.create``); the AuditLog page still filters
    client-side, this serves API consumers and large tables.
    """
    if not _table_ready:
        ensure_audit_table(db)
    limit = max(1, min(int(limit or 100), 500))
    clauses = []
    params: dict = {"limit": limit}
    if actor is None:
        pass
    else:
        clauses.append("actor = :actor")
        params["actor"] = actor
    if action:
        clauses.append("action LIKE :action")
        params["action"] = f"{action}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        text(f"SELECT id, ts, actor, action, target, detail FROM audit_logs {where} ORDER BY ts DESC LIMIT :limit"),
        params,
    ).fetchall()
    return [{"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "target": r[4], "detail": r[5]} for r in rows]


def prune_audit_logs(db, keep_days: int = 90) -> int:
    """Delete audit rows older than keep_days. Returns rows removed.

    audit_logs was the only unbounded table (metrics already retain 30d).
    Called from the 15-minute maintenance sweep in app.py.
    """
    if not _table_ready:
        ensure_audit_table(db)
    cutoff = time.time() - max(1, int(keep_days or 90)) * 86400
    result = db.execute(text("DELETE FROM audit_logs WHERE ts < :cutoff"), {"cutoff": cutoff})
    db.commit()
    return int(result.rowcount or 0)
