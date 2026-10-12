"""Batched sorted ledger upsert: one executemany, sorted (user_id, node_id)."""

import time

import backend.operations.billing.usage as u


def test_write_ledger_batch_sorts_rows_and_commits_once(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        u.ensure_daily_table(db)
        monkeypatch.setattr(u, "_table_ready", True)

        now = time.time()
        rows = [
            {
                "user_id": i + 1,
                "ts": now,
                "node_id": "node0",
                "kind": "poll",
                "delta_bytes": 1,
            }
            for i in range(1000)
        ]
        rows.reverse()  # feed them out of order on purpose

        captured: list = []
        real_execute = db.execute

        def spy(stmt, params=None):
            if isinstance(params, list):
                captured.append(params)
            return real_execute(stmt, params)

        monkeypatch.setattr(db, "execute", spy)
        committed: list = []
        monkeypatch.setattr(db, "commit", lambda: committed.append(1))

        count = u.write_ledger_batch(db, rows)
        db.commit()

        assert count == 1000
        assert committed == [1], "one commit per tick"
        assert len(captured) == 1, "the whole batch must be a single executemany"
        keys = [(r["user_id"], r["node_id"]) for r in captured[0]]
        assert keys == sorted(keys), "ledger rows must be sorted by (user_id, node_id)"
    finally:
        db.rollback()
        db.close()


def test_write_ledger_batch_empty_is_noop():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        u.ensure_daily_table(db)
        assert u.write_ledger_batch(db, []) == 0
    finally:
        db.rollback()
        db.close()
