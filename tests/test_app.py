"""Basic tests for OVManager panel.

These are environment-aware: the API prefix depends on config.URLPATH, so we
derive the real prefix from the app's config instead of hardcoding /api.
"""
from fastapi.testclient import TestClient

from backend.app import api
from backend.config import config


def _api_prefix():
    urlpath = (config.URLPATH or "").strip("/")
    return f"/{urlpath}/api" if urlpath else "/api"


def test_app_imports():
    """Verify the app can be imported without errors."""
    assert api is not None


def test_health_endpoint():
    client = TestClient(api)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_urlprefixed_health():
    client = TestClient(api)
    response = client.get(f"{_api_prefix()}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
