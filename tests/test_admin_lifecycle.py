# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Step-3 admin lifecycle tests: disable/enable, live-session revocation,
session listing, owner-only gating, and the audit trail for those actions.

All rows created here use the ``al_`` prefix because the suite shares one dev
SQLite database across test files (see tests/test_access_control.py).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import set_urlpath

    set_urlpath("")
    yield
    set_urlpath("")


def _token(username: str, role: str, *, user_agent: str | None = None, ip: str | None = None) -> str:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        return create_session(db, username, role, user_agent=user_agent, ip=ip)
    finally:
        db.close()


def _auth(username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(username, role)}"}


def _owner_headers() -> dict:
    return _auth(config.ADMIN_USERNAME, "owner")


def _ensure_schema():
    _run_migrations()
    from backend.db.engine import SessionLocal
    from backend.operations.audit import ensure_audit_table

    db = SessionLocal()
    try:
        ensure_audit_table(db)
    finally:
        db.close()


def _ensure_admin(username: str) -> None:
    """Create the admin if missing and always reset it to enabled."""
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        admin = crud.get_admin_by_username(db, username)
        if admin is None:
            admin = crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
        if admin.disabled:
            admin.disabled = False
            db.commit()
    finally:
        db.close()


def _set_disabled(username: str, disabled: bool) -> None:
    """Flip the flag directly, bypassing the endpoint (and its revocation)."""
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == username).first()
        row.disabled = disabled
        db.commit()
    finally:
        db.close()


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/login",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"username": username, "password": password},
    )


# ── Disable / enable ────────────────────────────────────────────────────────


