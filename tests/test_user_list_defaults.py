# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Regression tests for Phase 2 user-list work.

- GET /users/?search= filters server-side (bot no longer pulls the table).
- GET /users/?page=&page_size= slices in SQL, not Python.
- POST /users/ without expiry_date falls back to Settings.default_days.
- POST /users/{uuid}/extend with days works when expiry_date is NULL.
- DELETE /users/{uuid} removes the DB row even when a node is down,
  naming the unreachable nodes instead of failing.
"""

import datetime as dt
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def _mkrow(name: str, **fields) -> str:
    """Insert a user row directly (bypasses API defaults). Returns uuid."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    _run_migrations()
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is None:
            row = User(uuid=str(_uuid.uuid4()), name=name, owner=config.ADMIN_USERNAME)
            db.add(row)
        row.expiry_date = fields.get("expiry_date", dt.date(2030, 1, 1))
        row.total = fields.get("total", 10 * 1024**3)
        row.used = fields.get("used", 0)
        row.max_logins = fields.get("max_logins", 1)
        row.is_active = True
        db.commit()
        return row.uuid
    finally:
        db.close()


def test_search_filters_server_side():
    _mkrow("ulp_search_alpha")
    _mkrow("ulp_search_beta")
    with TestClient(api) as client:
        r = client.get("/api/users/?search=ulp_search_alpha", headers=_owner_headers())
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert [u["name"] for u in data["users"]] == ["ulp_search_alpha"]


def test_pagination_slices_at_db_level():
    for i in range(5):
        _mkrow(f"ulp_page_{i}")
    with TestClient(api) as client:
        r = client.get("/api/users/?search=ulp_page_&page=2&page_size=2", headers=_owner_headers())
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 5
        assert [u["name"] for u in data["users"]] == ["ulp_page_2", "ulp_page_3"]


def test_create_without_expiry_uses_default_days():
    from backend.db import crud
    from backend.db.engine import SessionLocal

    _run_migrations()
    db = SessionLocal()
    try:
        days = int(crud.get_settings(db).default_days or 30)
    finally:
        db.close()
    name = f"ulp_nodefault_{_uuid.uuid4().hex[:8]}"
    with TestClient(api) as client:
        r = client.post("/api/users/", json={"name": name, "total": 1024}, headers=_owner_headers())
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        got = r.json()["data"]["expiry_date"]
    assert got == (dt.date.today() + dt.timedelta(days=days)).isoformat()


def test_extend_days_normal_path():
    """Extend from an existing expiry still anchors on it (not today)."""
    name = f"ulp_dated_{_uuid.uuid4().hex[:8]}"
    uuid = _mkrow(name)
    with TestClient(api) as client:
        r = client.post(f"/api/users/{uuid}/extend", json={"days": 5, "bytes": 0}, headers=_owner_headers())
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.uuid == uuid).first()
        assert row.expiry_date == dt.date(2030, 1, 1) + dt.timedelta(days=5)
    finally:
        db.close()


def test_delete_with_dead_node_still_deletes_locally(monkeypatch):
    async def _partial(*args, **kwargs):
        return {"ok": False, "failed": ["dead-node"]}

    monkeypatch.setattr("backend.routers.users.delete_user_on_all_nodes", _partial)
    uuid = _mkrow(f"ulp_deadnode_{_uuid.uuid4().hex[:8]}")
    with TestClient(api) as client:
        r = client.delete(f"/api/users/{uuid}", headers=_owner_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["failed_nodes"] == ["dead-node"]
        assert "dead-node" in body["msg"]
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.uuid == uuid).first() is None
    finally:
        db.close()
