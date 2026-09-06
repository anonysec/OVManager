# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Per-user daily traffic history: record/upsert, series, top, prune."""

import datetime as dt

from sqlalchemy import text

from backend.app import _run_migrations
from backend.db.engine import SessionLocal
from backend.operations import usage_history as uh


def _db():
    _run_migrations()
    return SessionLocal()


def _uid():
    import uuid as _uuid

    return 424000 + int(_uuid.uuid4().hex[:6], 16) % 999


def test_record_upserts_same_day():
    uid = _uid()
    db = _db()
    try:
        uh.record_daily_bytes(db, uid, 100)
        uh.record_daily_bytes(db, uid, 50)
        uh.record_daily_bytes(db, uid, 0)  # no-op
        uh.record_daily_bytes(db, uid, -5)  # no-op
        db.commit()
        series = uh.user_daily_series(db, uid, days=1)
        assert series == [{"day": uh._today(), "bytes": 150}]
    finally:
        db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :u"), {"u": uid})
        db.commit()
        db.close()


def test_series_zero_fills_and_orders():
    uid2a, uid2b = _uid(), _uid()
    db = _db()
    try:
        uh.record_daily_bytes(db, uid2a, 10)
        db.commit()
        series = uh.user_daily_series(db, uid2a, days=3)
        assert [s["day"] for s in series] == sorted(s["day"] for s in series)
        assert series[-1] == {"day": uh._today(), "bytes": 10}
        assert series[0]["bytes"] == 0
        empty = uh.user_daily_series(db, uid2b, days=2)
        assert all(s["bytes"] == 0 for s in empty)
    finally:
        db.execute(text("DELETE FROM user_traffic_daily WHERE user_id IN (:a, :b)"), {"a": uid2a, "b": uid2b})
        db.commit()
        db.close()


def test_prune_drops_old_days():
    uid3 = _uid()
    db = _db()
    try:
        old = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=100)).strftime("%Y-%m-%d")
        uh.record_daily_bytes(db, uid3, 10, day=old)
        uh.record_daily_bytes(db, uid3, 20)
        db.commit()
        assert uh.prune_daily(db, keep_days=90) == 1
        series = uh.user_daily_series(db, uid3, days=1)
        assert series == [{"day": uh._today(), "bytes": 20}]
    finally:
        db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :u"), {"u": uid3})
        db.commit()
        db.close()


def test_top_users_sums_and_orders():
    import uuid as _uuid

    from backend.db.models import User

    db = _db()
    try:
        ids = []
        for _i, name in enumerate(("tt_top_a", "tt_top_b")):
            u = User(
                uuid=str(_uuid.uuid4()),
                name=f"{name}_{_uuid.uuid4().hex[:6]}",
                owner="owner",
                expiry_date=dt.date(2030, 1, 1),
            )
            db.add(u)
            db.flush()
            ids.append(u.id)
        uh.record_daily_bytes(db, ids[0], 100)
        uh.record_daily_bytes(db, ids[1], 300)
        db.commit()
        top = uh.top_users(db, days=7, limit=5)
        b = next(t for t in top if t["name"].startswith("tt_top_b"))
        assert b["bytes"] == 300
        a = next(t for t in top if t["name"].startswith("tt_top_a"))
        assert a["bytes"] == 100
        assert top.index(b) < top.index(a), "ordered desc"
        # owner scoping excludes others' users
        assert uh.top_users(db, days=7, limit=5, owner="nobody") == []
    finally:
        for uid in ids:
            db.query(User).filter(User.id == uid).delete()
        db.execute(text("DELETE FROM user_traffic_daily"))
        db.commit()
        db.close()
