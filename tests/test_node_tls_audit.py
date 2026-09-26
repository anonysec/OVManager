"""The self-signed TLS fallback writes one audit event per node address.

``_note_tls_fallback()`` warns loudly once per address; on that same first
occurrence it must also record a single ``node.tls_unverified`` event. The
audit call opens its own DB session (``log_event(None, ...)``), which is safe
here because this runs in a threadpool worker. No network is touched: the
method is called directly.
"""

import uuid

from backend.db.engine import SessionLocal
from backend.node.requests import NodeRequests
from backend.operations.audit import recent_events


def _node(host: str) -> NodeRequests:
    address = f"tlsa_{uuid.uuid4().hex[:8]}.{host}"
    return NodeRequests(address=address, port=2083, api_key="tlsa-key", use_tls=True)


def _fallback(req: NodeRequests) -> None:
    req._note_tls_fallback("/sync/status", RuntimeError("self-signed certificate"))


def test_tls_fallback_audits_once_per_address():
    node_a = _node("a.example")
    node_b = _node("b.example")

    _fallback(node_a)
    _fallback(node_a)  # repeat: already warned, must not add a second row
    _fallback(node_b)

    db = SessionLocal()
    try:
        rows = recent_events(db, limit=500, action="node.tls_unverified")
    finally:
        db.close()

    rows_a = [r for r in rows if r["target"] == node_a.address]
    rows_b = [r for r in rows if r["target"] == node_b.address]
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0]["actor"] is None
    assert "unverified TLS" in rows_a[0]["detail"]
