# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Owner-only per-node DNS + software-update routes.

The node client seam (``node_client`` in backend.routers.node) is
monkeypatched, so these tests assert route behaviour and payloads without
touching the network.
"""

import uuid as _uuid

from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.node.requests import LONG_TIMEOUT, NodeRequests
from backend.schema._input import NodeCreate


def _owner():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "X-Requested-With": "XMLHttpRequest",
    }


def _node():
    db = SessionLocal()
    try:
        return crud.create_node(
            db,
            NodeCreate(
                name=f"dnsnode_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.88",
                key="test-api-key-12345678",
                tunnel_address="vpn.example.com",
                protocol="tcp",
                ovpn_port=1194,
            ),
            None,
        )
    finally:
        db.close()


def _delete_node(node):
    db = SessionLocal()
    try:
        db.delete(db.merge(node))
        db.commit()
    finally:
        db.close()


class _FakeNR:
    def __init__(self, config_result=True, update_answer=None):
        self.config_result = config_result
        self.update_answer = update_answer
        self.config_calls = []

    def update_config(self, **kwargs):
        self.config_calls.append(kwargs)
        return self.config_result

    def trigger_update(self):
        return self.update_answer


def test_dns_route_forwards_node_settings(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/dns",
            headers=_headers(_owner()),
            json={"dns1": "9.9.9.9", "dns2": "149.112.112.112"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"dns1": "9.9.9.9", "dns2": "149.112.112.112"}
        (call,) = fake.config_calls
        assert call["dns1"] == "9.9.9.9"
        assert call["dns2"] == "149.112.112.112"
        assert call["tunnel_address"] == "vpn.example.com"
        assert call["protocol"] == "tcp"
        assert call["ovpn_port"] == 1194
        assert call["set_new_setting"] is True
    finally:
        _delete_node(node)


def test_dns_route_allows_single_value(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/dns",
            headers=_headers(_owner()),
            json={"dns1": "9.9.9.9"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert fake.config_calls[0]["dns2"] is None
    finally:
        _delete_node(node)


def test_dns_route_surfaces_node_rejection(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=False)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/dns",
            headers=_headers(_owner()),
            json={"dns1": "not-an-ip"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "rejected" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_dns_route_requires_a_value(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/dns",
            headers=_headers(_owner()),
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert fake.config_calls == []
    finally:
        _delete_node(node)


def test_dns_route_404_without_node():
    client = TestClient(api)
    resp = client.put(
        "/api/nodes/424242/dns",
        headers=_headers(_owner()),
        json={"dns1": "9.9.9.9"},
    )
    assert resp.status_code == 404


def test_update_route_mirrors_node_answer(monkeypatch):
    from backend.routers import node as node_router

    answer = {
        "success": True,
        "msg": "Update started in the background — the node restarts when it finishes.",
        "data": {"version": "2.0.2"},
    }
    fake = _FakeNR(update_answer=answer)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(
            f"/api/nodes/{node.id}/update",
            headers=_headers(_owner()),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"version": "2.0.2"}
        assert "Update started" in body["msg"]
    finally:
        _delete_node(node)


def test_update_route_surfaces_node_refusal(monkeypatch):
    from backend.routers import node as node_router

    answer = {
        "success": False,
        "msg": "This node runs in Docker — update the container from the host.",
        "data": None,
    }
    fake = _FakeNR(update_answer=answer)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(f"/api/nodes/{node.id}/update", headers=_headers(_owner()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "container" in body["msg"]
    finally:
        _delete_node(node)


def test_update_route_surfaces_unreachable_node(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(update_answer=None)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(f"/api/nodes/{node.id}/update", headers=_headers(_owner()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "unreachable" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_update_route_404_without_node():
    client = TestClient(api)
    resp = client.post("/api/nodes/424242/update", headers=_headers(_owner()))
    assert resp.status_code == 404


def test_update_config_payload_includes_dns_only_when_provided(monkeypatch):
    seen = {}

    def fake_request(self, method, path, **kw):
        seen.update(method=method, path=path, json=kw.get("json"), timeout=kw.get("timeout"))
        return {"success": True, "data": {}}

    monkeypatch.setattr(NodeRequests, "_request", fake_request)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)

    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194) is True
    assert "dns1" not in seen["json"] and "dns2" not in seen["json"]

    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194, dns1="9.9.9.9") is True
    assert seen["json"]["dns1"] == "9.9.9.9"
    assert "dns2" not in seen["json"]
    assert seen["path"] == "/sync/config"
    assert seen["timeout"] == LONG_TIMEOUT


def test_trigger_update_returns_node_answer_even_on_failure(monkeypatch):
    import backend.node.requests as nr_mod

    seen = {}

    class Resp:
        status_code = 200
        headers = {}

        def json(self):
            return {
                "success": False,
                "msg": "This node runs in Docker — update the container from the host.",
                "data": None,
            }

    def fake_post(url, headers=None, **kw):
        seen.update(url=url, headers=headers, kw=kw)
        return Resp()

    monkeypatch.setattr(nr_mod._req, "post", fake_post)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)
    answer = nr.trigger_update()
    assert answer is not None, "a node refusal must not be swallowed as unreachable"
    assert answer["success"] is False
    assert "container" in answer["msg"]
    assert seen["url"].endswith("/sync/update")
    assert seen["kw"]["timeout"] == LONG_TIMEOUT
