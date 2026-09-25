# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Per-node connection manager: persistent NodeRequests + health tracking.

Replaces per-call ``node_client(node)`` construction, which rebuilt TLS
state on every RPC. A connection is keyed by the fields that actually
change a transport (address, port, key, TLS flag) — a metadata-only edit
(name, tags) keeps the live connection; changing any signature field
replaces it. Health is an explicit state machine so poll loops can skip
BROKEN nodes cheaply instead of paying full timeouts every tick.

Single process + scheduler-driven access, so the registry lock only
guards dict replacement, not RPCs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum

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
    use_tls: bool

    @classmethod
    def from_node(cls, node) -> ConnectionSignature:
        return cls(
            address=str(getattr(node, "address", "") or ""),
            port=int(getattr(node, "port", 0) or 0),
            api_key=str(getattr(node, "key", "") or ""),
            use_tls=bool(getattr(node, "use_tls", False)),
        )


@dataclass
class Connection:
    client: NodeRequests
    signature: ConnectionSignature
    health: NodeHealth = NodeHealth.UNKNOWN
    last_ok: float = 0.0
    last_failure: float = 0.0


# Healthy results are trusted for this long without a fresh probe.
_HEALTH_TTL = 300.0

_lock = threading.Lock()
_connections: dict[int, Connection] = {}


def get_connection(node) -> NodeRequests:
    """Return a live client for ``node``, replacing it on signature change.

    Nodes without an ``id`` (test doubles) construct fresh clients and are
    never cached.
    """
    node_id = getattr(node, "id", None)
    signature = ConnectionSignature.from_node(node)
    if node_id is None:
        return NodeRequests(
            address=signature.address,
            port=signature.port,
            api_key=signature.api_key,
            use_tls=signature.use_tls,
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
        use_tls=signature.use_tls,
    )
    with _lock:
        conn = _connections.get(node_id)
        if conn is not None and conn.signature == signature:
            # Lost a construction race: the existing client wins.
            return conn.client
        conn = Connection(client=client, signature=signature, health=NodeHealth.UNKNOWN)
        _connections[node_id] = conn
        return conn.client


def note_success(node) -> None:
    """Record a successful RPC (any endpoint) for the node."""
    node_id = getattr(node, "id", None)
    if node_id is None:
        return
    node_id = int(node_id)
    with _lock:
        conn = _connections.get(node_id)
        if conn is not None:
            conn.health = NodeHealth.HEALTHY
            conn.last_ok = time.monotonic()


def note_failure(node) -> None:
    """Record a failed RPC; marks the node BROKEN."""
    node_id = getattr(node, "id", None)
    if node_id is None:
        return
    node_id = int(node_id)
    with _lock:
        conn = _connections.get(node_id)
        if conn is not None:
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

    Returns the parsed envelope (or None) like ``NodeRequests._request``
    and records success/failure for the node's health state. Callers that
    already hold a ``NodeRequests`` (e.g. custom timeouts in a loop) may
    bypass this and use the client directly.
    """
    client = get_connection(node)
    result = client._request(method, path, **kw)  # noqa: SLF001
    if result is None:
        note_failure(node)
    else:
        note_success(node)
    return result
