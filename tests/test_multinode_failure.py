# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Multi-node failure: the panel degrades gracefully with a dead node.

Uses a REAL node row pointed at a closed port (fast refused, no mocks
below the HTTP layer): listing never hangs, delete is best-effort with
named failures, status flips persist locally, enforce disables locally.
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

    _run_migrations()
    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


@pytest.fixture()
def dead_node_and_user():
    """A live (status=True) node row on a closed port + one user."""
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    _run_migrations()
    node_name = f"dead_{_uuid.uuid4().hex[:8]}"
    user_name = f"deaduser_{_uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(
            Node(
                name=node_name,
                address="127.0.0.1",
                protocol="udp",
                ovpn_port=1194,
                port=9,  # discard port: closed → instant refused
                key="k" * 32,
                status=True,
                use_tls=False,
            )
        )
        db.flush()
        row = User(
            uuid=str(_uuid.uuid4()),
            name=user_name,
            owner=config.ADMIN_USERNAME,
            expiry_date=dt.date(2030, 1, 1),
            total=10 * 1024**3,
            used=0,
            max_logins=1,
            is_active=True,
        )
        db.add(row)
        db.commit()
        yield node_name, user_name, row.uuid
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.name == user_name).delete()
            db.query(Node).filter(Node.name == node_name).delete()
            db.commit()
        finally:
            db.close()


def test_list_users_survives_dead_node(dead_node_and_user):
    _, user_name, _ = dead_node_and_user
    with TestClient(api) as client:
        r = client.get("/api/users/", headers=_owner_headers())
        assert r.status_code == 200
        names = [u["name"] for u in r.json()["data"]["users"]]
        assert user_name in names


def test_delete_names_unreachable_node_but_succeeds(dead_node_and_user):
    node_name, _, uuid = dead_node_and_user
    with TestClient(api) as client:
        r = client.delete(f"/api/users/{uuid}", headers=_owner_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["failed_nodes"] == [node_name]


def test_status_flip_persists_despite_dead_node(dead_node_and_user):
    _, _, uuid = dead_node_and_user
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    with TestClient(api) as client:
        r = client.put(
            f"/api/users/{uuid}/status",
            json={"name": "x", "status": False},
            headers=_owner_headers(),
        )
        assert r.status_code == 200
        assert r.json()["success"] is False  # node sync failed…
        db = SessionLocal()
        try:
            assert db.query(User).filter(User.uuid == uuid).first().is_active is False  # …but local saved
        finally:
            db.close()


def test_enforce_disables_locally_with_dead_node(dead_node_and_user):
    import asyncio

    from backend.operations import daily_checks as dc

    _, user_name, _ = dead_node_and_user
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        db.query(User).filter(User.name == user_name).update({"expiry_date": dt.date.today() - dt.timedelta(days=1)})
        db.commit()
    finally:
        db.close()
    asyncio.run(dc.enforce_user_limits())
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.name == user_name).first().is_active is False
    finally:
        db.close()
