"""Per-node connection manager: persistent NodeRequests + health tracking.

Replaces per-call ``node_client(node)`` construction, which rebuilt TLS
state on every RPC. A connection is keyed by the fields that actually
change a transport (address, port, key, pinned CA) — a metadata-only edit
(name, tags) keeps the live connection; changing any signature field
replaces it. Health is an explicit state machine so poll loops can skip
BROKEN nodes cheaply instead of paying full timeouts every tick.

The client class is resolved lazily inside :func:`get_connection`: this
module is imported from the bottom of ``requests.py`` to break the import
cycle, so a module-level from-import here would see a partially
initialized module.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.node.requests import NodeRequests


class NodeHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    BROKEN = "broken"


@dataclass(frozen=True)
class ConnectionSignature:
    """Fields that, if changed, require replacing the transport."""

    address: str
    port: int
    api_key: str
    server_ca: str | None = None

    @classmethod
    def from_node(cls, node) -> ConnectionSignature:
        return cls(
            address=str(getattr(node, "address", "") or ""),
            port=int(getattr(node, "port", 0) or 0),
            api_key=str(getattr(node, "key", "") or ""),
            server_ca=str(getattr(node, "server_ca", "") or "") or None,
        )


@dataclass
class Connection:
    client: NodeRequests
    signature: ConnectionSignature
    health: NodeHealth = NodeHealth.UNKNOWN
    last_ok: float = 0.0
    last_failure: float = 0.0


_HEALTH_TTL = 300.0

_lock = threading.Lock()
_connections: dict[int, Connection] = {}


def get_connection(node) -> NodeRequests:
    """Return a live client for ``node``, replacing it on signature change.

    Nodes without an ``id`` (test doubles) construct fresh clients and are
    never cached.
    """
    from backend.node.requests import NodeRequests

    node_id = getattr(node, "id", None)
    signature = ConnectionSignature.from_node(node)
    if node_id is None:
        return NodeRequests(
            address=signature.address,
            port=signature.port,
            api_key=signature.api_key,
        )
    node_id = int(node_id)
    with _lock:
        conn = _connections.get(node_id)
        if conn is not None and conn.signature == signature:
            return conn.client

    client = NodeRequests(
        address=signature.address,
        port=signature.port,
        api_key=signature.api_key,
        server_ca=signature.server_ca,
        node_id=node_id,
    )
    with _lock:
        conn = _connections.get(node_id)
        if conn is not None and conn.signature == signature:
            return conn.client
        conn = Connection(client=client, signature=signature, health=NodeHealth.UNKNOWN)
        _connections[node_id] = conn
        return conn.client


def record(node_id: int | None, ok: bool) -> None:
    """Record an RPC outcome by node id.

    The id form exists because ``NodeRequests`` keeps only the id: it is built
    from a signature, not from the ORM row. Recording from the single choke
    point in ``_request`` is what makes ``healthy()`` meaningful for callers
    that use the client directly instead of ``connection.request()`` — the
    read fanouts, which are the ones a dead node costs the most.
    """
    if node_id is None:
        return
    node_id = int(node_id)
    with _lock:
        conn = _connections.get(node_id)
        if conn is None:
            return
        if ok:
            conn.health = NodeHealth.HEALTHY
            conn.last_ok = time.monotonic()
        else:
            conn.health = NodeHealth.BROKEN
            conn.last_failure = time.monotonic()


def healthy(node) -> bool:
    """Cheap health check honoring the TTL (True while UNKNOWN, never
    positive-health on stale data — poll loops skip BROKEN only)."""
    node_id = getattr(node, "id", None)
    if node_id is None:
        return True
    with _lock:
        conn = _connections.get(int(node_id))
        if conn is None:
            return True
        if conn.health is NodeHealth.BROKEN:
            return False
        if conn.health is NodeHealth.HEALTHY and time.monotonic() - conn.last_ok <= _HEALTH_TTL:
            return True
        return True


BROKEN_PROBE_TIMEOUT = 3.0


def probe_timeout(node) -> float:
    """Timeout to use when periodically probing this node.

    A node that has already failed gets a short one, so re-checking it is
    nearly free and a node that comes back is noticed on the very next cycle.
    Skipping a broken node for 60s instead cost a full 30s timeout per 90s
    window and delayed a recovered node's return.
    """
    if healthy(node):
        from backend.node.requests import LONG_TIMEOUT

        return LONG_TIMEOUT
    return BROKEN_PROBE_TIMEOUT


def forget(node_id: int) -> None:
    """Drop the connection entry (node deleted)."""
    with _lock:
        _connections.pop(int(node_id), None)


def _reset_for_tests() -> None:
    """Test-only: clear the registry and health state."""
    with _lock:
        _connections.clear()


def request(node, method: str, path: str, **kw):
    """One RPC through the connection manager.

    Returns the parsed envelope (or None) like ``NodeRequests._request``.
    Health is recorded by ``_request`` itself, so callers that hold a
    ``NodeRequests`` directly get the same bookkeeping.
    """
    client = get_connection(node)
    return client._request(method, path, **kw)  # noqa: SLF001
