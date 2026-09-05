# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Retired global registry: live poll is authoritative, shapes unchanged.

The panel-side global_mlogin_sessions table was never written to, so its
two cleaners and per-request pruning were dead code (plus a cross-user
deletion bug had rows ever existed). These pin the post-removal contract:
- GET /mlogin/status/{u} answers from the live poll alone, touching no table.
- POST /maintenance/clean-global-registry stays green with removed == [].
- login diagnostics still carries global_registry == [] for the UI.
"""

import datetime as dt
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app import _run_migrations, api
from backend.config import config
from backend.db.engine import SessionLocal
from backend.db.models import User


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

    _run_migrations()
    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def test_mlogin_status_needs_no_table():
    """No nodes, no registry table touched: 200 with empty sessions."""
    _run_migrations()
    db = SessionLocal()
    try:
        db.execute(text("DROP TABLE IF EXISTS global_mlogin_sessions"))
        db.commit()
    finally:
        db.close()
    with TestClient(api) as client:
        r = client.get("/api/mlogin/status/ghost-user", headers=_owner_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["global_active"] == 0
        assert body["data"]["sessions"] == []


def test_clean_global_registry_is_retired_but_green():
    with TestClient(api) as client:
        r = client.post("/api/maintenance/clean-global-registry", headers=_owner_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["removed"] == []


def test_login_diagnostics_registry_empty():
    _run_migrations()
    name = f"reg_diag_{_uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        if db.query(User).filter(User.name == name).first() is None:
            db.add(
                User(
                    uuid=str(_uuid.uuid4()),
                    name=name,
                    owner=config.ADMIN_USERNAME,
                    expiry_date=dt.date(2030, 1, 1),
                    max_logins=1,
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()
    try:
        with TestClient(api) as client:
            r = client.get(f"/api/maintenance/login-diagnostics/{name}", headers=_owner_headers())
            assert r.status_code == 200
            assert r.json()["data"]["global_registry"] == []
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.name == name).delete()
            db.commit()
        finally:
            db.close()
