# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""sync_all_user_limits pushes only changed pairs (hash-cache dedup).

First sweep pushes everything; an identical second sweep pushes nothing
(skipped == total); changing one user's limit re-pushes exactly that pair;
a failed push stays dirty and is retried next sweep.
"""

import asyncio
import datetime as dt
import uuid as _uuid

import pytest

import backend.node.sync as sync_mod
from backend.app import _run_migrations


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


@pytest.fixture(autouse=True)
def _clean_cache():
    sync_mod._last_pushed_limits.clear()
    yield
    sync_mod._last_pushed_limits.clear()


def _seed():
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    _run_migrations()
    db = SessionLocal()
    try:
        node = Node(
            name=f"slc_node_{_uuid.uuid4().hex[:8]}",
            address="127.0.0.1",
            protocol="udp",
            ovpn_port=1194,
            port=2083,
            key="x" * 32,
            status=True,
            use_tls=False,
        )
        db.add(node)
        db.flush()
        user = User(
            uuid=str(_uuid.uuid4()),
            name=f"slc_user_{_uuid.uuid4().hex[:8]}",
            owner="owner",
            expiry_date=dt.date(2030, 1, 1),
            max_logins=1,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return node.id, user.id, user.name
    finally:
        db.close()


def _cleanup(node_id, name):
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    db = SessionLocal()
    try:
        db.query(User).filter(User.name == name).delete()
        db.query(Node).filter(Node.id == node_id).delete()
        db.commit()
    finally:
        db.close()


def _run_sync():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(sync_mod.sync_all_user_limits(db))
    finally:
        db.close()


def test_second_identical_sweep_pushes_nothing(monkeypatch):
    calls: list[tuple] = []

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True):
            pass

        def set_user_limit(self, uid, limit):
            calls.append((uid, limit))
            return True

    monkeypatch.setattr(sync_mod, "NodeRequests", FakeRequests)
    node_id, user_id, name = _seed()
    try:
        def ours():
            return [c for c in calls if c[0] == str(user_id)]

        first = _run_sync()
        assert first["success"] >= 1
        assert ours() == [(str(user_id), 1)]

        calls.clear()
        quiet = _run_sync()
        assert ours() == []  # unchanged pair skipped
        assert quiet["skipped"] >= 1

        # One limit change re-pushes exactly that pair.
        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            db.query(User).filter(User.id == user_id).update({"max_logins": 2})
            db.commit()
        finally:
            db.close()
        calls.clear()
        _run_sync()
        assert ours() == [(str(user_id), 2)]
    finally:
        _cleanup(node_id, name)


def test_failed_push_is_retried_next_sweep(monkeypatch):
    calls: list[tuple] = []
    fail_next = {"n": 1}
    target = {}

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True):
            pass

        def set_user_limit(self, uid, limit):
            calls.append((uid, limit))
            if uid == target.get("uid") and fail_next["n"] > 0:
                fail_next["n"] -= 1
                raise ConnectionError("node down")
            return True

    monkeypatch.setattr(sync_mod, "NodeRequests", FakeRequests)
    node_id, user_id, name = _seed()
    target["uid"] = str(user_id)
    try:
        def ours():
            return [c for c in calls if c[0] == str(user_id)]

        _run_sync()
        assert ours() == [(str(user_id), 1)]  # attempted once, failed
        _run_sync()
        assert ours() == [(str(user_id), 1), (str(user_id), 1)]  # retried, not dropped
    finally:
        _cleanup(node_id, name)
