"""Traffic collector vs. concurrent panel actions.

The collector loads users, awaits node HTTP (seconds), then persists. A
reset-usage or delete landing in that window must win: the collector's write
is conditional and becomes a no-op, and no orphan daily-history row appears.
"""

import asyncio
import datetime as dt
import uuid as _uuid
from types import SimpleNamespace

from sqlalchemy import text

from backend.operations import daily_checks as dc


def _mkrow(name: str, used: int = 0, node_usage: str = "{}") -> int:
    from backend.app import _run_migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    _run_migrations()
    db = SessionLocal()
    try:
        row = User(
            uuid=str(_uuid.uuid4()),
            name=name,
            owner="owner",
            expiry_date=dt.date(2030, 1, 1),
            total=10**12,
            used=used,
            max_logins=1,
            is_active=True,
            node_usage=node_usage,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _drop(name: str) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is not None:
            db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :uid"), {"uid": row.id})
            db.query(User).filter(User.name == name).delete()
            db.commit()
    finally:
        db.close()


def test_reset_during_node_fetch_is_not_overwritten(monkeypatch):
    """A reset that lands while the node is polled must survive the tick."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"race_reset_{_uuid.uuid4().hex[:8]}"
    user_id = _mkrow(name, used=500, node_usage='{"tnode": {"total": 1000}}')
    node = SimpleNamespace(name="tnode", address="127.0.0.1")

    async def fake_fetch(node, db=None):
        other = SessionLocal()
        try:
            row = other.query(User).filter(User.id == user_id).first()
            row.used = 0
            row.node_usage = "{}"
            other.commit()
        finally:
            other.close()
        return {"users": {name: 1500}, "totals": {name: 1500}}

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        assert asyncio.run(dc._collect_node_traffic(node, {name: user}, db)) is True
        db.expire_all()
        row = db.query(User).filter(User.id == user_id).first()
        assert row.used == 0, "reset must not be overwritten by stale collector values"
        assert row.node_usage == "{}"
        daily = db.execute(text("SELECT COUNT(*) FROM user_traffic_daily WHERE user_id = :uid"), {"uid": user_id}).scalar()
        assert daily == 0, "no traffic may be billed for the reset-away delta"
    finally:
        db.close()
        _drop(name)


def test_delete_during_node_fetch_leaves_no_orphan_history(monkeypatch):
    """A user deleted mid-tick must not recreate daily rows for a reused id."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"race_del_{_uuid.uuid4().hex[:8]}"
    user_id = _mkrow(name, used=100, node_usage='{"tnode": {"total": 500}}')
    node = SimpleNamespace(name="tnode", address="127.0.0.1")

    async def fake_fetch(node, db=None):
        other = SessionLocal()
        try:
            other.query(User).filter(User.id == user_id).delete()
            other.commit()
        finally:
            other.close()
        return {"users": {name: 900}, "totals": {name: 900}}

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        assert asyncio.run(dc._collect_node_traffic(node, {name: user}, db)) is True
        db.expire_all()
        assert db.query(User).filter(User.id == user_id).first() is None
        daily = db.execute(text("SELECT COUNT(*) FROM user_traffic_daily WHERE user_id = :uid"), {"uid": user_id}).scalar()
        assert daily == 0, "deleted user must not leave orphan history"
    finally:
        db.close()
        _drop(name)


def test_delta_still_billed_when_row_untouched(monkeypatch):
    """Sanity: the conditional write must not skip legitimate deltas."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    name = f"race_ok_{_uuid.uuid4().hex[:8]}"
    user_id = _mkrow(name, used=100, node_usage='{"tnode": {"total": 500}}')
    node = SimpleNamespace(name="tnode", address="127.0.0.1")

    async def fake_fetch(node, db=None):
        return {"users": {name: 900}, "totals": {name: 900}}

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        assert asyncio.run(dc._collect_node_traffic(node, {name: user}, db)) is True
        db.expire_all()
        row = db.query(User).filter(User.id == user_id).first()
        assert row.used == 500
        daily = db.execute(text("SELECT COUNT(*) FROM user_traffic_daily WHERE user_id = :uid"), {"uid": user_id}).scalar()
        assert daily == 1
    finally:
        db.close()
        _drop(name)
