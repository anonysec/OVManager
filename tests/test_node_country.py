# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Node country: manual override wins, auto-lookup is validated, and the
frontend never invents a country from the node name.

Regression: node "node-1" (116.203.55.47, Germany, NULL country_code in DB)
rendered as Netherlands because normalizeCountryCode fuzzy-matched the
lowercase-stripped node name against country initials.
"""

import uuid as _uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import api
from backend.db import crud
from backend.operations import geolocation as geo_mod
from backend.schema._input import NodeCreate


def _node_payload(**overrides):
    base = {
        "name": f"geo_{_uuid.uuid4().hex[:8]}",
        "address": "203.0.113.9",
        "tunnel_address": "",
        "protocol": "tcp",
        "ovpn_port": 1194,
        "port": 2083,
        "key": "test-api-key-12345678",
        "status": True,
        "set_new_setting": False,
        "use_tls": True,
    }
    base.update(overrides)
    return NodeCreate(**base)


def _db():
    from backend.db.engine import SessionLocal

    return SessionLocal()


# --- geolocate payload validation (no network; httpx2 is stubbed) ---


def _fake_get(payload):
    def _get(*args, **kwargs):
        class _Resp:
            def json(self):
                return payload

        return _Resp()

    return _get


def test_geolocate_accepts_good_payload(monkeypatch):
    monkeypatch.setattr(
        geo_mod.httpx2,
        "get",
        _fake_get({"status": "success", "countryCode": "de", "lat": 49.45, "lon": 11.07}),
    )
    assert geo_mod.geolocate("203.0.113.9") == {
        "country_code": "DE",
        "latitude": 49.45,
        "longitude": 11.07,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "fail", "message": "private range"},
        {"status": "success", "countryCode": "", "lat": 1.0, "lon": 1.0},
        {"status": "success", "countryCode": "XX1", "lat": 1.0, "lon": 1.0},
        {"status": "success", "countryCode": "DE", "lat": 91.0, "lon": 1.0},
        {"status": "success", "countryCode": "DE", "lat": "x", "lon": 1.0},
    ],
)
def test_geolocate_rejects_junk_payloads(monkeypatch, payload):
    monkeypatch.setattr(geo_mod.httpx2, "get", _fake_get(payload))
    assert geo_mod.geolocate(f"203.0.113.{abs(hash(str(payload))) % 250 + 1}") is None


def test_geolocate_retries_then_gives_up(monkeypatch):
    calls = []

    def _flaky(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("boom")

    monkeypatch.setattr(geo_mod.httpx2, "get", _flaky)
    assert geo_mod.geolocate("203.0.113.10") is None
    assert len(calls) == 2  # initial + one retry, failures never cached


# --- crud precedence: manual > auto > keep ---


def test_create_node_manual_country_wins_over_geo():
    db = _db()
    try:
        node = crud.create_node(
            db,
            _node_payload(country_code="de"),
            {"country_code": "FR", "latitude": 1.0, "longitude": 2.0},
        )
        try:
            assert node.country_code == "DE"
            assert node.latitude is None
            assert node.longitude is None
        finally:
            db.delete(node)
            db.commit()
    finally:
        db.close()


def test_create_node_geo_used_when_no_manual():
    db = _db()
    try:
        node = crud.create_node(
            db,
            _node_payload(),
            {"country_code": "DE", "latitude": 49.45, "longitude": 11.07},
        )
        try:
            assert node.country_code == "DE"
            assert node.latitude == pytest.approx(49.45)
        finally:
            db.delete(node)
            db.commit()
    finally:
        db.close()


def test_update_node_manual_clears_stale_geo():
    db = _db()
    try:
        node = crud.create_node(
            db,
            _node_payload(),
            {"country_code": "NL", "latitude": 52.1, "longitude": 5.3},
        )
        try:
            updated = crud.update_node(db, node.id, _node_payload(name=node.name, country_code="DE"), None)
            assert updated.country_code == "DE"
            assert updated.latitude is None
            assert updated.longitude is None
        finally:
            db.delete(node)
            db.commit()
    finally:
        db.close()


def test_update_node_failed_lookup_keeps_old_value():
    db = _db()
    try:
        node = crud.create_node(
            db,
            _node_payload(),
            {"country_code": "DE", "latitude": 49.45, "longitude": 11.07},
        )
        try:
            updated = crud.update_node(db, node.id, _node_payload(name=node.name), None)
            assert updated.country_code == "DE"
        finally:
            db.delete(node)
            db.commit()
    finally:
        db.close()


def test_update_node_rejects_bad_country_code():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NodeCreate(
            **{
                "name": "x",
                "address": "203.0.113.9",
                "country_code": "XXXX",
            }
        )


# --- API: PUT /nodes/{id} persists the override (handler level) ---


def test_api_update_node_manual_country_wins(monkeypatch):
    import backend.node.ops as ops_mod
    from backend.auth.sessions import create_session
    from backend.config import config

    # Auto-lookup claims FR; the form says DE — DE must win, no node contact.
    monkeypatch.setattr(
        ops_mod, "geolocate", lambda address: {"country_code": "FR", "latitude": 1.0, "longitude": 2.0}
    )
    db = _db()
    try:
        node = crud.create_node(db, _node_payload(), None)
        try:
            client = TestClient(api)
            raw = create_session(db, config.ADMIN_USERNAME, "owner")
            token = raw
            resp = client.put(
                f"/api/nodes/{node.id}",
                json={
                    "name": node.name,
                    "address": "203.0.113.9",
                    "tunnel_address": "",
                    "protocol": "tcp",
                    "ovpn_port": 1194,
                    "port": 2083,
                    "key": "",
                    "status": True,
                    "set_new_setting": False,
                    "use_tls": True,
                    "country_code": "de",
                },
                headers={"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["success"] is True
            db.refresh(node)
            assert node.country_code == "DE"
            assert node.latitude is None
        finally:
            db.delete(node)
            db.commit()
    finally:
        db.close()
