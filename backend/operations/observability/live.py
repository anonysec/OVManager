"""Server-side live data: in-process event bus + node snapshot collector.

ONE background collector polls all nodes on a fixed interval and stores the
result in an in-memory snapshot (per-user live connection counts, per-node
reachability). HTTP handlers read the cache instead of fanning out to every
node per request, so a dead node cannot stall the user list.

Subscribers (SSE connections) receive lightweight invalidation events
("users", "usage", "nodes") and the frontend refetches; the wire payload is
intentionally small. Everything is single-process in-memory (uvicorn runs
with workers=1); there is no external broker to operate.
"""

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field

from backend.logger import logger

POLL_SECONDS = float(os.getenv("OVMANAGER_LIVE_POLL_SECONDS", "10"))

IDLE_POLL_SECONDS = float(os.getenv("OVMANAGER_LIVE_IDLE_POLL_SECONDS", "300"))

GRACE_SECONDS = float(os.getenv("OVMANAGER_LIVE_GRACE_SECONDS", "20"))

SNAPSHOT_MAX_NODES = 50
SNAPSHOT_MAX_NODES_KEY = "telemetry.snapshot_max_nodes"

_grace_until: dict[str, float] = {}  # node name → monotonic deadline while a fresh failure is held up


@dataclass
class LiveEvent:
    topic: str  # "users" | "usage" | "nodes"
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class LiveBus:
    """Fan-out pub/sub with one asyncio.Queue per subscriber.

    publish() is safe to call from any thread (async endpoints, APScheduler
    executor threads, sync CRUD helpers): delivery is scheduled on the event
    loop captured when the first subscriber registers. With no subscribers
    (tests, CLI tooling) publish() is a cheap no-op.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def subscribe(self, *, max_queue: int = 100) -> asyncio.Queue:
        """Register a subscriber. Must be called from the serving event loop."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        with self._lock:
            self._subscribers.add(q)
            self._loop = loop
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def has_subscribers(self) -> bool:
        with self._lock:
            return bool(self._subscribers)

    def publish(self, topic: str, data: dict | None = None) -> None:
        with self._lock:
            loop = self._loop
            subs = list(self._subscribers)
        if loop is None or not subs:
            return
        event = LiveEvent(topic=topic, data=data or {})
        try:
            loop.call_soon_threadsafe(self._deliver, subs, event)
        except RuntimeError:  # loop already closed (shutdown race)
            pass

    @staticmethod
    def _deliver(subs: list[asyncio.Queue], event: LiveEvent) -> None:
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass


bus = LiveBus()


class LiveSnapshot:
    """Last-known node reachability + per-user live connection counts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, int] = {}
        self._nodes: dict[str, bool] = {}
        self._last_poll_ts: float = 0.0
        self._cap: int = SNAPSHOT_MAX_NODES

    def update(self, connections: dict[str, int], nodes: dict[str, bool], cap: int | None = None) -> tuple[bool, bool]:
        """Store a new snapshot. Returns (connections_changed, nodes_changed)."""
        with self._lock:
            if cap and len(nodes) > cap:
                nodes = dict(sorted(nodes.items())[:cap])
            self._cap = cap or SNAPSHOT_MAX_NODES
            counts_changed = connections != self._connections
            nodes_changed = nodes != self._nodes
            self._connections = dict(connections)
            self._nodes = dict(nodes)
            self._last_poll_ts = time.monotonic()
            return counts_changed, nodes_changed

    def get_connections(self) -> dict[str, int]:
        with self._lock:
            return dict(self._connections)

    def get_nodes(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._nodes)

    def get_cap(self) -> int:
        with self._lock:
            return self._cap

    @property
    def last_poll_ts(self) -> float:
        with self._lock:
            return self._last_poll_ts


snapshot = LiveSnapshot()


def get_connection_counts() -> dict[str, int]:
    return snapshot.get_connections()


def get_node_online() -> dict[str, bool]:
    return snapshot.get_nodes()


def last_poll_ts() -> float:
    return snapshot.last_poll_ts


def get_snapshot_cap() -> int:
    return snapshot.get_cap()


def publish(topic: str, data: dict | None = None) -> None:
    bus.publish(topic, data)


def _apply_grace(online: dict[str, bool], prev: dict[str, bool], now: float) -> dict[str, bool]:
    """Hold a node that just went down as up until the grace window expires.

    A node that was up and now fails (empty answer or probe exception) stays
    visible for GRACE_SECONDS so a single blip does not flash the whole panel
    offline. A node that was already down gets no grace.
    """
    for name in set(prev) | set(online):
        if online.get(name, False):
            _grace_until.pop(name, None)
            online[name] = True
            continue
        until = _grace_until.get(name)
        if until is None and prev.get(name, False):
            until = _grace_until[name] = now + GRACE_SECONDS
        if until is not None and now >= until:
            _grace_until.pop(name, None)
            online[name] = False
        else:
            online[name] = until is not None
    return online


async def collect_live_snapshot() -> None:
    """Poll every active node once and refresh the in-memory snapshot.

    Runs as a single scheduled job (default every 10s), replacing the old
    pattern where each page load and each browser tab queried all nodes
    directly. Node failures never propagate: a dead node simply contributes
    zero sessions.

    Events are published only when the snapshot actually changed, so idle
    panels emit no SSE traffic beyond heartbeats.
    """
    from functools import partial

    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.node.connection import probe_timeout
    from backend.node.fanout import gather_background
    from backend.node.requests import node_client, panel_id_for

    if not bus.has_subscribers() and snapshot.last_poll_ts > 0:
        return

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    db = SessionLocal()
    try:
        nodes = crud.get_active_nodes(db)
        id_to_name = dict(crud.get_user_id_name_pairs(db))
        # Read while the session is open — the probes below run after close.
        pid = panel_id_for(db)
        try:
            cap_row = db.execute(text("SELECT value FROM settings_kv WHERE key = :k"), {"k": SNAPSHOT_MAX_NODES_KEY}).scalar()
            cap = int(cap_row)
        except (OperationalError, TypeError, ValueError):
            cap = SNAPSHOT_MAX_NODES
    except Exception as exc:
        logger.error("live collector: DB read failed: %s", exc)
        db.close()
        return
    finally:
        db.close()

    if not nodes:
        counts_changed, nodes_changed = snapshot.update({}, {}, cap=cap)
        if nodes_changed:
            publish("nodes", {"op": "snapshot"})
        return

    def probe(node) -> tuple[object, dict]:
        req = node_client(node, panel_id=pid)
        return node, req.get_sessions(hours=1, timeout=probe_timeout(node))

    results = await gather_background([partial(probe, n) for n in nodes])

    counts: dict[str, int] = {}
    online: dict[str, bool] = {}
    for item in results:
        if isinstance(item, Exception):
            logger.debug("live collector: node probe failed: %s", item)
            continue
        node, data = item
        if not isinstance(data, dict) or not data:
            online[node.name] = False
            continue
        online[node.name] = True
        for sess in data.get("live_sessions") or []:
            cn = sess.get("common_name", "")
            username = id_to_name.get(cn, cn)
            if username:
                counts[username] = counts.get(username, 0) + 1

    online = _apply_grace(online, snapshot.get_nodes(), time.monotonic())
    counts_changed, nodes_changed = snapshot.update(counts, online, cap=cap)
    if nodes_changed:
        publish("nodes", {"op": "status"})
    if counts_changed:
        publish("users", {"op": "connections"})
