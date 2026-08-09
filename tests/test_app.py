"""Basic tests for OVManager panel.

Routes are registered at /api/... (no prefix). The URLPathMiddleware handles
any dynamic prefix at the ASGI level. These tests use TestClient which
exercises the app directly, so they test the unprefixed routes.
"""
from fastapi.testclient import TestClient

from backend.app import api


def test_app_imports():
    """Verify the app can be imported without errors."""
    assert api is not None


def test_health_endpoint():
    client = TestClient(api)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_users_requires_auth():
    """API endpoints require authentication."""
    client = TestClient(api)
    response = client.get("/api/users/")
    assert response.status_code in (401, 403)


def test_refresh_token_cannot_access_api():
    """Refresh tokens are not valid API bearer tokens."""
    from backend.auth.auth import create_access_token, create_refresh_token

    client = TestClient(api)
    access = create_access_token({"sub": "admin", "role": "main_admin"})
    refresh = create_refresh_token({"sub": "admin", "role": "main_admin"})
    assert client.get("/api/server/info", headers={"Authorization": f"Bearer {access}"}).status_code == 200
    assert client.get("/api/server/info", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401


def test_urlpath_middleware_blocks_non_matching():
    """When URLPATH is set, non-matching paths get empty response.
    But /assets/ and /health are always allowed through."""
    from backend.urlpath import set_urlpath

    client = TestClient(api)
    try:
        set_urlpath("mysecret")
        # Matching path: should be handled
        response = client.get("/mysecret/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Non-matching path: should get empty 200
        response = client.get("/other-path")
        assert response.status_code == 200
        assert response.content == b""

        # /health without prefix is now allowed through (not blocked)
        response = client.get("/health")
        assert response.status_code == 200
    finally:
        set_urlpath("")


def test_urlpath_empty_serves_root():
    """When URLPATH is empty, all paths are served at root."""
    from backend.urlpath import set_urlpath

    client = TestClient(api)
    try:
        set_urlpath("")
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        set_urlpath("")
