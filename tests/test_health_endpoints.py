"""Tests for backend/routers/health.py (owner overview + setup checklist).

This router is not registered in backend/routers/__init__.py yet (the
coordinating agent owns that), so the tests mount it on a dedicated app.
Once registration lands these tests keep working unchanged.

These tests share the dev SQLite database with the rest of the suite, so every
row uses a unique ``hh_`` name and is deleted in a ``finally`` block.
"""

import datetime as dt
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import config
from backend.routers.health import router as health_router
from backend.version import __version__

_app = FastAPI()
_app.include_router(health_router, prefix="/api")

_RUN_DATE = dt.date.today

_CHECK_IDS = ["panel", "database", "nodes", "tls", "disk", "backups"]


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    """Serve at root like the other API test files do."""
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


def _client() -> TestClient:
    return TestClient(_app)


def _headers(username: str, role: str) -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, username, role)
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _owner_headers() -> dict:
    return _headers(config.ADMIN_USERNAME, "owner")


def _create_admin(username: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def _create_user(name: str, owner: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import CreateUser

    db = SessionLocal()
    try:
        if crud.get_user_by_name(db, name) is None:
            req = CreateUser(name=name, expiry_date=_RUN_DATE() + dt.timedelta(days=30), total=1024)
            crud.create_user(db, req, owner)
    finally:
        db.close()


def _create_node(name: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import NodeCreate

    db = SessionLocal()
    try:
        if crud.get_node_by_name(db, name) is None:
            payload = NodeCreate(
                name=name,
                address="203.0.113.77",
                tunnel_address="",
                protocol="tcp",
                port=2083,
                key="hh-test-key-12345678",
                status=True,
            )
            crud.create_node(db, payload)
    finally:
        db.close()


def _cleanup_user(name: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        if crud.get_user_by_name(db, name) is not None:
            crud.delete_user(db, name)
    finally:
        db.close()


def _cleanup_node(name: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        node = crud.get_node_by_name(db, name)
        if node is not None:
            crud.delete_node(db, node.id)
    finally:
        db.close()


def _cleanup_admin(username: str) -> None:
    from backend.auth.sessions import revoke_user_sessions
    from backend.db import crud
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        revoke_user_sessions(db, username)
        admin = crud.get_admin_by_username(db, username)
        if admin is not None:
            crud.delete_admin(db, admin)
    finally:
        db.close()


def test_overview_requires_auth():
    client = _client()
    assert client.get("/api/health/overview").status_code == 401
    assert client.get("/api/health/setup").status_code == 401


def test_overview_owner_lists_every_check():
    client = _client()
    resp = client.get("/api/health/overview", headers=_owner_headers())
    assert resp.status_code == 200

    body = resp.json()
    assert [c["id"] for c in body["checks"]] == _CHECK_IDS
    for check in body["checks"]:
        assert check["status"] in ("ok", "warn", "error"), check
        assert check["summary"], check
        assert isinstance(check["hint"], str), check
        if check["status"] == "ok":
            assert check["hint"] == "", check
        else:
            assert check["hint"], check

    assert set(body["details"]) == set(_CHECK_IDS)
    assert body["details"]["panel"]["version"] == __version__


def test_overview_missing_tls_file_does_not_500(monkeypatch):
    """A configured-but-missing certificate must degrade to warn/error."""
    monkeypatch.setattr(config, "SSL_CERTFILE", "/nonexistent/hh_missing_cert.pem")
    monkeypatch.setattr(config, "SSL_KEYFILE", "/nonexistent/hh_missing_key.pem")

    client = _client()
    resp = client.get("/api/health/overview", headers=_owner_headers())
    assert resp.status_code == 200

    tls = next(c for c in resp.json()["checks"] if c["id"] == "tls")
    assert tls["status"] in ("warn", "error")
    assert tls["hint"]


def test_setup_counts_reflect_created_rows_and_scope_admin():
    suffix = uuid.uuid4().hex[:8]
    admin = f"hh_admin_{suffix}"
    user = f"hh_user_{suffix}"
    node = f"hh_node_{suffix}"

    _create_admin(admin)
    _create_user(user, admin)
    _create_node(node)
    try:
        client = _client()

        owner = client.get("/api/health/setup", headers=_owner_headers())
        assert owner.status_code == 200
        owner_body = owner.json()
        assert owner_body["has_node"] is True
        assert owner_body["has_active_node"] is True
        assert owner_body["has_user"] is True
        assert owner_body["node_count"] >= 1
        assert owner_body["user_count"] >= 1
        assert set(owner_body) == {"has_node", "has_user", "has_active_node", "node_count", "user_count"}

        scoped = client.get("/api/health/setup", headers=_headers(admin, "admin"))
        assert scoped.status_code == 200
        scoped_body = scoped.json()
        assert scoped_body["user_count"] == 1
        assert scoped_body["node_count"] == owner_body["node_count"]
    finally:
        _cleanup_user(user)
        _cleanup_node(node)
        _cleanup_admin(admin)
