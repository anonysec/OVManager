# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Fan-out dedup: login_health_summary must poll /sync/sessions once per node.

It used to fan out itself AND call get_active_connection_counts() (which
fanned out again for the same live_sessions). Active counts are now derived
from its own payload — same numbers, half the node traffic.
"""

import pytest

from backend.app import _run_migrations


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


def _seed(node_name="dup_node", user_name="dup_user"):
    import uuid as _uuid

    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    _run_migrations()
    db = SessionLocal()
    try:
        node = db.query(Node).filter(Node.name == node_name).first()
        if node is None:
            node = Node(
                name=node_name,
                address="127.0.0.1",
                protocol="udp",
                ovpn_port=1194,
                port=2083,
                key="x" * 32,
                status=True,
                use_tls=False,
            )
            db.add(node)
        else:
            node.status = True
        user = db.query(User).filter(User.name == user_name).first()
        if user is None:
            user = User(
                uuid=str(_uuid.uuid4()),
                name=user_name,
                owner="owner",
                expiry_date=__import__("datetime").date(2030, 1, 1),
                max_logins=1,
                is_active=True,
            )
            db.add(user)
        db.commit()
        return str(user.id)
    finally:
        db.close()


def test_health_summary_polls_each_node_once(monkeypatch):
    import backend.node.diagnostics as diag
    from backend.db.engine import SessionLocal

    uid = _seed()
    calls: list[str] = []

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True, **kwargs):
            pass

        def get_sessions(self, common_name=None, hours=8):
            calls.append(common_name)
            return {
                "live_sessions": [{"common_name": uid, "virtual_address": "10.8.0.2"}],
                "sessions": [],
                "stale_markers": [],
                "live_count": 1,
                "stale_marker_count": 0,
                "auth_errors": 0,
                "auth_errors_by_cn": {},
                "rejects": 0,
                "management_available": True,
            }

    monkeypatch.setattr(diag, "NodeRequests", FakeRequests)
    import asyncio

    db = SessionLocal()
    try:
        out = asyncio.run(diag.login_health_summary(db, hours=8))
    finally:
        db.close()
    # One sessions poll for the single active node (was two before dedup).
    assert len(calls) == 1
    assert out["totals"]["online"] == 1
    row = next(u for u in out["users"] if u["name"] == "dup_user")
    assert row["active_connections"] == 1
    assert row["status"] == "online"
    # Leave no active node rows behind: the dev DB is shared across test
    # files and an active 127.0.0.1 row would add probes to other tests.
    db = SessionLocal()
    try:
        from backend.db.models import Node

        db.query(Node).filter(Node.name == "dup_node").update({"status": False})
        db.commit()
    finally:
        db.close()
