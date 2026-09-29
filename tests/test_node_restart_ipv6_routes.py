"""Owner-only node restart + per-node IPv6 routes.

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
                name=f"ipv6node_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.89",
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
    def __init__(self, config_result=True, restart_answer=None):
        self.config_result = config_result
        self.restart_answer = restart_answer
        self.config_calls = []
        self.restart_calls = 0

    def update_config(self, **kwargs):
        self.config_calls.append(kwargs)
        return self.config_result

    def restart_vpn(self):
        self.restart_calls += 1
        return self.restart_answer


def test_restart_route_returns_node_result(monkeypatch):
    from backend.routers import node as node_router

    answer = {
        "success": True,
        "msg": "OpenVPN restart command completed",
        "data": {"openvpn_running": True},
    }
    fake = _FakeNR(restart_answer=answer)
    events = []
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    monkeypatch.setattr(
        node_router,
        "log_event",
        lambda db, action, **kw: events.append((action, kw)),
    )
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(f"/api/nodes/{node.id}/restart", headers=_headers(_owner()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"openvpn_running": True}
        assert fake.restart_calls == 1
        ((action, kwargs),) = events
        assert action == "node.restart"
        assert kwargs["target"] == node.name
        assert kwargs["actor"]
    finally:
        _delete_node(node)


def test_restart_route_surfaces_node_failure(monkeypatch):
    from backend.routers import node as node_router

    answer = {
        "success": False,
        "msg": "OpenVPN restart failed: no service manager found",
        "data": {"openvpn_running": False},
    }
    fake = _FakeNR(restart_answer=answer)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(f"/api/nodes/{node.id}/restart", headers=_headers(_owner()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "no service manager" in body["msg"]
        assert body["data"] == {"openvpn_running": False}
    finally:
        _delete_node(node)


def test_restart_route_surfaces_unreachable_node(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(restart_answer=None)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.post(f"/api/nodes/{node.id}/restart", headers=_headers(_owner()))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "unreachable" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_restart_route_404_without_node():
    client = TestClient(api)
    resp = client.post("/api/nodes/424242/restart", headers=_headers(_owner()))
    assert resp.status_code == 404


def test_ipv6_route_forwards_node_settings(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ipv6",
            headers=_headers(_owner()),
            json={"enable_ipv6": True, "ipv6_prefix": "fd42:1:2:3::/64"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"enable_ipv6": True, "ipv6_prefix": "fd42:1:2:3::/64"}
        (call,) = fake.config_calls
        assert call["enable_ipv6"] is True
        assert call["ipv6_prefix"] == "fd42:1:2:3::/64"
        assert call["tunnel_address"] == "vpn.example.com"
        assert call["protocol"] == "tcp"
        assert call["ovpn_port"] == 1194
        assert call["set_new_setting"] is True
    finally:
        _delete_node(node)


def test_ipv6_route_allows_disable_only(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ipv6",
            headers=_headers(_owner()),
            json={"enable_ipv6": False},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert fake.config_calls[0]["enable_ipv6"] is False
        assert fake.config_calls[0]["ipv6_prefix"] is None
    finally:
        _delete_node(node)


def test_ipv6_route_requires_a_value(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=True)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(f"/api/nodes/{node.id}/ipv6", headers=_headers(_owner()), json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert fake.config_calls == []
    finally:
        _delete_node(node)


def test_ipv6_route_surfaces_node_rejection(monkeypatch):
    from backend.routers import node as node_router

    fake = _FakeNR(config_result=False)
    monkeypatch.setattr(node_router, "node_client", lambda node, **kw: fake)
    node = _node()
    try:
        client = TestClient(api)
        resp = client.put(
            f"/api/nodes/{node.id}/ipv6",
            headers=_headers(_owner()),
            json={"enable_ipv6": True, "ipv6_prefix": "not-a-prefix"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert "rejected" in body["msg"].lower()
    finally:
        _delete_node(node)


def test_ipv6_route_404_without_node():
    client = TestClient(api)
    resp = client.put(
        "/api/nodes/424242/ipv6",
        headers=_headers(_owner()),
        json={"enable_ipv6": True},
    )
    assert resp.status_code == 404


def test_update_config_payload_includes_ipv6_only_when_provided(monkeypatch):
    seen = {}

    def fake_request(self, method, path, **kw):
        seen.update(method=method, path=path, json=kw.get("json"), timeout=kw.get("timeout"))
        return {"success": True, "data": {}}

    monkeypatch.setattr(NodeRequests, "_request", fake_request)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)

    assert nr.update_config(tunnel_address="vpn.example.com", protocol="tcp", ovpn_port=1194) is True
    assert "enable_ipv6" not in seen["json"] and "ipv6_prefix" not in seen["json"]

    assert (
        nr.update_config(
            tunnel_address="vpn.example.com",
            protocol="tcp",
            ovpn_port=1194,
            enable_ipv6=False,
            ipv6_prefix="fd42:1:2:3::/64",
        )
        is True
    )
    assert seen["json"]["enable_ipv6"] is False
    assert seen["json"]["ipv6_prefix"] == "fd42:1:2:3::/64"
    assert seen["path"] == "/sync/config"
    assert seen["timeout"] == LONG_TIMEOUT


def test_restart_vpn_returns_node_failure_envelope(monkeypatch):
    import backend.node.requests as nr_mod

    seen = {}

    class Resp:
        status_code = 200
        headers = {}

        def json(self):
            return {
                "success": False,
                "msg": "OpenVPN restart failed",
                "data": {"openvpn_running": False},
            }

    def fake_post(url, headers=None, **kw):
        seen.update(url=url, headers=headers, kw=kw)
        return Resp()

    monkeypatch.setattr(nr_mod._req, "post", fake_post)
    nr = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)
    answer = nr.restart_vpn()
    assert answer is not None, "a node restart failure must not be swallowed as unreachable"
    assert answer["success"] is False
    assert answer["data"] == {"openvpn_running": False}
    assert seen["url"].endswith("/sync/restart")
    assert seen["headers"] == {"key": "k"}
    assert seen["kw"]["timeout"] == LONG_TIMEOUT
