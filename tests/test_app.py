"""Basic tests for OVManager panel."""
import pytest
from fastapi.testclient import TestClient


def test_app_imports():
    """Verify the app can be imported without errors."""
    from backend.app import api
    assert api is not None


def test_config_loads():
    """Verify config loads with defaults."""
    from backend.config import config
    assert config.PORT == 9000  # default


def test_health_endpoint():
    """Test the public health check endpoint."""
    from backend.app import api
    client = TestClient(api)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_urlprefixed_health():
    """Test the URL-prefixed health check endpoint."""
    from backend.app import api
    client = TestClient(api)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"