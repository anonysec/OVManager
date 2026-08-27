# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Regression tests for partial PUT /api/users/{uuid} updates.

`crud.update_user` used to assign `expiry_date` and `total` unconditionally,
so any payload that omitted them silently cleared those columns. A client that
posts only {"expiry_date": ...} used to wipe `total` and turn a quota-limited
account into an unlimited one — while returning HTTP 200.

Separately, `UpdateUser.expiry_date` was typed `date | None` with no default.
In Pydantic v2 that is REQUIRED, not optional, so partial updates 422ed; and
passing an explicit null hit `NOT NULL constraint failed: users.expiry_date`
and surfaced as a 500.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config

GB = 1024**3


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    """Serve routes at bare /api/... for the duration of the test.

    A deployment may namespace everything under a secret prefix (URLPATH); the
    middleware then answers unprefixed requests with an empty 200, which would
    make these assertions silently pass against a stale row.
    """
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


@pytest.fixture(autouse=True)
def _no_node_sync(monkeypatch):
    """Stub the node fan-out.

    PUT /users/{uuid} pushes status/limit changes to every registered node.
    These tests assert on what gets persisted, and a dev database may hold
    unreachable node rows whose 30s connect timeouts would dominate the run.
    """

    async def _ok(*args, **kwargs):
        return True

    monkeypatch.setattr("backend.routers.users.change_user_status_on_all_nodes", _ok)
    monkeypatch.setattr("backend.routers.users.set_user_limit_on_all_nodes", _ok)


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def _make_user(name: str) -> str:
    """Create (or reset) a user with known field values. Returns its uuid."""
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    _run_migrations()
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is None:
            import uuid as _uuid

            row = User(uuid=str(_uuid.uuid4()), name=name, owner=config.ADMIN_USERNAME)
            db.add(row)
        row.expiry_date = dt.date(2030, 1, 1)
        row.total = 10 * GB
        row.used = 0
        row.max_logins = 1
        row.is_active = True
        db.commit()
        return row.uuid
    finally:
        db.close()


def _read(client: TestClient, uuid: str) -> dict:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.uuid == uuid).first()
        return {"expiry_date": u.expiry_date, "total": u.total, "max_logins": u.max_logins}
    finally:
        db.close()


def test_expiry_only_update_preserves_total():
    """A partial expiry update must not wipe the traffic quota."""
    uuid = _make_user("pu_expiry_only")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={"name": "pu_expiry_only", "expiry_date": "2031-06-01"},
            headers=_owner_headers(),
        )
        assert r.status_code == 200, r.text
        row = _read(client, uuid)
        assert row["expiry_date"] == dt.date(2031, 6, 1)
        assert row["total"] == 10 * GB, "total was cleared by a partial update"
        assert row["max_logins"] == 1


def test_total_only_update_preserves_expiry():
    """A traffic-only update must not clear the expiry date."""
    uuid = _make_user("pu_total_only")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={"name": "pu_total_only", "total": 5 * GB},
            headers=_owner_headers(),
        )
        assert r.status_code == 200, r.text
        row = _read(client, uuid)
        assert row["total"] == 5 * GB
        assert row["expiry_date"] == dt.date(2030, 1, 1), "expiry was cleared"


def test_max_logins_only_update_preserves_the_rest():
    uuid = _make_user("pu_logins_only")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={"name": "pu_logins_only", "max_logins": 7},
            headers=_owner_headers(),
        )
        assert r.status_code == 200, r.text
        row = _read(client, uuid)
        assert row["max_logins"] == 7
        assert row["total"] == 10 * GB
        assert row["expiry_date"] == dt.date(2030, 1, 1)


def test_explicit_null_total_still_means_unlimited():
    """total=None is a real feature (unlimited), not a 'field omitted' marker."""
    uuid = _make_user("pu_null_total")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={"name": "pu_null_total", "total": None},
            headers=_owner_headers(),
        )
        assert r.status_code == 200, r.text
        row = _read(client, uuid)
        assert row["total"] is None
        assert row["expiry_date"] == dt.date(2030, 1, 1)


def test_explicit_null_expiry_is_rejected_not_a_500():
    """The column is NOT NULL — reject cleanly instead of an IntegrityError."""
    uuid = _make_user("pu_null_expiry")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={"name": "pu_null_expiry", "expiry_date": None},
            headers=_owner_headers(),
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        assert _read(client, uuid)["expiry_date"] == dt.date(2030, 1, 1)


def test_full_update_from_the_edit_modal_still_works():
    uuid = _make_user("pu_full_update")
    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}",
            json={
                "name": "pu_full_update",
                "expiry_date": "2032-03-15",
                "total": 20 * GB,
                "max_logins": 4,
            },
            headers=_owner_headers(),
        )
        assert r.status_code == 200, r.text
        row = _read(client, uuid)
        assert row == {"expiry_date": dt.date(2032, 3, 15), "total": 20 * GB, "max_logins": 4}
