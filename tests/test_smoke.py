# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Smoke tests for the OVManager API.

Routes are at /api/... (no prefix). These tests verify the public surface
and the auth gate on settings mutations.
"""

from fastapi.testclient import TestClient

from backend.app import api


def test_health_is_public():
    client = TestClient(api)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_settings_requires_auth():
    client = TestClient(api)
    # No auth header -> should be rejected (401/403), not 200.
    res = client.put("/api/server/settings/subscription", json={})
    assert res.status_code in (401, 403)


def test_timezone_update_requires_auth():
    client = TestClient(api)
    res = client.put("/api/server/settings/timezone", json={"timezone": "UTC"})
    assert res.status_code in (401, 403)


def test_urlpath_update_requires_main_admin():
    client = TestClient(api)
    res = client.put("/api/server/settings/urlpath", json={"urlpath": "test"})
    # Should be rejected (401 for no auth, or 403 for non-main-admin)
    assert res.status_code in (401, 403)


def test_version_reported():
    from backend.version import __version__

    assert __version__
