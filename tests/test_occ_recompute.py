"""OCC-miss recompute: a concurrent reset/delete never silently drops a delta (Gate 2 #1)."""

import asyncio
import json
import uuid as _uuid
from types import SimpleNamespace

from backend.operations.billing import daily as dc


def _mkrow(name: str, used: int, node_usage: dict):
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
        row.node_usage = json.dumps(node_usage)
        db.commit()
        from sqlalchemy import text

        db.execute(text("DELETE FROM traffic_ledger WHERE user_id = :uid"), {"uid": row.id})
        db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :uid"), {"uid": row.id})
        db.commit()
        return row.id
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


def _concurrent(sql: str, params: dict) -> None:
    """Apply a write from a separate connection, mid-collect."""
    from sqlalchemy import text

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text(sql), params)
        db.commit()
    finally:
        db.close()


def _row(name: str):
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == name).first()
        return (user.used, json.loads(user.node_usage or "{}")) if user else None
    finally:
        db.close()


def _ledger(name: str) -> list[tuple]:
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


def _run_collect(db, user, totals: dict, node_name: str = "tnode"):
    node = SimpleNamespace(name=node_name, address="127.0.0.1")

    async def fake_fetch(_node, db=None):
        return {"users": dict(totals), "sessions": {}, "totals": dict(totals)}

    original = dc.get_users_used_traffic
    dc.get_users_used_traffic = fake_fetch
    try:
        return asyncio.run(dc._collect_node_traffic(node, {user.name: user}, db))
    finally:
        dc.get_users_used_traffic = original


def test_concurrent_used_bump_preserves_the_delta():
    """Another writer bumped `used`; this tick's delta must still land."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"occ_bump_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=0, node_usage={"tnode": {"total": 1000}})
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.name == name).first()
            # a concurrent session (another node's tick) bumps used only
            _concurrent("UPDATE users SET used = :u WHERE name = :n", {"u": 700, "n": name})

            _run_collect(db, user, {name: 1500})
        finally:
            db.close()

        used, state = _row(name)
        assert used == 1200, "the delta must be applied on top of the fresh used, not dropped"
        assert state["tnode"]["total"] == 1500, "the cursor must advance to the polled total"
        assert _ledger(name) == [("tnode", "poll", 500)], "the delta must reach the ledger exactly once"
    finally:
        _drop(name)


def test_concurrent_reset_rebaselines_instead_of_dropping():
    """A mid-collect reset must re-baseline the cursor, then bill from there."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"occ_reset_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=0, node_usage={"tnode": {"total": 1000}})
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.name == name).first()
            _concurrent("UPDATE users SET used = 0, node_usage = '{}' WHERE name = :n", {"n": name})

            _run_collect(db, user, {name: 1500})
            used, state = _row(name)
            assert used == 0, "a reset keeps used at zero"
            assert state == {}, "the reset must survive: the cursor stays wiped, not overwritten"
            assert _ledger(name) == [], "the wiped delta must not be billed after a reset"

            _run_collect(db, user, {name: 1700})  # re-baseline poll
            assert _ledger(name) == [], "the re-baseline poll bills nothing"
            db.refresh(user)  # the sweep's stale mechanism refreshes before the next node
            _run_collect(db, user, {name: 1900})
        finally:
            db.close()

        assert _ledger(name) == [("tnode", "poll", 200)], "the next poll must bill from the re-baselined cursor"
    finally:
        _drop(name)


def test_deleted_row_never_crashes_the_tick():
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"occ_del_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=0, node_usage={"tnode": {"total": 1000}})
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.name == name).first()
            _concurrent("DELETE FROM users WHERE name = :n", {"n": name})

            assert _run_collect(db, user, {name: 1500}) is True, "the tick must survive a mid-collect delete"
        finally:
            db.close()

        assert _row(name) is None
        assert _ledger(name) == [], "a deleted user must not leave an orphan ledger row"
    finally:
        _drop(name)
