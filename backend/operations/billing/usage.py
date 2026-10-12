"""Per-user daily traffic history (raw-SQL table, like audit_logs).

The collector attributes each billed delta to today's UTC row, so the panel
can draw per-user graphs and top-talker boards without scanning the
aggregate snapshots. Sparse by design: only days with billed bytes get rows.
"""

from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

_table_ready: bool = False


def ensure_daily_table(db: Session) -> None:
    """Create user_traffic_daily if missing (DDL owned by migrations)."""
    global _table_ready
    from backend.db.migrations import ensure_extra_tables

    ensure_extra_tables(db)
    _table_ready = True


def _today() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


def record_daily_bytes(db: Session, user_id: int, delta: int, day: str | None = None) -> None:
    """Add billed bytes to a user's day row (upsert)."""
    if not delta or delta <= 0:
        return
    if not _table_ready:
        ensure_daily_table(db)
    db.execute(
        text(
            "INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (:uid, :day, :b) "
            "ON CONFLICT(user_id, day) DO UPDATE SET bytes = bytes + :b"
        ),
        {"uid": int(user_id), "day": day or _today(), "b": int(delta)},
    )


def user_daily_series(db: Session, user_id: int, days: int = 14) -> list[dict]:
    """Last N days (UTC) for one user, oldest first, zero-filled."""
    if not _table_ready:
        ensure_daily_table(db)
    days = max(1, min(int(days or 14), 90))
    today = dt.datetime.now(dt.UTC).date()
    wanted = [(today - dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    rows = db.execute(
        text("SELECT day, bytes FROM user_traffic_daily WHERE user_id = :uid AND day >= :start"),
        {"uid": int(user_id), "start": wanted[0]},
    ).fetchall()
    have = {r[0]: int(r[1]) for r in rows}
    return [{"day": d, "bytes": have.get(d, 0)} for d in wanted]


def top_users(db: Session, days: int = 7, limit: int = 5) -> list[dict]:
    """Top users by billed bytes over the last N days (UTC)."""
    if not _table_ready:
        ensure_daily_table(db)
    days = max(1, min(int(days or 7), 90))
    limit = max(1, min(int(limit or 5), 25))
    start = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = db.execute(
        text(
            "SELECT u.name, SUM(d.bytes) AS b FROM user_traffic_daily d "
            "JOIN users u ON u.id = d.user_id "
            "WHERE d.day >= :start GROUP BY u.name ORDER BY b DESC LIMIT :limit"
        ),
        {"start": start, "limit": limit},
    ).fetchall()
    return [{"name": r[0], "bytes": int(r[1])} for r in rows]


def prune_daily(db: Session, keep_days: int = 90) -> int:
    """Delete daily rows older than keep_days. Returns rows removed."""
    if not _table_ready:
        ensure_daily_table(db)
    cutoff = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=max(1, int(keep_days or 90)))).strftime("%Y-%m-%d")
    result = db.execute(text("DELETE FROM user_traffic_daily WHERE day < :cutoff"), {"cutoff": cutoff})
    return int(result.rowcount or 0)


def write_ledger_batch(db: Session, rows: list[dict]) -> int:
    """Insert ledger rows sorted by (user_id, node_id) in one executemany.

    The caller owns the commit, so a whole tick's worth of deltas lands in a
    single transaction. Rows are sorted first so the insert walks the UNIQUE
    (user_id, ts, kind, node_id) index in order and duplicates surface as a
    constraint error instead of a mid-batch surprise.
    """
    if not rows:
        return 0
    ordered = sorted(rows, key=lambda r: (int(r["user_id"]), r["node_id"]))
    db.execute(
        text(
            "INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes, meta_json) "
            "VALUES (:user_id, :ts, :node_id, :kind, :delta_bytes, :meta_json)"
        ),
        [
            {
                "user_id": int(r["user_id"]),
                "ts": float(r["ts"]),
                "node_id": r["node_id"],
                "kind": r["kind"],
                "delta_bytes": int(r["delta_bytes"]),
                "meta_json": r.get("meta_json", "{}"),
            }
            for r in ordered
        ],
    )
    return len(ordered)


def prune_ledger(db: Session, keep_days: int = 90, batch: int = 5000) -> int:
    """Delete ledger rows older than keep_days in LIMIT batches. No inner commit.

    Batched so a very old backlog does not hold one long DELETE lock. The
    caller commits, matching prune_daily.
    """
    if not _table_ready:
        ensure_daily_table(db)
    cutoff = time.time() - max(1, int(keep_days or 90)) * 86400
    batch = max(1, int(batch or 5000))
    total = 0
    while True:
        result = db.execute(
            text("DELETE FROM traffic_ledger WHERE id IN (SELECT id FROM traffic_ledger WHERE ts < :cutoff LIMIT :batch)"),
            {"cutoff": cutoff, "batch": batch},
        )
        removed = int(result.rowcount or 0)
        total += removed
        if removed < batch:
            break
    return total
