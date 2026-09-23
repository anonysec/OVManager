# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for the node_client() construction seam + decrypt cache.

node_client() is the single place a Node row becomes a NodeRequests;
decrypt_node_key() is lru_cached so per-tick fan-outs don't pay a Fernet
decrypt per node per RPC.
"""

from types import SimpleNamespace

from backend.db import crud
from backend.node.requests import NodeRequests, node_client


def _node():
    return SimpleNamespace(address="10.0.0.9", port=2083, key="plain-key", use_tls=False)


def test_node_client_maps_row_fields():
    req = node_client(_node())
    assert isinstance(req, NodeRequests)
    assert req.address == "10.0.0.9:2083"
    assert req.headers == {"key": "plain-key"}
    assert req.scheme == "http"


def test_node_client_tls_scheme():
    req = node_client(SimpleNamespace(address="10.0.0.9", port=2083, key="k", use_tls=True))
    assert req.scheme == "https"


def test_decrypt_cache_returns_same_result():
    crud.decrypt_node_key.cache_clear()
    try:
        assert crud.decrypt_node_key("plain-key") == "plain-key"
        assert crud.decrypt_node_key("plain-key") == "plain-key"
        info = crud.decrypt_node_key.cache_info()
        assert info.hits >= 1
    finally:
        crud.decrypt_node_key.cache_clear()


def test_retry_after_parsing():
    from backend.node.requests import _retry_after_s

    assert _retry_after_s("7") == 7.0
    assert _retry_after_s(None) == 5.0
    assert _retry_after_s("garbage") == 5.0
    assert _retry_after_s("9999") == 60.0  # capped
    assert _retry_after_s("0") == 1.0  # floored


def test_send_retries_once_on_429_then_succeeds(monkeypatch):
    import backend.node.requests as nr_mod

    calls = []

    class Resp:
        def __init__(self, status, headers=None, payload=None):
            self.status_code = status
            self.headers = headers or {}
            self._payload = payload or {"success": True, "data": {}}

        def json(self):
            return self._payload

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        if len(calls) == 1:
            return Resp(429, {"Retry-After": "0"})
        return Resp(200)

    monkeypatch.setattr(nr_mod._req, "get", fake_get)
    monkeypatch.setattr(nr_mod._time, "sleep", lambda s: None)
    req = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)
    assert req._request("get", "/sync/status") == {"success": True, "data": {}}
    assert len(calls) == 2


def test_node_version_compat_policy():
    """Panel must distinguish node versions: same major is compatible,
    newer nodes are flagged, other majors and garbage are not compatible."""
    from backend.node.ops import node_version_compat
    from backend.version import __version__

    major = __version__.split(".")[0]
    assert node_version_compat(__version__)["verdict"] == "compatible"
    assert node_version_compat(f"{major}.0.0")["verdict"] == "compatible"
    assert node_version_compat("v" + __version__)["verdict"] == "compatible"
    newer = node_version_compat("9999.0.0")
    assert newer["verdict"] in ("node-newer", "incompatible"), newer
    assert node_version_compat("0.0.1")["verdict"] == "incompatible"
    for bad in (None, "", "not-a-version", "1.x"):
        assert node_version_compat(bad)["verdict"] == "unknown", bad
