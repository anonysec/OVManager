# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Tests for the live layer: event bus, snapshot cache, and the SSE endpoint."""

import asyncio

from fastapi.testclient import TestClient

from backend.app import api
from backend.config import config
from backend.operations import live


def _owner_headers() -> dict:
    from backend.auth.auth import create_access_token

    token = create_access_token({"sub": config.ADMIN_USERNAME, "role": "owner"})
    return {"Authorization": f"Bearer {token}"}


# ── LiveBus ────────────────────────────────────────────────────────────────


def test_bus_publish_without_subscribers_is_noop():
    live.publish("users", {"op": "nobody-listens"})  # must not raise


async def test_bus_delivers_to_subscriber():
    q = live.bus.subscribe()
    try:
        live.publish("users", {"op": "unit"})
        evt = await asyncio.wait_for(q.get(), timeout=1)
        assert evt.topic == "users"
        assert evt.data["op"] == "unit"
    finally:
        live.bus.unsubscribe(q)


async def test_bus_evicts_oldest_for_slow_consumer():
    q = live.bus.subscribe(max_queue=1)
    try:
        live.publish("users", {"op": "one"})
        live.publish("users", {"op": "two"})
        evt = await asyncio.wait_for(q.get(), timeout=1)
        assert evt.data["op"] == "two"  # freshest wins, "one" was evicted
    finally:
        live.bus.unsubscribe(q)


# ── LiveSnapshot ───────────────────────────────────────────────────────────


def test_snapshot_reports_changes():
    snap = live.LiveSnapshot()
    assert snap.last_poll_ts == 0.0
    assert snap.update({"a": 1}, {"n1": True}) == (True, True)
    assert snap.update({"a": 1}, {"n1": True}) == (False, False)  # no change → no event
    assert snap.update({"a": 2}, {"n1": True}) == (True, False)
    assert snap.update({"a": 2}, {"n1": False}) == (False, True)
    assert snap.get_connections() == {"a": 2}
    assert snap.get_nodes() == {"n1": False}
    assert snap.last_poll_ts > 0


# ── SSE endpoint ───────────────────────────────────────────────────────────


def test_live_stream_requires_auth():
    client = TestClient(api)
    resp = client.get("/api/live/stream")
    assert resp.status_code in (401, 403)


async def test_live_stream_sends_ready_event():
    """Drive the real ASGI app (full middleware stack) with a raw scope.

    TestClient/httpx streaming deadlocks on infinite generators in some
    Starlette versions, so we collect ASGI messages directly: response start,
    then the first body chunk must be the SSE "ready" frame. An
    http.disconnect after the first chunk terminates the stream cleanly.
    """
    from backend.auth.auth import create_access_token

    token = create_access_token({"sub": config.ADMIN_USERNAME, "role": "owner"})
    headers = [(b"authorization", f"Bearer {token}".encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/live/stream",
        "raw_path": b"/api/live/stream",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
    }
    messages: list = []

    async def receive():
        # Give the app room to emit response start + the ready chunk, then hang up.
        await asyncio.sleep(0.5)
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    task = asyncio.create_task(api(scope, receive, send))
    try:
        await asyncio.wait_for(task, timeout=5)
    except TimeoutError:
        task.cancel()

    start = next((m for m in messages if m["type"] == "http.response.start"), None)
    assert start is not None, "no response start was sent"
    assert start["status"] == 200
    resp_headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert resp_headers.get("content-type", "").startswith("text/event-stream")
    assert resp_headers.get("x-accel-buffering") == "no"
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert b"event: ready" in body


# ── User list reads the connection cache ───────────────────────────────────


def test_users_list_uses_live_connection_cache(monkeypatch):
    from backend.app import _run_migrations

    _run_migrations()

    from backend.db.crud import create_user, get_user_by_name
    from backend.db.engine import SessionLocal
    from backend.schema._input import CreateUser

    db = SessionLocal()
    try:
        if get_user_by_name(db, "livecache_qa_user") is None:
            import datetime as dt

            req = CreateUser(name="livecache_qa_user", expiry_date=dt.date.today() + dt.timedelta(days=30), total=1024)
            create_user(db, req, "owner")
    finally:
        db.close()

    # The collector is not running in tests; simulate one successful poll.
    monkeypatch.setattr(live, "get_connection_counts", lambda: {"livecache_qa_user": 3})
    monkeypatch.setattr(live, "last_poll_ts", lambda: 1.0)

    client = TestClient(api)
    resp = client.get("/api/users/", headers=_owner_headers())
    assert resp.status_code == 200
    users = resp.json()["data"]["users"]
    match = [u for u in users if u["name"] == "livecache_qa_user"]
    assert match, "seeded user missing from list"
    assert match[0]["active_connections"] == 3
    assert match[0]["online"] is True
