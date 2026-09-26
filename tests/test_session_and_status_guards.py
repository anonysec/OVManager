"""Step-1 reliability guards: session revocation and activation rules."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    set_urlpath("")
    yield
    set_urlpath(get_urlpath() and "" or "")


@pytest.fixture(autouse=True)
def _no_node_sync(monkeypatch):
    """Stub every node fan-out: tests assert local behavior only."""

    async def _ok(*args, **kwargs):
        return True

    async def _ok_delete(*args, **kwargs):
        return {"failed": []}

    monkeypatch.setattr("backend.routers.users.change_user_status_on_all_nodes", _ok)
    monkeypatch.setattr("backend.routers.users.set_user_limit_on_all_nodes", _ok)
    monkeypatch.setattr("backend.routers.users.delete_user_on_all_nodes", _ok_delete)


def _token(username: str, role: str) -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, username, role)
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _owner() -> dict:
    return _token(config.ADMIN_USERNAME, "owner")


def _ensure_admin(username: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def _make_user(name: str, **kw) -> str:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import CreateUser

    db = SessionLocal()
    try:
        existing = crud.get_user_by_name(db, name)
        if existing is not None:
            return existing.uuid
        req = CreateUser(name=name, expiry_date=kw.pop("expiry_date", dt.date.today() + dt.timedelta(days=30)), **kw)
        return crud.create_user(db, req, config.ADMIN_USERNAME).uuid
    finally:
        db.close()


def _is_active(uuid: str) -> bool:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return bool(db.query(User.is_active).filter(User.uuid == uuid).first()[0])
    finally:
        db.close()


def test_admin_password_change_revokes_live_sessions():
    """Old bearer tokens must die when the admin's password is rotated."""
    _run_migrations()
    name = "ac_pwrevoke_admin"
    _ensure_admin(name)
    admin = _token(name, "admin")
    client = TestClient(api)
    assert client.get("/api/users/", headers=admin).status_code == 200

    resp = client.put("/api/admin/", json={"username": name, "password": "new-pw-rotated-12345"}, headers=_owner())
    assert resp.status_code == 200, resp.text

    assert client.get("/api/users/", headers=admin).status_code == 401


def _set_user_fields(name: str, **fields) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def test_status_toggle_cannot_activate_expired_user():
    _run_migrations()
    uuid = _make_user("ac_status_expired")
    _set_user_fields("ac_status_expired", expiry_date=dt.date.today() - dt.timedelta(days=1), is_active=False)
    client = TestClient(api)
    resp = client.put(
        f"/api/users/{uuid}/status",
        json={"name": "ac_status_expired", "status": True},
        headers=_owner(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False
    assert "expired" in resp.json()["msg"]
    assert _is_active(uuid) is False


def test_status_toggle_cannot_activate_user_over_quota():
    _run_migrations()
    uuid = _make_user("ac_status_quota", total=100)
    _set_user_fields("ac_status_quota", used=100, is_active=False)
    client = TestClient(api)
    resp = client.put(
        f"/api/users/{uuid}/status",
        json={"name": "ac_status_quota", "status": True},
        headers=_owner(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False
    assert "traffic" in resp.json()["msg"]
    assert _is_active(uuid) is False


def test_status_toggle_still_activates_healthy_user():
    _run_migrations()
    uuid = _make_user("ac_status_ok")
    _set_user_fields("ac_status_ok", is_active=False)
    client = TestClient(api)
    resp = client.put(
        f"/api/users/{uuid}/status",
        json={"name": "ac_status_ok", "status": True},
        headers=_owner(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert _is_active(uuid) is True


def test_undo_delete_restores_node_baselines():
    """Undo must keep the per-node baselines, or between-delete traffic is
    silently unbilled when the collector rebaselines."""
    _run_migrations()
    uuid = _make_user("ac_undo_baseline")
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.uuid == uuid).first()
        row.node_usage = '{"1": {"total": 4096}}'
        row.last_node_usage = 4096
        db.commit()
    finally:
        db.close()

    client = TestClient(api)
    owner = _owner()
    assert client.delete(f"/api/users/{uuid}", headers=owner).status_code == 200
    resp = client.post(f"/api/users/{uuid}/restore", headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.uuid == uuid).first()
        assert row.node_usage == '{"1": {"total": 4096}}'
        assert row.last_node_usage == 4096
    finally:
        db.close()
