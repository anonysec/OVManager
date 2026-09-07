# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Access-control regression tests: cross-tenant isolation, reserved URL
paths, audit-feed scoping, and revocation on the mlogin JWT path."""

import datetime as dt

from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config

_RUN_DATE = dt.date.today


def _token(username: str, role: str) -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, username, role)
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _owner_headers() -> dict:
    return _token(config.ADMIN_USERNAME, "owner")


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
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema._input import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def _ensure_user(name: str, owner: str) -> str:
    """Create a user row (idempotent per username). Returns its uuid."""
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema._input import CreateUser

    db = SessionLocal()
    try:
        existing = crud.get_user_by_name(db, name)
        if existing is not None:
            return existing.uuid
        req = CreateUser(name=name, expiry_date=_RUN_DATE() + dt.timedelta(days=30), total=1024)
        return crud.create_user(db, req, owner).uuid
    finally:
        db.close()


def _expiry_of(uuid: str) -> dt.date:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return db.query(User.expiry_date).filter(User.uuid == uuid).first()[0]
    finally:
        db.close()


# ── Single-user extend respects tenancy ────────────────────────────────────


def test_extend_admin_cannot_touch_other_tenants_users():
    _ensure_schema()
    _ensure_admin("ac_admin_extend")
    admin_uuid = _ensure_user("ac_extend_own_user", "ac_admin_extend")
    other_uuid = _ensure_user("ac_extend_foreign_user", config.ADMIN_USERNAME)

    before_admin, before_other = _expiry_of(admin_uuid), _expiry_of(other_uuid)

    client = TestClient(api)
    # Own user: allowed.
    resp = client.post(
        f"/api/users/{admin_uuid}/extend",
        json={"days": 10},
        headers=_token("ac_admin_extend", "admin"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert _expiry_of(admin_uuid) == before_admin + dt.timedelta(days=10)

    # Other tenant: 404 (no existence leak).
    resp = client.post(
        f"/api/users/{other_uuid}/extend",
        json={"days": 10},
        headers=_token("ac_admin_extend", "admin"),
    )
    assert resp.status_code == 404
    assert _expiry_of(other_uuid) == before_other  # untouched


def test_extend_owner_can_touch_everyone():
    _ensure_schema()
    other_uuid = _ensure_user("ac_extend_owner_scope", config.ADMIN_USERNAME)
    before = _expiry_of(other_uuid)

    client = TestClient(api)
    resp = client.post(
        f"/api/users/{other_uuid}/extend",
        json={"days": 5},
        headers=_owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert _expiry_of(other_uuid) == before + dt.timedelta(days=5)


def test_extend_rejects_empty_payload():
    _ensure_schema()
    uuid = _ensure_user("ac_extend_empty", config.ADMIN_USERNAME)
    client = TestClient(api)
    resp = client.post(f"/api/users/{uuid}/extend", json={"days": 0, "bytes": 0}, headers=_owner_headers())
    assert resp.status_code == 422


def test_list_users_returns_full_set_by_default():
    """The panel filters client-side, so GET /users/ must not silently cap at 100."""
    _ensure_schema()
    for i in range(3):
        _ensure_user(f"ac_list_user_{i}", config.ADMIN_USERNAME)
    client = TestClient(api)
    resp = client.get("/api/users/", headers=_owner_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["users"], list)
    assert data["total"] == len(data["users"])
    assert data["total"] >= 3


# ── Restore (undo delete) respects tenancy ─────────────────────────────────


def test_restore_rejects_cross_tenant_and_allows_owner():
    _ensure_schema()
    _ensure_admin("ac_admin_restore")
    uuid = _ensure_user("ac_restore_user", config.ADMIN_USERNAME)

    client = TestClient(api)
    # Owner deletes → snapshot lands in the process-global undo buffer.
    resp = client.delete(f"/api/users/{uuid}", headers=_owner_headers())
    assert resp.status_code == 200 and resp.json()["success"]

    # A different admin knows the UUID but must not resurrect it.
    resp = client.post(f"/api/users/{uuid}/restore", headers=_token("ac_admin_restore", "admin"))
    assert resp.status_code == 200
    assert resp.json()["success"] is False

    # The failed attempt must not consume the buffer entry — owner can still restore.
    resp = client.post(f"/api/users/{uuid}/restore", headers=_owner_headers())
    assert resp.status_code == 200 and resp.json()["success"]


# ── Reserved URL paths ─────────────────────────────────────────────────────


def test_urlpath_rejects_reserved_prefixes():
    from backend.urlpath import set_urlpath

    _ensure_schema()
    client = TestClient(api)
    try:
        for reserved in ("api", "assets", "health", "doc", "sub"):
            resp = client.put("/api/server/settings/urlpath", json={"urlpath": reserved}, headers=_owner_headers())
            assert resp.status_code == 200
            assert resp.json()["success"] is False, f"reserved prefix '{reserved}' was accepted"
        # And a sane value still works.
        resp = client.put("/api/server/settings/urlpath", json={"urlpath": "panel42"}, headers=_owner_headers())
        assert resp.json()["success"] is True
    finally:
        set_urlpath("")


# ── Audit feed scoping ─────────────────────────────────────────────────────


def test_activity_feed_scopes_admin_to_own_events():
    _ensure_schema()
    _ensure_admin("ac_admin_audit")
    from backend.db.engine import SessionLocal
    from backend.operations.audit import log_event

    db = SessionLocal()
    try:
        log_event(db, "test.owner_action", actor=config.ADMIN_USERNAME, target="ac_audit_t1")
        log_event(db, "test.admin_action", actor="ac_admin_audit", target="ac_audit_t2")
    finally:
        db.close()

    client = TestClient(api)
    resp = client.get("/api/activity/", headers=_token("ac_admin_audit", "admin"))
    assert resp.status_code == 200
    events = resp.json()["data"]
    assert all(e["actor"] == "ac_admin_audit" for e in events)
    assert any(e["action"] == "test.admin_action" for e in events)

    resp = client.get("/api/activity/", headers=_owner_headers())
    actions = {e["action"] for e in resp.json()["data"]}
    assert {"test.owner_action", "test.admin_action"} <= actions


def test_activity_action_prefix_filter():
    """?action= filters server-side by prefix (owner sees all actors)."""
    _ensure_schema()
    from backend.db.engine import SessionLocal
    from backend.operations.audit import log_event

    db = SessionLocal()
    try:
        log_event(db, "flt.user_create", actor="flt_actor", target="t1")
        log_event(db, "flt.node_create", actor="flt_actor", target="t2")
        log_event(db, "other.ping", actor="flt_actor", target="t3")
    finally:
        db.close()

    client = TestClient(api)
    resp = client.get("/api/activity/", params={"action": "flt.user"}, headers=_owner_headers())
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()["data"]]
    assert actions and all(a.startswith("flt.user") for a in actions)

    # Admin scoping still applies on top of the filter.
    _ensure_admin("ac_admin_flt")
    resp = client.get("/api/activity/", params={"action": "flt"}, headers=_token("ac_admin_flt", "admin"))
    assert resp.status_code == 200
    assert all(e["actor"] == "ac_admin_flt" for e in resp.json()["data"])


def test_failed_login_is_audited():
    """401s and lockouts land in the audit trail (actor=attempted user)."""
    _ensure_schema()
    client = TestClient(api)
    resp = client.post(
        "/api/login",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"username": "ghost_login_xyz", "password": "wrong-wrong-wrong"},
    )
    assert resp.status_code == 401
    from backend.db.engine import SessionLocal
    from backend.operations.audit import recent_events

    db = SessionLocal()
    try:
        fails = [e for e in recent_events(db, limit=50) if e["action"] == "auth.login_fail"]
        assert any(e["actor"] == "ghost_login_xyz" and e["target"] for e in fails)
    finally:
        db.close()


def test_admin_lifecycle_is_audited():
    """admin.create/update/delete land in the audit trail with the actor."""
    _ensure_schema()
    client = TestClient(api)
    name = "ac_audit_admin"
    headers = _owner_headers()
    client.delete(f"/api/admin/{name}", headers=headers)
    resp = client.post("/api/admin/", json={"username": name, "password": "pw-ac-audit-12345"}, headers=headers)
    assert resp.status_code == 200, resp.text
    resp = client.put("/api/admin/", json={"username": name, "password": "pw-ac-audit-67890"}, headers=headers)
    assert resp.status_code == 200, resp.text
    resp = client.delete(f"/api/admin/{name}", headers=headers)
    assert resp.status_code == 200, resp.text

    from backend.db.engine import SessionLocal
    from backend.operations.audit import recent_events

    db = SessionLocal()
    try:
        got = {(e["action"], e["target"]) for e in recent_events(db, limit=100) if e["target"] == name}
        assert ("admin.create", name) in got
        assert ("admin.update", name) in got
        assert ("admin.delete", name) in got
    finally:
        db.close()


# ── Owner-only read surface (nodes / settings / info / security / metrics) ──


def test_owner_only_reads_reject_admin():
    """Normal admins get 403 on node list, settings, server info,
    security summary and metrics history; owner keeps 200."""
    _ensure_schema()
    _ensure_admin("ac_admin_readgate")
    client = TestClient(api)
    admin = _token("ac_admin_readgate", "admin")
    owner = _owner_headers()
    for path in (
        "/api/nodes/",
        "/api/server/settings",
        "/api/server/info",
        "/api/security/summary",
        "/api/metrics/history",
    ):
        resp = client.get(path, headers=admin)
        assert resp.status_code == 403, f"{path} allowed for admin"
    for path in (
        "/api/nodes/",
        "/api/server/settings",
        "/api/server/info",
        "/api/metrics/history",
    ):
        resp = client.get(path, headers=owner)
        assert resp.status_code == 200, f"{path} broke for owner: {resp.text[:200]}"


def test_security_summary_owner_still_works():
    """Owner keeps 200 on the security summary (admin is 403 above)."""
    _ensure_schema()
    client = TestClient(api)
    resp = client.get("/api/security/summary", headers=_owner_headers())
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── mlogin JWT path honors revocation ──────────────────────────────────────


def test_mlogin_status_rejects_revoked_owner_token():
    from backend.auth.sessions import create_session, revoke_token
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
        revoke_token(db, raw)
    finally:
        db.close()
    client = TestClient(api)
    resp = client.get("/api/mlogin/status/someone", headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401
