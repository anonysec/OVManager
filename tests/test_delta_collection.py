"""Cursor-based delta collection: ledger row + cursor move in one txn (Task 7)."""

import asyncio
import uuid as _uuid
from types import SimpleNamespace

from backend.operations.billing import daily as dc


def _mkrow(name: str, used: int = 0, node_usage: str = "{}"):
    import datetime as dt

    from backend.app import _run_migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    _run_migrations()
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is None:
            row = User(uuid=str(_uuid.uuid4()), name=name)
            db.add(row)
        row.expiry_date = dt.date(2030, 1, 1)
        row.total = 10 * 1024**3
        row.used = used
        row.max_logins = 1
        row.is_active = True
        row.node_usage = node_usage
        db.commit()
        # A dropped user's id can be reused; purge any orphaned ledger rows.
        from sqlalchemy import text

        db.execute(text("DELETE FROM traffic_ledger WHERE user_id = :uid"), {"uid": row.id})
        db.commit()
        return row.uuid
    finally:
        db.close()


def _drop(name: str):
    from sqlalchemy import text

    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is not None:
            db.execute(text("DELETE FROM traffic_ledger WHERE user_id = :uid"), {"uid": row.id})
            db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :uid"), {"uid": row.id})
            db.query(User).filter(User.name == name).delete()
            db.commit()
    finally:
        db.close()


def _ledger_rows(name: str) -> list[tuple]:
    from sqlalchemy import text

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        uid = db.execute(text("SELECT id FROM users WHERE name = :n"), {"n": name}).scalar()
        return db.execute(
            text("SELECT node_id, kind, delta_bytes FROM traffic_ledger WHERE user_id = :uid ORDER BY id"),
            {"uid": uid},
        ).fetchall()
    finally:
        db.close()


def _cursor(name: str) -> str:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.name == name).first().node_usage
    finally:
        db.close()


def _run(coro):
    return asyncio.run(coro)


def _poll(monkeypatch, name: str, totals: dict, node_name: str = "tnode"):
    """Drive one _collect_node_traffic pass against a stubbed node payload."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    node = SimpleNamespace(name=node_name, address="127.0.0.1")

    async def fake_fetch(_node, db=None):
        return {"users": dict(totals), "sessions": {}, "totals": dict(totals)}

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == name).first()
        return _run(dc._collect_node_traffic(node, {name: user}, db))
    finally:
        db.close()


def test_poll_writes_ledger_row_and_moves_cursor(monkeypatch):
    name = f"dc_poll_{_uuid.uuid4().hex[:8]}"
    _mkrow(name)
    try:
        _poll(monkeypatch, name, {name: 1000})  # baseline: no billing, cursor set
        assert _ledger_rows(name) == [], "first sight must only baseline"
        # canonical form: compact separators, sorted keys — must not regress to json.dumps default
        assert _cursor(name) == '{"tnode":{"total":1000}}'

        _poll(monkeypatch, name, {name: 1300})  # growth: delta 300
        rows = _ledger_rows(name)
        assert len(rows) == 1, f"one ledger row per growth poll, got {rows}"
        assert rows[0][0] == "tnode" and rows[0][1] == "poll" and rows[0][2] == 300
        assert _cursor(name) == '{"tnode":{"total":1300}}'
    finally:
        _drop(name)


def test_same_cumulative_repolled_yields_zero_rows(monkeypatch):
    name = f"dc_same_{_uuid.uuid4().hex[:8]}"
    _mkrow(name)
    try:
        _poll(monkeypatch, name, {name: 1000})
        _poll(monkeypatch, name, {name: 1300})
        assert len(_ledger_rows(name)) == 1

        _poll(monkeypatch, name, {name: 1300})  # identical cumulative
        assert len(_ledger_rows(name)) == 1, "an unchanged cumulative must not add a row"
    finally:
        _drop(name)


def test_crash_before_commit_redelivers_exactly_once(monkeypatch):
    name = f"dc_crash_{_uuid.uuid4().hex[:8]}"
    _mkrow(name)
    try:
        _poll(monkeypatch, name, {name: 1000})  # baseline
        assert _ledger_rows(name) == []

        from backend.db.engine import SessionLocal
        from backend.db.models import User

        node = SimpleNamespace(name="tnode", address="127.0.0.1")

        async def fake_fetch(_node, db=None):
            return {"users": {name: 1500}, "sessions": {}, "totals": {name: 1500}}

        monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)

        db = SessionLocal()
        try:
            real_commit = db.commit

            def crash():
                raise RuntimeError("simulated crash before commit")

            db.commit = crash
            try:
                user = db.query(User).filter(User.name == name).first()
                _run(dc._collect_node_traffic(node, {name: user}, db))
            except RuntimeError:
                pass
            db.rollback()
            db.commit = real_commit
        finally:
            db.close()

        assert _ledger_rows(name) == [], "a crash before commit must leave no ledger row"
        assert _cursor(name) == '{"tnode":{"total":1000}}', "cursor must not move on a crash"

        _poll(monkeypatch, name, {name: 1500})  # redelivery of the same cumulative
        rows = _ledger_rows(name)
        assert len(rows) == 1, f"redelivery must insert exactly once, got {rows}"
        assert rows[0][2] == 500
    finally:
        _drop(name)


def test_reset_advances_cursor_next_delta_zero(monkeypatch):
    name = f"dc_reset_{_uuid.uuid4().hex[:8]}"
    _mkrow(name)
    try:
        _poll(monkeypatch, name, {name: 1000})
        _poll(monkeypatch, name, {name: 1600})
        assert len(_ledger_rows(name)) == 1

        # panel:reset re-baselines the cursor without calling the node
        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            row = db.query(User).filter(User.name == name).first()
            row.used = 0
            row.node_usage = "{}"
            db.commit()
        finally:
            db.close()

        _poll(monkeypatch, name, {name: 1600})  # same cumulative after reset
        assert len(_ledger_rows(name)) == 1, "a reset must not manufacture a delta"
    finally:
        _drop(name)
