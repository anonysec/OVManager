# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Server-side live data: in-process event bus + node snapshot collector.

Architecture (step 1 of the realtime plan):

- ONE background collector polls all nodes on a fixed interval and stores the
  result in an in-memory snapshot (per-user live connection counts, per-node
  reachability). HTTP handlers read the cache instead of fanning out to every
  node per request — a dead node can no longer stall the user list.
- Subscribers (SSE connections) receive lightweight invalidation events
  ("users", "usage", "nodes") and the frontend refetches exactly like it did
  during 8s polling. The wire payload is intentionally small.

Everything is single-process in-memory (uvicorn runs with workers=1); there is
no external broker to operate.
"""

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field

from backend.logger import logger

# How often the collector polls nodes. 10s feels live in the UI while being
# far gentler than the old per-page-load fan-out.
POLL_SECONDS = float(os.getenv("OVMANAGER_LIVE_POLL_SECONDS", "10"))

# How often to poll when nobody has the live stream open. The snapshot also
# feeds the public subscription page (/sub/...), which has no SSE channel of
# its own, so it must never go permanently stale — but there is no reason to
# hit every node every 10 seconds for an audience of nobody.
IDLE_POLL_SECONDS = float(os.getenv("OVMANAGER_LIVE_IDLE_POLL_SECONDS", "300"))


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
        """True when at least one SSE client is connected."""
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
                # Slow consumer: drop the oldest event. Live UI events are
                # invalidation hints — freshness matters more than history.
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

    def update(self, connections: dict[str, int], nodes: dict[str, bool]) -> tuple[bool, bool]:
        """Store a new snapshot. Returns (connections_changed, nodes_changed)."""
        with self._lock:
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

    @property
    def last_poll_ts(self) -> float:
        with self._lock:
            return self._last_poll_ts


snapshot = LiveSnapshot()


# Module-level accessors (used by request handlers).
def get_connection_counts() -> dict[str, int]:
    return snapshot.get_connections()


def get_node_online() -> dict[str, bool]:
    return snapshot.get_nodes()


def last_poll_ts() -> float:
    return snapshot.last_poll_ts


def publish(topic: str, data: dict | None = None) -> None:
    """Publish an invalidation event to all live subscribers."""
    bus.publish(topic, data)


async def collect_live_snapshot() -> None:
    """Poll every active node once and refresh the in-memory snapshot.

    Runs as a single scheduled job (default every 10s). Replaces the previous
    pattern where each HTTP page load and each browser tab queried all nodes
    directly. Node failures never propagate: a dead node simply contributes
    zero sessions, exactly like the old per-request code tolerated errors.

    Events are published only when the snapshot actually changed, so idle
    panels emit no SSE traffic beyond heartbeats.
    """
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.node.requests import NodeRequests

    # Nothing is watching and the snapshot is still fresh enough for the
    # non-SSE consumers: skip the fan-out entirely. With no browser open this
    # turns a node probe every 10s into one every IDLE_POLL_SECONDS.
    if not bus.has_subscribers():
        last = snapshot.last_poll_ts
        if last > 0 and (time.monotonic() - last) < IDLE_POLL_SECONDS:
            return

    db = SessionLocal()
    try:
        nodes = crud.get_active_nodes(db)
        # Only (id, name) is needed to map a node's common_name back to a
        # username; loading full ORM objects here every 10s for a panel with
        # thousands of users was a needless allocation.
        id_to_name = dict(crud.get_user_id_name_pairs(db))
    except Exception as exc:
        logger.error("live collector: DB read failed: %s", exc)
        db.close()
        return
    finally:
        db.close()

    if not nodes:
        counts_changed, nodes_changed = snapshot.update({}, {})
        if nodes_changed:
            publish("nodes", {"op": "snapshot"})
        return

    def probe(node) -> tuple[object, dict]:
        # The sessions summary is a superset of the health check: a node that
        # answers with any payload is up; an unreachable node returns {}.
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls)
        return node, req.get_sessions(hours=1)

    results = await asyncio.gather(
        *[asyncio.to_thread(probe, n) for n in nodes],
        return_exceptions=True,
    )

    counts: dict[str, int] = {}
    online: dict[str, bool] = {}
    for item in results:
        if isinstance(item, Exception):
            logger.warning("live collector: node probe failed: %s", item)
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

    counts_changed, nodes_changed = snapshot.update(counts, online)
    if nodes_changed:
        publish("nodes", {"op": "status"})
    if counts_changed:
        publish("users", {"op": "connections"})
