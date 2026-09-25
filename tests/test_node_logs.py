# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Node log viewer plumbing: client validation + proxy route passthrough."""

import uuid as _uuid

from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.node.requests import NodeRequests
from backend.schema import NodeCreate


def _owner():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _node():
    db = SessionLocal()
    try:
        return crud.create_node(
            db,
            NodeCreate(
                name=f"lognode_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.77",
                key="test-api-key-12345678",
            ),
            None,
        )
    finally:
        db.close()


def test_get_logs_validates_level_and_limit(monkeypatch):
    seen = {}

    def fake_request(self, method, path, **kw):
        seen.update(method=method, path=path, kw=kw)
        return {"data": {"records": []}}

    monkeypatch.setattr(NodeRequests, "_request", fake_request)
    nr = NodeRequests.__new__(NodeRequests)
    out = NodeRequests.get_logs(nr, level="bogus", limit=9999)
    assert out == {"records": []}
    assert seen["kw"]["params"] == {"level": "WARNING", "limit": 500}
    out = NodeRequests.get_logs(nr, level="error", limit=10)
    assert seen["kw"]["params"] == {"level": "ERROR", "limit": 10}


def test_node_logs_proxy_passthrough(monkeypatch):
    from backend.routers import node as node_router

    calls = {}

    class FakeNR:
        def __init__(self, **kw):
            calls.update(kw)

        def get_logs(self, level="WARNING", limit=100):
            calls.update(level=level, limit=limit)
            return {"records": [{"level": "ERROR", "message": "boom"}], "errors_1h": 1}

    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: FakeNR())
    node = _node()
    try:
        client = TestClient(api)
        token = _owner()
        resp = client.get(
            f"/api/nodes/{node.id}/logs",
            params={"level": "error", "limit": "10"},
            headers={"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["records"] == [{"level": "ERROR", "message": "boom"}]
        assert calls["level"] == "error" and calls["limit"] == 10
    finally:
        db = SessionLocal()
        try:
            db.delete(db.merge(node))
            db.commit()
        finally:
            db.close()


def test_node_logs_proxy_404_without_node():
    client = TestClient(api)
    token = _owner()
    resp = client.get(
        "/api/nodes/424242/logs",
        headers={"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 404