def test_disabled_admin_cannot_log_in_until_enabled():
    _ensure_schema()
    name = "al_login"
    _ensure_admin(name)
    password = f"pw-{name}-12345"
    client = TestClient(api)
    owner = _owner_headers()

    resp = _login(client, name, password)
    assert resp.status_code == 200, resp.text

    resp = client.put(f"/api/admin/{name}/status", json={"status": False}, headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    resp = _login(client, name, password)
    assert resp.status_code in (401, 403), resp.text

    resp = client.put(f"/api/admin/{name}/status", json={"status": True}, headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    resp = _login(client, name, password)
    assert resp.status_code == 200, resp.text


def test_status_toggle_reflects_disabled_in_admins_list():
    _ensure_schema()
    name = "al_listed"
    _ensure_admin(name)
    client = TestClient(api)
    owner = _owner_headers()

    def listed_disabled() -> bool:
        resp = client.get("/api/admin/", headers=owner)
        assert resp.status_code == 200, resp.text
        return next(a["disabled"] for a in resp.json()["data"] if a["username"] == name)

    assert listed_disabled() is False

    resp = client.put(f"/api/admin/{name}/status", json={"status": False}, headers=owner)
    assert resp.json()["success"] is True
    assert listed_disabled() is True

    resp = client.put(f"/api/admin/{name}/status", json={"status": True}, headers=owner)
    assert resp.json()["success"] is True
    assert listed_disabled() is False


def test_status_ignores_unknown_and_owner_accounts():
    _ensure_schema()
    client = TestClient(api)
    owner = _owner_headers()

    resp = client.put("/api/admin/al_missing_xyz/status", json={"status": False}, headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False
    assert "not found" in resp.json()["msg"].lower()

    # The owner is not a DB admin and must never be lockable from the panel.
    resp = client.put(f"/api/admin/{config.ADMIN_USERNAME}/status", json={"status": False}, headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False


# ── Live-session revocation ─────────────────────────────────────────────────


def test_disabling_admin_revokes_live_session():
    _ensure_schema()
    name = "al_revoke"
    _ensure_admin(name)
    client = TestClient(api)
    headers = _auth(name, "admin")

    assert client.get("/api/users/", headers=headers).status_code == 200

    resp = client.put(f"/api/admin/{name}/status", json={"status": False}, headers=_owner_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    assert client.get("/api/users/", headers=headers).status_code == 401


def test_disabled_admin_existing_session_is_rejected():
    """Even without revocation, role_is_current must reject a disabled admin."""
    _ensure_schema()
    name = "al_flag"
    _ensure_admin(name)
    client = TestClient(api)
    headers = _auth(name, "admin")

    assert client.get("/api/users/", headers=headers).status_code == 200

    _set_disabled(name, True)

    assert client.get("/api/users/", headers=headers).status_code == 401


# ── Session listing + revoke ────────────────────────────────────────────────


def test_sessions_endpoint_lists_and_revokes_sessions():
    _ensure_schema()
    name = "al_sessions"
    other = "al_sessions_other"
    _ensure_admin(name)
    _ensure_admin(other)
    client = TestClient(api)
    owner = _owner_headers()

    raw_watched = _token(name, "admin", user_agent="al-agent", ip="203.0.113.9")
    _token(name, "admin")
    other_token = _token(other, "admin")

    resp = client.get(f"/api/admin/{name}/sessions", headers=owner)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    sessions = body["data"]
    assert len(sessions) >= 2

    expected_keys = {"id", "ip", "user_agent", "created_at", "last_seen_at", "expires_at"}
    for item in sessions:
        assert set(item) == expected_keys
    assert any(item["user_agent"] == "al-agent" and item["ip"] == "203.0.113.9" for item in sessions)
    # Never leak token material (raw token or its hash).
    assert raw_watched not in resp.text

    resp = client.post(f"/api/admin/{name}/sessions/revoke", headers=owner)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["revoked"] >= 2

    resp = client.get(f"/api/admin/{name}/sessions", headers=owner)
    assert resp.json()["data"] == []

    # Another admin's sessions are untouched by the revoke.
    assert client.get("/api/users/", headers={"Authorization": f"Bearer {other_token}"}).status_code == 200

    # Unknown admin: no crash, clear message.
    resp = client.get("/api/admin/al_missing_sessions/sessions", headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False
    resp = client.post("/api/admin/al_missing_sessions/sessions/revoke", headers=owner)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False


def test_lifecycle_endpoints_are_owner_only():
    _ensure_schema()
    name = "al_gate"
    _ensure_admin(name)
    client = TestClient(api)
    admin = _auth(name, "admin")

    resp = client.put(f"/api/admin/{name}/status", json={"status": False}, headers=admin)
    assert resp.status_code == 403, resp.text
    resp = client.get(f"/api/admin/{name}/sessions", headers=admin)
    assert resp.status_code == 403, resp.text
    resp = client.post(f"/api/admin/{name}/sessions/revoke", headers=admin)
    assert resp.status_code == 403, resp.text


# ── Audit trail ─────────────────────────────────────────────────────────────


def test_admin_lifecycle_actions_are_audited():
    _ensure_schema()
    name = "al_audit"
    _ensure_admin(name)
    client = TestClient(api)
    owner = _owner_headers()

    resp = client.put(f"/api/admin/{name}/status", json={"status": False}, headers=owner)
    assert resp.json()["success"] is True
    resp = client.put(f"/api/admin/{name}/status", json={"status": True}, headers=owner)
    assert resp.json()["success"] is True
    resp = client.post(f"/api/admin/{name}/sessions/revoke", headers=owner)
    assert resp.json()["success"] is True

    from backend.db.engine import SessionLocal
    from backend.operations.audit import recent_events

    db = SessionLocal()
    try:
        got = {(e["action"], e["target"]) for e in recent_events(db, limit=100)}
    finally:
        db.close()
    assert ("admin.disable", name) in got
    assert ("admin.enable", name) in got
    assert ("admin.sessions_revoke", name) in got


# ── Per-admin new-user defaults ─────────────────────────────────────────────


def _set_global_defaults(days: int, traffic_gb: int, max_users: int) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Settings

    db = SessionLocal()
    try:
        row = db.query(Settings).first()
        row.default_days = days
        row.default_traffic_gb = traffic_gb
        row.default_max_users = max_users
        db.commit()
    finally:
        db.close()


def _clear_overrides(username: str) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == username).first()
        if row is not None:
            row.default_days = None
            row.default_traffic_gb = None
            row.default_max_users = None
            db.commit()
    finally:
        db.close()


def test_admin_defaults_inherit_owner_global_until_overridden():
    _ensure_schema()
    name = "al_defaults"
    _ensure_admin(name)
    _clear_overrides(name)
    _set_global_defaults(45, 55, 2)
    client = TestClient(api)

    try:
        # No override -> the owner's global plan applies.
        resp = client.get("/api/admin/me/defaults", headers=_auth(name, "admin"))
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["source"] == "owner"
        assert body["effective"] == {"days": 45, "traffic_gb": 55, "max_users": 2}

        # The owner sets a per-admin override on this admin only.
        resp = client.put(
            "/api/admin/",
            json={"username": name, "default_days": 7, "default_max_users": 5},
            headers=_owner_headers(),
        )
        assert resp.json()["success"] is True, resp.text

        resp = client.get("/api/admin/me/defaults", headers=_auth(name, "admin"))
        body = resp.json()["data"]
        assert body["source"] == "admin"
        # Untouched fields still inherit; the overridden ones do not.
        assert body["effective"] == {"days": 7, "traffic_gb": 55, "max_users": 5}

        # An explicit null clears the override back to the global plan.
        resp = client.put(
            "/api/admin/",
            json={"username": name, "default_days": None, "default_max_users": None},
            headers=_owner_headers(),
        )
        assert resp.json()["success"] is True, resp.text
        resp = client.get("/api/admin/me/defaults", headers=_auth(name, "admin"))
        assert resp.json()["data"]["effective"] == {"days": 45, "traffic_gb": 55, "max_users": 2}
    finally:
        _clear_overrides(name)


def test_new_user_uses_creating_admins_effective_defaults():
    _ensure_schema()
    name = "al_defcreate"
    _ensure_admin(name)
    _clear_overrides(name)
    _set_global_defaults(11, 22, 3)
    client = TestClient(api)

    try:
        resp = client.put(
            "/api/admin/",
            json={"username": name, "default_days": 9, "default_traffic_gb": 4},
            headers=_owner_headers(),
        )
        assert resp.json()["success"] is True, resp.text

        # Omit expiry/traffic/devices: the plan comes from the creating admin.
        resp = client.post(
            "/api/users/",
            json={"name": "al_defcreate_u1", "total": None, "max_logins": None},
            headers=_auth(name, "admin"),
        )
        assert resp.json()["success"] is True, resp.text
        user = resp.json()["data"]

        from datetime import date, timedelta

        assert user["expiry_date"] == (date.today() + timedelta(days=9)).isoformat()
        # total stayed unlimited (explicit None) and devices came from the
        # untouched global (3) rather than the admin's traffic override.
        assert user["max_logins"] == 3
    finally:
        from backend.db import crud
        from backend.db.engine import SessionLocal

        db = SessionLocal()
        try:
            crud.delete_user(db, "al_defcreate_u1")
        finally:
            db.close()
        _clear_overrides(name)


def test_create_admin_persists_telegram_prefix_and_defaults():
    """The create form sends all of these; they used to be dropped on the floor."""
    _ensure_schema()
    name = "al_createfull"
    client = TestClient(api)

    from backend.db import crud
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, name):
            crud.delete_admin(db, crud.get_admin_by_username(db, name))
    finally:
        db.close()

    resp = client.post(
        "/api/admin/",
        json={
            "username": name,
            "password": "short-pass-8",  # 8 chars: the documented floor
            "telegram_id": 4242,
            "username_prefix": "90",
            "default_days": 3,
            "default_max_users": 0,
        },
        headers=_owner_headers(),
    )
    assert resp.json()["success"] is True, resp.text
    data = resp.json()["data"]
    assert data["telegram_id"] == 4242
    assert data["username_prefix"] == "90"
    assert data["default_days"] == 3
    assert data["default_max_users"] == 0
    # Unset traffic override keeps inheriting the owner global.
    assert data["effective_defaults"]["traffic_gb"] > 0

    db = SessionLocal()
    try:
        row = crud.get_admin_by_username(db, name)
        assert row.telegram_id == 4242
        assert row.username_prefix == "90"
        assert row.default_days == 3
        assert row.default_traffic_gb is None
    finally:
        db.close()
