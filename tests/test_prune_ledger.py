"""prune_ledger: deletes old rows in LIMIT batches, no inner commit."""

import time

from sqlalchemy import text

import backend.operations.billing.usage as u


def _seed(db, n_old: int, n_recent: int) -> None:
    now = time.time()
    old_ts = now - 100 * 86400  # 100 days old
    recent_ts = now - 1 * 86400  # 1 day old
    for i in range(n_old):
        db.execute(
            text("INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes) VALUES (:u, :t, :n, 'poll', 1)"),
            {"u": i + 1, "t": old_ts, "n": "node0"},
        )
    for i in range(n_recent):
        db.execute(
            text("INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes) VALUES (:u, :t, :n, 'poll', 1)"),
            {"u": 1000 + i, "t": recent_ts, "n": "node0"},
        )
    db.commit()


def test_prune_ledger_batches_and_leaves_commit_to_caller(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        u.ensure_daily_table(db)
        monkeypatch.setattr(u, "_table_ready", True)
        db.execute(text("DELETE FROM traffic_ledger"))
        db.commit()
        _seed(db, n_old=5, n_recent=3)

        deletes: list = []
        real_execute = db.execute

        def spy(stmt, params=None):
            if "DELETE FROM traffic_ledger" in str(stmt):
                deletes.append(params)
            return real_execute(stmt, params)

        monkeypatch.setattr(db, "execute", spy)
        committed: list = []
        monkeypatch.setattr(db, "commit", lambda: committed.append(1))

        removed = u.prune_ledger(db, keep_days=90, batch=2)

        assert committed == [], "prune_ledger must leave the commit to the caller"
        assert removed == 5, "only the >90d rows go"
        assert len(deletes) >= 2, "old rows must be deleted in LIMIT batches"
        left = db.execute(text("SELECT COUNT(*) FROM traffic_ledger")).scalar()
        assert left == 3, "recent rows must remain"
    finally:
        db.rollback()
        db.close()
