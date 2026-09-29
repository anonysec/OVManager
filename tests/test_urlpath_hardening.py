"""URLPATH hardening: route-table-derived reserved prefixes + CLI reset."""

import pytest
from fastapi.testclient import TestClient

from backend.app import api
from backend.config import config
from backend.urlpath import reserved_prefixes


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def test_reserved_prefixes_derived_from_routes():
    """The reserved set comes from the live route table, not a hardcoded list."""
    reserved = reserved_prefixes()
    assert {"api", "assets", "health"} <= reserved
    assert config.SUBSCRIPTION_PATH.strip("/").lower() in reserved
    assert not any(seg.startswith("{") for seg in reserved)


def test_route_derived_prefix_rejected_over_http():
    """A route-derived prefix (not in any static list) is refused end to end."""
    from backend.urlpath import set_urlpath

    client = TestClient(api)
    try:
        resp = client.put("/api/server/settings/urlpath", json={"urlpath": "health"}, headers=_owner_headers())
        assert resp.status_code == 200
        assert resp.json()["success"] is False
    finally:
        set_urlpath("")


def test_reset_urlpath_clears_prefix_and_cache():
    from backend.urlpath import get_urlpath, reset_urlpath, set_urlpath

    set_urlpath("lockedoutpath")
    assert get_urlpath() == "lockedoutpath"
    assert reset_urlpath() is True
    assert get_urlpath() == ""


def test_reset_urlpath_cli_flag():
    """main.py --reset-urlpath exits 0 and clears the prefix."""
    import subprocess
    import sys

    from backend.urlpath import set_urlpath

    set_urlpath("clireset")
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "--reset-urlpath"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0
        assert "root" in proc.stdout
    finally:
        from backend.urlpath import invalidate_cache

        invalidate_cache()


def test_set_urlpath_rejects_reserved_prefixes():
    """The write path itself must refuse reserved prefixes: the settings
    router validates user input, but main.py's CLI path and any future
    writer would otherwise shadow live routes and lock the operator out."""
    from backend.urlpath import reserved_prefixes, set_urlpath

    for evil in ("api", "assets", "health", "doc", "openapi.json"):
        with pytest.raises(ValueError, match="reserved"):
            set_urlpath(evil)
    assert "api" in reserved_prefixes()
    assert set_urlpath("mysecret") == "mysecret"
    assert set_urlpath("") == ""
