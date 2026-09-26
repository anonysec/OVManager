"""Traffic accounting: totals-based billing never double-counts, enforce works.

Covers backend/operations/daily_checks.py:
- _compute_session_delta: accurate path, first-seen, legacy fallback, reset.
- _extract_username: exact match wins, legacy -node suffix stripped, unknown
  keys pass through unmangled (dashed names are never billed to mangled names).
- _collect_node_traffic (node fetch stubbed): lifetime totals billed on
  growth only; baselines on first sight/reset; banked-only payloads bill;
  drops bill zero and rebaseline; numeric CNs resolve via id map.
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
    from sqlalchemy import text

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


def _used(name: str):
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.name == name).first().used
    finally:
        db.close()


def test_delta_accurate_path_diffs_per_session():
    delta, state = dc._compute_session_delta({"s1": 1000, "s2": 500}, {"s1": 800, "s2": 500}, 1500)
    assert delta == 200
    assert state == {"s1": 1000, "s2": 500}


def test_delta_counts_reset_counters_as_new_bytes():
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


def test_extract_username_exact_match_wins():
    assert dc._extract_username("john-doe", "node-1", {"john-doe"}) == "john-doe"
    assert dc._extract_username("ghost-9", "node-1", {"alice"}) == "ghost-9"


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
        {"users": {f"{name}-tnode": 1300}, "sessions": {f"{name}-tnode": {"s2": 300}}},
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
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 1300
        finally:
            db.close()
    finally:
        _drop(name)


def test_collect_totals_bills_growth_rebaselines_drops(monkeypatch):
    """Lifetime totals: growth billed, identical +0, drops bill 0 and
    rebaseline (reset/daemon restart can only shrink the counter)."""
    from backend.db.engine import SessionLocal

    name = f"tt_tot_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=0)
    node = SimpleNamespace(name="tnode", address="127.0.0.1")
    payloads = [
        {"users": {name: 1000}, "sessions": {name: {"s1": 1000}}, "totals": {name: 1000}},
        {"users": {name: 1000}, "sessions": {name: {"s1": 1000}}, "totals": {name: 1000}},
        {"users": {name: 500}, "sessions": {name: {"s2": 500}}, "totals": {name: 1800}},
        {"users": {name: 500}, "sessions": {name: {"s2": 500}}, "totals": {name: 300}},
    ]

    async def fake_fetch(node, db=None):
        return payloads.pop(0)

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    try:
        db = SessionLocal()
        try:
            from backend.db.models import User

            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 0  # first sight: baseline, no billing
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 0  # identical: +0
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 800  # banked completion billed once
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 800  # drop: +0, rebaselined
        finally:
            db.close()
    finally:
        _drop(name)


def test_collect_banked_only_payload_bills_offline_bytes(monkeypatch):
    """Node reports only totals (user offline, sessions gone): the completed
    bytes must still be billed — previously silently dropped."""
    from backend.db.engine import SessionLocal

    name = f"tt_bank_{_uuid.uuid4().hex[:8]}"
    _mkrow(name, used=100)
    node = SimpleNamespace(name="tnode", address="127.0.0.1")
    payloads = [
        {"users": {}, "sessions": {}, "totals": {name: 700}},
        {"users": {}, "sessions": {}, "totals": {name: 950}},
    ]

    async def fake_fetch(node, db=None):
        return payloads.pop(0)

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    try:
        db = SessionLocal()
        try:
            from backend.db.models import User

            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 100  # baseline, nothing billed yet
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {name: db.query(User).filter(User.name == name).first()}, db)) is True
            assert _used(name) == 350  # offline-completed bytes billed
        finally:
            db.close()
    finally:
        _drop(name)


def test_collect_dashed_username_billed_not_mangled(monkeypatch):
    """Bare dashed usernames (what nodes send) bill to the exact user."""
    from backend.db.engine import SessionLocal

    base = f"tt-dash-{_uuid.uuid4().hex[:6]}"
    _mkrow(base, used=0)
    node = SimpleNamespace(name="tnode", address="127.0.0.1")
    payloads = [
        {"users": {base: 400}, "sessions": {}, "totals": {base: 400}},
        {"users": {base: 900}, "sessions": {}, "totals": {base: 900}},
    ]

    async def fake_fetch(node, db=None):
        return payloads.pop(0)

    monkeypatch.setattr(dc, "get_users_used_traffic", fake_fetch)
    try:
        db = SessionLocal()
        try:
            from backend.db.models import User

            assert _run(dc._collect_node_traffic(node, {base: db.query(User).filter(User.name == base).first()}, db)) is True
            db.expire_all()
            assert _run(dc._collect_node_traffic(node, {base: db.query(User).filter(User.name == base).first()}, db)) is True
            assert _used(base) == 500, "dashed user must be billed exactly once"
        finally:
            db.close()
    finally:
        _drop(base)


def test_reset_usage_fans_out_to_nodes(monkeypatch):
    """Panel reset must zero node banked files too (best-effort per node)."""
    from backend.node import ops as node_ops

    nodes = [
        SimpleNamespace(id=1, name="n1", address="10.0.0.1", port=2083, use_tls=True),
        SimpleNamespace(id=2, name="n2", address="10.0.0.2", port=2083, use_tls=True),
    ]
    called = []

    class FakeNR:
        def __init__(self, address=None, port=None, api_key=None, use_tls=None):
            pass

        def reset_usage(self, uid):
            called.append(uid)
            return uid != "9"

    monkeypatch.setattr(node_ops.crud, "get_active_nodes", lambda db: nodes)
    monkeypatch.setattr(node_ops, "node_client", lambda node, **kw: FakeNR())
    import backend.db.engine as _eng

    db = _eng.SessionLocal()
    try:
        out = _run(node_ops.reset_user_usage_on_all_nodes(7, db))
        assert called == ["7", "7"], out
        assert out == {"ok": True, "failed": []}
    finally:
        db.close()


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
