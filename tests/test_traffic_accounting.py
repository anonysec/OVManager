# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Traffic accounting: per-session deltas never double-count, enforce works.

Covers backend/operations/daily_checks.py:
- _compute_session_delta: accurate path, first-seen, legacy fallback, reset.
- _extract_username: dashed usernames keep working.
- _collect_node_traffic (node fetch stubbed): second identical poll adds 0;
  reconnects count only new sessions; unknown users are skipped.
- enforce_user_limits (node push stubbed): expired + over-quota users are
  deactivated in the DB, healthy users untouched.
"""

import asyncio
import datetime as dt
import uuid as _uuid
from types import SimpleNamespace

from backend.operations import daily_checks as dc


def _mkrow(name: str, **fields):
    from backend.app import _run_migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    _run_migrations()
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is None:
            row = User(uuid=str(_uuid.uuid4()), name=name, owner="owner")
            db.add(row)
        row.expiry_date = fields.get("expiry_date", dt.date(2030, 1, 1))
        row.total = fields.get("total", 10 * 1024**3)
        row.used = fields.get("used", 0)
        row.max_logins = fields.get("max_logins", 1)
        row.is_active = fields.get("is_active", True)
        row.node_usage = fields.get("node_usage", "{}")
        db.commit()
        return row.uuid
    finally:
        db.close()


def _drop(name: str):
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        db.query(User).filter(User.name == name).delete()
        db.commit()
    finally:
        db.close()


def _used(name: str):
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.name == name).first().used
    finally:
        db.close()


# ── delta unit tests ──────────────────────────────────────────────


def test_delta_accurate_path_diffs_per_session():
    delta, state = dc._compute_session_delta({"s1": 1000, "s2": 500}, {"s1": 800, "s2": 500}, 1500)
    assert delta == 200
    assert state == {"s1": 1000, "s2": 500}


def test_delta_counts_reset_counters_as_new_bytes():
    # Node rebooted / counter wrapped: cur < last → count cur, never negative.
    delta, _ = dc._compute_session_delta({"s1": 50}, {"s1": 9000}, 50)
    assert delta == 50


def test_delta_first_seen_subtracts_legacy_baseline():
    delta, state = dc._compute_session_delta({"s1": 1200}, 200, 1200)
    assert delta == 1000
    assert state == {"s1": 1200}


def test_delta_legacy_fallback_without_sessions():
    delta, state = dc._compute_session_delta(None, 300, 900)
    assert delta == 600
    assert state == 900


def test_extract_username_keeps_dashes():
    assert dc._extract_username("john-doe-eu1", "eu1") == "john-doe"
    assert dc._extract_username("alice-eu1", "eu1") == "alice"


# ── collector integration (stubbed node fetch) ────────────────────


def _run(coro):
    return asyncio.run(coro)


def test_collect_never_double_counts(monkeypatch):
    from backend.db.engine import SessionLocal

    name = f"tt_collect_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=0)
    node = SimpleNamespace(name="tnode", address="127.0.0.1")
    payloads = [
        {"users": {f"{name}-tnode": 1000}, "sessions": {f"{name}-tnode": {"s1": 1000}}},
        {"users": {f"{name}-tnode": 1000}, "sessions": {f"{name}-tnode": {"s1": 1000}}},
        # Reconnect: old session gone, new one carries 300 fresh bytes.
        {"users": {f"{name}-tnode": 1300}, "sessions": {f"{name}-tnode": {"s2": 300}}},
        # Unknown users in the payload must not crash the run.
        {"users": {"ghost-tnode": 5}, "sessions": {"ghost-tnode": {"g": 5}}},
    ]

    async def fake_fetch(node, db=None):
        return payloads.pop(0)

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    try:
        db = SessionLocal()
        try:
            from backend.db.models import User

            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 1000
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 1000  # identical poll: +0
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 1300  # only the new session counted
            db.expire_all()
            # Unknown users in the payload: run completes, our user untouched.
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 1300
        finally:
            db.close()
    finally:
        _drop(name)


def test_enforce_disables_expired_and_over_quota(monkeypatch):
    expired = f"tt_exp_{_uuid.uuid4().hex[:8]}"
    over = f"tt_over_{_uuid.uuid4().hex[:8]}"
    healthy = f"tt_ok_{_uuid.uuid4().hex[:8]}"
    _mkrow(expired, expiry_date=dt.date.today() - dt.timedelta(days=1))
    _mkrow(over, total=1000, used=1500)
    _mkrow(healthy)
    pushed = []

    async def fake_push(*args, **kwargs):
        pushed.append(kwargs.get("name") or (args[1] if len(args) > 1 else None))
        return True

    monkeypatch.setattr(dc, "change_user_status_on_all_nodes", fake_push)
    try:
        _run(dc.enforce_user_limits())
        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            states = {u.name: u.is_active for u in db.query(User).filter(User.name.in_([expired, over, healthy])).all()}
        finally:
            db.close()
        assert states[expired] is False
        assert states[over] is False
        assert states[healthy] is True
        assert set(pushed) == {expired, over}
    finally:
        _drop(expired)
        _drop(over)
        _drop(healthy)
