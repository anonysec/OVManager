import backend.operations.billing.usage as u


def test_prune_daily_no_inner_commit(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        u.ensure_daily_table(db)
        monkeypatch.setattr(u, "_table_ready", True)
        committed = []
        monkeypatch.setattr(db, "commit", lambda: committed.append(1))
        u.prune_daily(db, keep_days=90)
        assert committed == []
    finally:
        db.rollback()
        db.close()
