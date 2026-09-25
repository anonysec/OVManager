# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Owner-only per-node extra VPN ports route.

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
from backend.schema import NodeCreate


def _owner():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _admin_token(username: str) -> str:
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
        return create_session(db, username, "admin")
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
                name=f"portsnode_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.90",
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
    def __init__(self, config_result=True):
        self.config_result = config_result
        self.config_calls = []

    def update_config(self, **kwargs):
        self.config_calls.append(kwargs)
        return self.config_result


def _patch(monkeypatch, fake, events=None):
    from backend.routers import node as node_router

    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    if events is not None:
        monkeypatch.setattr(
            node_router,
            "log_event",
            lambda db, action, **kw: events.append((action, kw)),
        )
    return node_router


def test_ports_route_forwards_extra_ports(monkeypatch):
    fake = _FakeNR(config_result=True)
    events = []
    _patch(monkeypatch, fake, events)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": "443,8443"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"extra_ports": "443,8443"}
        (call,) = fake.config_calls
        assert call["extra_ports"] == "443,8443"
        assert call["tunnel_address"] == "vpn.example.com"
        assert call["protocol"] == "tcp"
        assert call["ovpn_port"] == 1194
        assert call["set_new_setting"] is True
        ((action, kwargs),) = events
        assert action == "node.ports"
        assert kwargs["target"] == node.name
        assert kwargs["actor"]
    finally:
        _delete_node(node)


def test_ports_route_allows_empty_string_to_clear(monkeypatch):
    fake = _FakeNR(config_result=True)
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": ""},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert fake.config_calls[0]["extra_ports"] == ""
    finally:
        _delete_node(node)


def test_ports_route_requires_a_value(monkeypatch):
    fake = _FakeNR(config_result=True)
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(f"/api/nodes/{node.id}/ports", headers=_headers(_owner()), json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "extra_ports" in body["msg"]
        assert fake.config_calls == []
    finally:
        _delete_node(node)


def test_ports_route_surfaces_node_rejection(monkeypatch):
    fake = _FakeNR(config_result=False)
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": "not-a-port"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "rejected" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_ports_route_maps_node_envelope(monkeypatch):
    fake = _FakeNR(
        config_result={
            "success": False,
            "msg": "Invalid extra ports — send comma-separated ports 1-65535.",
            "data": None,
        }
    )
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": "0"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert body["msg"] == "Invalid extra ports — send comma-separated ports 1-65535."
    finally:
        _delete_node(node)


def test_ports_route_maps_node_success_message(monkeypatch):
    fake = _FakeNR(
        config_result={
            "success": True,
            "msg": "Extra ports set to 443. NAT redirects applied.",
            "data": {"extra_ports": "443"},
        }
    )
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": "443"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["msg"] == "Extra ports set to 443. NAT redirects applied."
        assert body["data"] == {"extra_ports": "443"}
    finally:
        _delete_node(node)


def test_ports_route_surfaces_unreachable_node(monkeypatch):
    fake = _FakeNR(config_result=None)
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_owner()),
            json={"extra_ports": "443"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "unreachable" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_ports_route_is_owner_only(monkeypatch):
    fake = _FakeNR(config_result=True)
    _patch(monkeypatch, fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ports",
            headers=_headers(_admin_token(f"portsadmin_{_uuid.uuid4().hex[:6]}")),
            json={"extra_ports": "443"},
        )
        assert resp.status_code == 403
        assert fake.config_calls == []
    finally:
        _delete_node(node)


def test_ports_route_404_without_node():
    client = TestClient(api)
    resp = client.put(
        "/api/nodes/424242/ports",
        headers=_headers(_owner()),
        json={"extra_ports": "443"},
    )
    assert resp.status_code == 404


# ── client payloads ──────────────────────────────────────────────────


def test_update_config_payload_includes_extra_ports_only_when_provided(monkeypatch):
    seen = {}

    def fake_request(self, method, path, **kw):
        seen.update(method=method, path=path, json=kw.get("json"), timeout=kw.get("timeout"))
        return {"success": True, "data": {}}

    monkeypatch.setattr(NodeRequests, "_request", fake_request)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)

    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194) is True
    assert "extra_ports" not in seen["json"]

    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194, extra_ports="443,8443") is True
    assert seen["json"]["extra_ports"] == "443,8443"

    # Empty string is a real value (clear), not "omitted".
    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194, extra_ports="") is True
    assert seen["json"]["extra_ports"] == ""
    assert seen["path"] == "/sync/config"
    assert seen["timeout"] == LONG_TIMEOUT


def test_update_config_return_envelope_surfaces_node_message(monkeypatch):
    class Resp:
        status_code = 200
        headers = {}

        def json(self):
            return {
                "success": False,
                "msg": "Invalid extra ports — send comma-separated ports 1-65535.",
                "data": None,
            }

    def fake_post(url, headers=None, **kw):
        return Resp()

    import backend.node.requests as nr_mod

    monkeypatch.setattr(nr_mod._req, "post", fake_post)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)
    answer = nr.update_config(
        tunnel_address="vpn.example.com",
        protocol="tcp",
        ovpn_port=1194,
        extra_ports="0",
        return_envelope=True,
    )
    assert answer is not None, "a node refusal must not be swallowed as unreachable"
    assert answer["success"] is False
    assert "Invalid extra ports" in answer["msg"]
