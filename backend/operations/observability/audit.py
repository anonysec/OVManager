from __future__ import annotations

import json
import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.operations.observability.notifier import send_telegram
from backend.utils.like import escape_like

logger = logging.getLogger(__name__)

_table_ready: bool = False


def ensure_audit_table(db: Session) -> None:
    """Create the audit_logs table and index if not already present.

    The DDL itself lives in :mod:`backend.db.migrations` so schema creation
    has one owner; this wrapper only adds the once-per-process guard.
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


def record_event(db, kind, severity: str = "info", message: str = "", meta: dict | None = None) -> None:
    """Write one system event as an audit row — the unified event pipeline.

    ``detail`` carries JSON ``{"severity", "message", "meta"}`` so the audit
    page can render it and :func:`promote_events` can read it back. Severity
    is ``info`` / ``warning`` / ``error``. ``meta`` is free-form; a
    ``meta["event_key"]`` enrolls the row for Telegram promotion (one send per
    key, see :func:`promote_events`), rows without one are audit-only.
    ``meta["target"]`` also fills the ``target`` column.
    """
    payload = {"severity": severity, "message": message, "meta": meta or {}}
    log_event(db, kind, actor="system", target=(meta or {}).get("target"), detail=json.dumps(payload, default=str))


def last_event_meta(db, kind: str) -> dict | None:
    """Meta of the newest ``record_event`` row for ``kind``, or None.

    This is the persisted transition state: producers compare the current
    condition against it and write a row only when something changed, so a
    restart never replays or forgets a state change.
    """
    if not _table_ready:
        ensure_audit_table(db)
    row = db.execute(
        text("SELECT detail FROM audit_logs WHERE action = :a AND actor = 'system' ORDER BY id DESC LIMIT 1"),
        {"a": kind},
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return meta if isinstance(meta, dict) else None


def promote_events(db, *, send=None) -> int:
    """Deliver enrolled audit events to Telegram, each exactly once.

    ``delivered`` is the sent-marker table (UNIQUE subscription+event_key),
    written only after the sender accepts the message. An enrolled row
    (``meta.event_key``) is sent once; repeats find the marker and stay
    silent; a failed send stays unmarked and retries on the next call — the
    crash window between send and marker can re-spam at most once. Markers
    are never deleted (producers re-announce by recording a fresh row with a
    new event_key), so re-scanning old rows is idempotent.

    ``send`` defaults to :func:`send_telegram`; tests pass a recorder.
    Returns the number of messages sent.
    """
    sender = send or send_telegram
    if db is None:
        from backend.db.engine import SessionLocal

        db = SessionLocal()
        created = True
    else:
        created = False
    sent = 0
    try:
        if not _table_ready:
            ensure_audit_table(db)
        delivered = {(r[0], r[1]) for r in db.execute(text("SELECT subscription, event_key FROM delivered")).fetchall()}
        rows = db.execute(text("SELECT action, detail FROM audit_logs WHERE actor = 'system' ORDER BY id ASC")).fetchall()
        for action, detail in rows:
            try:
                payload = json.loads(detail)
                meta = payload.get("meta") or {}
            except (TypeError, ValueError, AttributeError):
                continue  # plain log_event detail, not a record_event row
            key = meta.get("event_key") if isinstance(meta, dict) else None
            if not key or (action, str(key)) in delivered:
                continue
            message = payload.get("message") if isinstance(payload, dict) else None
            if not sender(str(message or action), db=db):
                continue
            db.execute(
                text("INSERT OR IGNORE INTO delivered (subscription, event_key, ts) VALUES (:s, :k, :ts)"),
                {"s": action, "k": str(key), "ts": time.time()},
            )
            db.commit()
            delivered.add((action, str(key)))
            sent += 1
    except Exception:
        logger.exception("Could not promote audit events")
        try:
            db.rollback()
        except Exception:
            logger.debug("Promote rollback failed", exc_info=True)
    finally:
        if created:
            db.close()
    return sent


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
        clauses.append("action LIKE :action ESCAPE '\\'")
        params["action"] = f"{escape_like(action)}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        text(f"SELECT id, ts, actor, action, target, detail FROM audit_logs {where} ORDER BY ts DESC LIMIT :limit"),
        params,
    ).fetchall()
    return [{"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "target": r[4], "detail": r[5]} for r in rows]


def prune_audit_logs(db, keep_days: int = 90) -> int:
    """Delete audit rows older than keep_days. Returns rows removed.

    audit_logs was the only unbounded table (metrics already retain 30d);
    called from the 15-minute maintenance sweep in app.py.
    """
    if not _table_ready:
        ensure_audit_table(db)
    cutoff = time.time() - max(1, int(keep_days or 90)) * 86400
    result = db.execute(text("DELETE FROM audit_logs WHERE ts < :cutoff"), {"cutoff": cutoff})
    db.execute(text("DELETE FROM delivered WHERE ts < :cutoff"), {"cutoff": cutoff})  # markers die with their rows
    db.commit()
    return int(result.rowcount or 0)
