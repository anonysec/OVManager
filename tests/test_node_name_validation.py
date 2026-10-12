"""Non-empty node names at every write path.

An empty or whitespace-only name saves a blank ledger row: audit targets and
ledger sentinels fall back to ``node.name or str(node_id)``, so a blank name
makes events indistinguishable. Reject at the schema (HTTP 422) and at crud
(direct/CLI callers, ValueError).
"""

import uuid as _uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.schema import NodeCreate

BLANKS = ["", "   ", "\t\n "]


def _payload(**overrides):
    base = {
        "name": f"namenode_{_uuid.uuid4().hex[:8]}",
        "address": "203.0.113.90",
        "key": "test-api-key-12345678",
        "tunnel_address": "vpn.example.com",
        "protocol": "tcp",
        "ovpn_port": 1194,
    }
    base.update(overrides)
    return NodeCreate(**base)


def _owner_token():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _headers():
    return {
        "Authorization": f"Bearer {_owner_token()}",
        "X-Requested-With": "XMLHttpRequest",
    }


# --- schema boundary (drives the router's 422) ------------------------------


@pytest.mark.parametrize("bad", BLANKS)
def test_schema_rejects_blank_name(bad):
    with pytest.raises(ValueError, match="(?i)name"):
        _payload(name=bad)


def test_schema_keeps_normal_name():
    assert _payload(name="edge-1").name == "edge-1"


# --- crud write path --------------------------------------------------------


@pytest.mark.parametrize("bad", BLANKS)
def test_crud_create_rejects_blank_name(bad):
    db = SessionLocal()
    try:
        payload = _payload()
        payload.name = bad  # bypasses the schema on purpose: crud must not trust it
        with pytest.raises(ValueError, match="(?i)name"):
            crud.create_node(db, payload, None)
    finally:
        db.close()


@pytest.mark.parametrize("bad", BLANKS)
def test_crud_update_rejects_blank_name(bad):
    db = SessionLocal()
    node = crud.create_node(db, _payload(), None)
    try:
        payload = _payload(name=node.name)
        payload.name = bad
        with pytest.raises(ValueError, match="(?i)name"):
            crud.update_node(db, node.id, payload, None)
        db.refresh(node)
        assert node.name != bad and node.name.strip() != ""
    finally:
        db.delete(node)
        db.commit()
        db.close()


def test_crud_create_and_update_accept_normal_name():
    db = SessionLocal()
    node = crud.create_node(db, _payload(), None)
    try:
        assert node.name.startswith("namenode_")
        renamed = crud.update_node(db, node.id, _payload(name="edge-renamed"), None)
        assert renamed.name == "edge-renamed"
    finally:
        db.delete(node)
        db.commit()
        db.close()


# --- router write paths -----------------------------------------------------


def _error_names(detail):
    return [err["loc"][-1] for err in detail]


@pytest.mark.parametrize("bad", BLANKS)
def test_add_node_route_rejects_blank_name(bad):
    with TestClient(api) as client:
        r = client.post(
            "/api/nodes/",
            headers=_headers(),
            json={**_payload(name="edge-x").model_dump(), "name": bad},
        )
        assert r.status_code == 422, r.text
        assert "name" in _error_names(r.json()["detail"])


@pytest.mark.parametrize("bad", BLANKS)
def test_update_node_route_rejects_blank_name(bad):
    with TestClient(api) as client:
        r = client.put(
            "/api/nodes/999999",
            headers=_headers(),
            json={**_payload(name="edge-x").model_dump(), "name": bad},
        )
        assert r.status_code == 422, r.text
        assert "name" in _error_names(r.json()["detail"])


def test_update_node_route_accepts_normal_name():
    """A valid name never 422s: the route runs and reports the missing node."""
    with TestClient(api) as client:
        r = client.put(
            "/api/nodes/999999",
            headers=_headers(),
            json=_payload(name="edge-normal").model_dump(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is False
        assert "not found" in r.json()["msg"].lower()
