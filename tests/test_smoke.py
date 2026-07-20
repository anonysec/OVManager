"""Smoke tests for the OVManager API.

These run against the in-process app via Starlette's TestClient (no real
network, no external nodes). They verify the public surface and the auth
gate on settings mutations. The API prefix is derived from config.URLPATH
so the tests are correct whether or not the panel is installed under a subpath.
"""
from fastapi.testclient import TestClient

from backend.app import api
from backend.config import config


def _api_prefix():
    urlpath = (config.URLPATH or "").strip("/")
    return f"/{urlpath}/api" if urlpath else "/api"


def test_health_is_public():
    client = TestClient(api)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_settings_requires_auth():
    client = TestClient(api)
    # No auth header -> should be rejected (401/403), not 200.
    res = client.put(f"{_api_prefix()}/server/settings/subscription", json={})
    assert res.status_code in (401, 403)


def test_timezone_update_requires_auth():
    client = TestClient(api)
    res = client.put(f"{_api_prefix()}/server/settings/timezone", json={"timezone": "UTC"})
    assert res.status_code in (401, 403)


def test_version_reported():
    from backend.version import __version__

    assert __version__
