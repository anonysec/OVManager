# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""User tags: free-form labels for organizing customers (pure bookkeeping)."""
import uuid as uuidlib

from fastapi.testclient import TestClient

from backend.app import api

client = TestClient(api)


def _owner():
    """The configured owner name (tests must not hardcode it — CI uses a
    dedicated ADMIN_USERNAME)."""
    from backend.config import config

    return config.ADMIN_USERNAME


def _owner_headers():
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        token = create_session(db, _owner(), "owner", user_agent="pytest", ip="127.0.0.1")
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def _create(name, tag=None):
    name = f"{name}-{uuidlib.uuid4().hex[:8]}"
    payload = {"name": name, "expiry_date": "2030-01-01"}
    if tag is not None:
        payload["tag"] = tag
    return client.post("/api/users/", json=payload, headers=_owner_headers())


def test_create_user_with_tag_persists_and_strips():
    r = _create("tagged-user-1", tag="  monthly  ")
    body = r.json()
    assert body["success"], body
    assert body["data"]["tag"] == "monthly"


def test_create_user_without_tag_has_none():
    r = _create("tagless-user-1")
    body = r.json()
    assert body["success"], body
    assert body["data"]["tag"] is None


def test_update_tag_set_and_clear():
    """Tags update through the API row without the node fanout interfering:
    crud-level set / clear / omit semantics."""
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import CreateUser, UpdateUser

    db = SessionLocal()
    try:
        name = f"tag-crud-{uuidlib.uuid4().hex[:8]}"
        request = CreateUser(name=name, expiry_date=None, tag="vip")
        user = crud.create_user(db, request, owner="admin")
        assert user.tag == "vip"

        # Explicit set
        crud.update_user(db, user.uuid, UpdateUser(name=name, tag="reseller-a"))
        assert db.query(crud.User).filter(crud.User.uuid == user.uuid).first().tag == "reseller-a"
        # Empty string clears
        crud.update_user(db, user.uuid, UpdateUser(name=name, tag=""))
        assert db.query(crud.User).filter(crud.User.uuid == user.uuid).first().tag is None
        # Omitted tag leaves the value alone
        crud.update_user(db, user.uuid, UpdateUser(name=name, tag=None))
        assert db.query(crud.User).filter(crud.User.uuid == user.uuid).first().tag is None
    finally:
        db.close()


def test_tag_cannot_be_updated_without_ownership():
    """Admins may only touch their own users — tags are part of the row."""
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    r = _create("tag-owner-admin-1", tag="mine")
    uuid = r.json()["data"]["uuid"]
    # The row belongs to the owner, so an admin session with the same
    # username works; a different admin must be rejected by access control.
    db = SessionLocal()
    try:
        token = create_session(db, f"{_owner()}-other", "admin", user_agent="pytest", ip="127.0.0.1")
    finally:
        db.close()
    r = client.put(
        f"/api/users/{uuid}",
        json={"name": r.json()["data"]["name"], "tag": "hijack"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code in (401, 403, 404)
