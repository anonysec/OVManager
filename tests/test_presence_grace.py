"""Presence grace window, subscriber gating, snapshot node cap (Task 5)."""

import time

from backend.operations.observability import live


class _FakeNode:
    address = "127.0.0.1"
    port = 1
    key = "k"
    use_tls = False

    def __init__(self, name):
        self.name = name


def _reset():
    live.snapshot._connections = {}
    live.snapshot._nodes = {}
    live.snapshot._last_poll_ts = 0.0
    live._grace_until.clear()


def _install(monkeypatch, calls, *, names=("n1",), respond=None):
    from backend.db import crud
    from backend.node import requests as node_requests

    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [_FakeNode(n) for n in names])
    monkeypatch.setattr(crud, "get_user_id_name_pairs", lambda db: [("1", "u1")])

    class _FakeRequests:
        def __init__(self, **kwargs):
            pass

        def get_sessions(self, hours=None, timeout=None):
            calls.append(timeout)
            return {"live_sessions": [{"common_name": "1"}]} if respond is None else respond

    monkeypatch.setattr(node_requests, "NodeRequests", _FakeRequests)


def _watching():
    """A subscriber attached, so the collector is allowed to probe."""
    return live.bus.subscribe()


async def test_down_node_stays_visible_through_the_grace_window(monkeypatch):
    calls: list = []
    _reset()
    _install(monkeypatch, calls)
    await live.collect_live_snapshot()
    assert live.get_node_online() == {"n1": True}

    _install(monkeypatch, calls, respond={})  # node answers empty → down
    q = _watching()
    try:
        await live.collect_live_snapshot()
    finally:
        live.bus.unsubscribe(q)
    assert live.get_node_online() == {"n1": True}, "a node that just went down must stay visible through grace"

    live._grace_until["n1"] = time.monotonic() - live.GRACE_SECONDS - 1
    q = _watching()
    try:
        await live.collect_live_snapshot()
    finally:
        live.bus.unsubscribe(q)
    assert live.get_node_online() == {"n1": False}, "grace must expire into down"


async def test_collector_probes_nothing_without_a_subscriber_once_seeded(monkeypatch):
    calls: list = []
    _reset()
    _install(monkeypatch, calls)
    await live.collect_live_snapshot()
    assert len(calls) == 1, "the first poll seeds the snapshot for /sub/ and health"

    live.snapshot._last_poll_ts = time.monotonic() - live.IDLE_POLL_SECONDS - 1
    await live.collect_live_snapshot()
    assert len(calls) == 1, "an idle panel must not re-probe nodes with no watcher"


async def test_snapshot_caps_the_node_list(monkeypatch):
    calls: list = []
    _reset()
    names = [f"n{i:02d}" for i in range(60)]
    _install(monkeypatch, calls, names=names)
    await live.collect_live_snapshot()

    online = live.get_node_online()
    assert len(online) == 50, f"cap must slice the snapshot to 50 nodes, got {len(online)}"
    assert list(online) == sorted(names)[:50], "the cap slice must be deterministic"
    assert live.get_snapshot_cap() == 50
