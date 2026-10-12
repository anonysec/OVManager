"""Active nodes only, and a stale live snapshot is unknown.

A decommissioned node must not be probed at all — every probe can cost the
full node timeout, so one dead row used to stall the whole poll. And the idle
collector must keep refreshing within its window: a snapshot older than
IDLE_POLL_SECONDS is treated as unknown by every reader (users list,
subscription page, health overview) instead of being served frozen.
"""

import asyncio
import time
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.app import api
from backend.config import config
from backend.operations.observability import live


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _reset_snapshot() -> None:
    live.snapshot._connections = {}
    live.snapshot._nodes = {}
    live.snapshot._last_poll_ts = 0.0
    live._grace_until.clear()


class _FakeNode:
    address = "127.0.0.1"
    port = 1
    key = "k"
    use_tls = False
    id = 1

    def __init__(self, name):
        self.name = name


# ── which nodes a poll touches ──────────────────────────────────────────────


def test_the_traffic_poll_skips_a_decommissioned_node(monkeypatch):
    """A decommissioned node adds no stall time — it is never probed."""
    from backend.db import crud
    from backend.operations.billing import daily

    alive = _FakeNode("alive")
    dead = _FakeNode("dead")
    probed: list[str] = []

    async def fake_traffic(node, db=None, **kwargs):
        probed.append(node.name)
        if node.name == "dead":
            await asyncio.sleep(30)  # what a real node timeout costs
        return {}

    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [alive])
    monkeypatch.setattr(crud, "get_all_nodes", lambda db: [alive, dead])
    monkeypatch.setattr(daily, "get_users_used_traffic", fake_traffic)

    started = time.monotonic()
    asyncio.run(daily.check_user_used_traffic())
    elapsed = time.monotonic() - started

    assert probed == ["alive"], f"only active nodes may be polled, probed {probed}"
    assert elapsed < 5, f"a decommissioned node must add no stall time, took {elapsed:.1f}s"


def test_the_metrics_poll_skips_a_decommissioned_node(monkeypatch):
    from backend.db import crud
    from backend.operations.observability import metrics

    alive = _FakeNode("alive")
    dead = _FakeNode("dead")
    probed: list[str] = []

    async def fake_snapshot(node, panel_id=None):
        probed.append(node.name)
        if node.name == "dead":
            await asyncio.sleep(30)
        row = {
            "node_id": node.id,
            "node_name": node.name,
            "cpu": 1,
            "memory": 1,
            "live_count": 0,
            "latency_ms": 1.0,
            "reachable": 1,
            "auth_errors": 0,
            "rejects": 0,
            "stale_markers": 0,
        }
        return row, {}

    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [alive])
    monkeypatch.setattr(crud, "get_all_nodes", lambda db: [alive, dead])
    monkeypatch.setattr(metrics, "_node_snapshot", fake_snapshot)

    started = time.monotonic()
    asyncio.run(metrics.collect_metrics())
    elapsed = time.monotonic() - started

    assert probed == ["alive"], f"only active nodes may be polled, probed {probed}"
    assert elapsed < 5, f"a decommissioned node must add no stall time, took {elapsed:.1f}s"


# ── snapshot freshness ──────────────────────────────────────────────────────


def test_snapshot_freshness_is_never_polled_then_fresh_then_stale():
    _reset_snapshot()
    assert live.snapshot_fresh() is False, "a snapshot that was never taken is unknown"

    live.snapshot.update({"u1": 1}, {"n1": True})
    assert live.snapshot_fresh() is True

    live.snapshot._last_poll_ts = time.monotonic() - live.IDLE_POLL_SECONDS - 1
    assert live.snapshot_fresh() is False, "a snapshot past the idle window is stale"


def test_the_users_list_never_serves_frozen_connection_counts(monkeypatch):
    """Stale snapshot → fall back to the database, not last week's counts."""
    from backend.db.crud import create_user, get_user_by_name
    from backend.db.engine import SessionLocal
    from backend.schema import CreateUser

    name = f"frozen-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        create_user(db, CreateUser(name=name, expiry_date=date.today() + timedelta(days=30), total=1024), "owner")
    finally:
        db.close()

    monkeypatch.setattr(live, "get_connection_counts", lambda: {name: 3})
    monkeypatch.setattr(live, "snapshot_fresh", lambda: False)

    resp = TestClient(api).get("/api/users/", headers=_owner_headers())
    assert resp.status_code == 200
    match = [u for u in resp.json()["data"]["users"] if u["name"] == name]
    assert match, "seeded user missing from list"
    assert match[0]["active_connections"] == 0, "a stale snapshot must not be served as live counts"

    db = SessionLocal()
    try:
        row = get_user_by_name(db, name)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def test_the_subscription_page_drops_up_links_when_the_snapshot_is_stale(monkeypatch):
    """Frozen "up" links would keep advertising a node long after it died."""
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    token = uuid.uuid4().hex
    node_name = f"freshness-{token[:8]}"
    db = SessionLocal()
    user = User(
        name=f"sub-{token[:8]}",
        uuid=token,
        expiry_date=date.today() + timedelta(days=30),
        total=None,
        used=0,
        is_active=True,
    )
    node = Node(name=node_name, address="127.0.0.1", protocol="tcp", ovpn_port=1194, port=443, key="k", status=True)
    db.add_all([user, node])
    db.commit()
    try:
        # Fresh snapshot with the node up → the link is served.
        _reset_snapshot()
        live.snapshot.update({}, {node_name: True})
        page = TestClient(api).get(f"/sub/{token}")
        assert page.status_code == 200, page.text
        assert node_name in page.text, "a fresh snapshot with the node up must advertise it"

        # Same data, but past the idle window → unknown, no link.
        live.snapshot._last_poll_ts = time.monotonic() - live.IDLE_POLL_SECONDS - 1
        page = TestClient(api).get(f"/sub/{token}")
        assert page.status_code == 200, page.text
        assert node_name not in page.text, "a stale snapshot must never serve frozen up-links"
    finally:
        db.delete(user)
        db.delete(node)
        db.commit()
        db.close()


def test_the_health_check_reports_a_stale_snapshot_as_unknown():
    from backend.db.engine import SessionLocal
    from backend.db.models import Node
    from backend.routers.health import _check_nodes

    node_name = f"stale-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    node = Node(name=node_name, address="127.0.0.1", protocol="tcp", ovpn_port=1194, port=443, key="k", status=True)
    db.add(node)
    db.commit()
    try:
        _reset_snapshot()
        live.snapshot.update({}, {node_name: True})
        entry = _check_nodes(db)
        assert entry["status"] == "ok"
        assert entry["detail"]["nodes"][0]["reachable"] is True

        live.snapshot._last_poll_ts = time.monotonic() - live.IDLE_POLL_SECONDS - 1
        entry = _check_nodes(db)
        assert entry["status"] == "warn", "stale live data must not read as healthy"
        assert "stale" in entry["summary"].lower()
        assert entry["detail"]["nodes"][0]["reachable"] is False, "a stale snapshot reports unknown, not up"
    finally:
        db.delete(node)
        db.commit()
        db.close()
