# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Owner-only per-node server-certificate renewal route.

The node client seam (``node_client`` in backend.routers.node) is
monkeypatched, so these tests assert route behaviour without any network.
"""

import uuid as _uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.routers import node as node_router
from backend.schema._input import AdminCreate, NodeCreate


def _owner():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _headers(token):
    return {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}


def _node():
    db = SessionLocal()
    try:
        return crud.create_node(
            db,
            NodeCreate(
                name=f"renew_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.90",
                key="test-api-key-12345678",
                protocol="udp",
                ovpn_port=1194,
                port=2083,
                use_tls=True,
            ),
        )
    finally:
        db.close()


@pytest.fixture()
def node():
    """A throwaway node row, removed afterwards.

    Leftover rows would be probed by other tests (the collector fans out to
    every node), so cleanup is not optional.
    """
    created = _node()
    try:
        yield created
    finally:
        from backend.db.models import Node

        db = SessionLocal()
        try:
            db.query(Node).filter(Node.id == created.id).delete()
            db.commit()
        finally:
            db.close()


class _FakeRequests:
    def __init__(self, answer):
        self.answer = answer
        self.called = 0

    def renew_server_cert(self):
        self.called += 1
        return self.answer


def test_renew_cert_success_is_audited(node, monkeypatch):
    fake = _FakeRequests(
        {
            "success": True,
            "msg": "Server certificate renewed; OpenVPN restarted",
            "data": {"server_expiry": "2028-01-01"},
        }
    )
    monkeypatch.setattr(node_router, "node_client", lambda n, **kw: fake)
    client = TestClient(api)
    r = client.post(f"/api/nodes/{node.id}/renew-cert", headers=_headers(_owner()))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["server_expiry"] == "2028-01-01"
    assert fake.called == 1

    from backend.operations.audit import recent_events

    db = SessionLocal()
    try:
        events = [e for e in recent_events(db, limit=50) if e["action"] == "node.renew_cert" and e["target"] == node.name]
    finally:
        db.close()
    assert events, "renewal must be audited"


def test_renew_cert_surfaces_node_refusal(node, monkeypatch):
    fake = _FakeRequests({"success": False, "msg": "Server certificate renewal failed — check the node logs", "data": None})
    monkeypatch.setattr(node_router, "node_client", lambda n, **kw: fake)
    client = TestClient(api)
    body = client.post(f"/api/nodes/{node.id}/renew-cert", headers=_headers(_owner())).json()
    assert body["success"] is False
    assert "renewal failed" in body["msg"]


def test_renew_cert_unreachable_node(node, monkeypatch):
    monkeypatch.setattr(node_router, "node_client", lambda n, **kw: _FakeRequests(None))
    client = TestClient(api)
    body = client.post(f"/api/nodes/{node.id}/renew-cert", headers=_headers(_owner())).json()
    assert body["success"] is False
    assert "unreachable" in body["msg"]


def test_renew_cert_missing_node(monkeypatch):
    monkeypatch.setattr(node_router, "node_client", lambda n, **kw: _FakeRequests({"success": True}))
    client = TestClient(api)
    r = client.post("/api/nodes/99999999/renew-cert", headers=_headers(_owner()))
    assert r.status_code == 404


def test_renew_cert_requires_owner(node, monkeypatch):
    monkeypatch.setattr(node_router, "node_client", lambda n, **kw: _FakeRequests({"success": True}))
    db = SessionLocal()
    try:
        username = f"renew_admin_{_uuid.uuid4().hex[:8]}"
        crud.create_admin(db, AdminCreate(username=username, password="renew-admin-password-1"))
        token = create_session(db, username, "admin")
    finally:
        db.close()
    client = TestClient(api)
    r = client.post(f"/api/nodes/{node.id}/renew-cert", headers=_headers(token))
    assert r.status_code == 403
