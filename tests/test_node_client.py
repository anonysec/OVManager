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
