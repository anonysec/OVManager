"""Tests for the node_client() construction seam.

node_client() is the single place a Node row becomes a NodeRequests.
"""

import asyncio
from types import SimpleNamespace

from backend.node.requests import NodeRequests, node_client


def _node():
    return SimpleNamespace(address="10.0.0.9", port=2083, key="plain-key", use_tls=False)


def test_node_client_maps_row_fields():
    req = node_client(_node())
    assert isinstance(req, NodeRequests)
    assert req.address == "10.0.0.9:2083"
    assert req.headers == {"key": "plain-key"}
    assert req.scheme == "http"


def test_node_client_tls_scheme():
    req = node_client(SimpleNamespace(address="10.0.0.9", port=2083, key="k", use_tls=True))
    assert req.scheme == "https"


def test_retry_after_parsing():
    from backend.node.requests import _retry_after_s

    assert _retry_after_s("7") == 7.0
    assert _retry_after_s(None) == 5.0
    assert _retry_after_s("garbage") == 5.0
    assert _retry_after_s("9999") == 60.0  # capped
    assert _retry_after_s("0") == 1.0  # floored


def test_send_retries_once_on_429_then_succeeds(monkeypatch):
    import backend.node.requests as nr_mod

    calls = []

    class Resp:
        def __init__(self, status, headers=None, payload=None):
            self.status_code = status
            self.headers = headers or {}
            self._payload = payload or {"success": True, "data": {}}

        def json(self):
            return self._payload

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        if len(calls) == 1:
            return Resp(429, {"Retry-After": "0"})
        return Resp(200)

    monkeypatch.setattr(nr_mod._req, "get", fake_get)
    monkeypatch.setattr(nr_mod._time, "sleep", lambda s: None)
    req = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=False)
    assert req._request("get", "/sync/status") == {"success": True, "data": {}}
    assert len(calls) == 2


def test_node_version_compat_policy():
    """Panel must distinguish node versions: same major is compatible,
    newer nodes are flagged, other majors and garbage are not compatible."""
    from backend.node.management import node_version_compat
    from backend.version import __version__

    major = __version__.split(".")[0]
    assert node_version_compat(__version__)["verdict"] == "compatible"
    assert node_version_compat(f"{major}.0.0")["verdict"] == "compatible"
    assert node_version_compat("v" + __version__)["verdict"] == "compatible"
    newer = node_version_compat("9999.0.0")
    assert newer["verdict"] in ("node-newer", "incompatible"), newer
    assert node_version_compat("0.0.1")["verdict"] == "incompatible"
    for bad in (None, "", "not-a-version", "1.x"):
        assert node_version_compat(bad)["verdict"] == "unknown", bad


def _self_signed_pem() -> str:
    """Real self-signed cert for the pinned-context test (a fake PEM cannot
    load into an SSLContext)."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_pinned_ca_verifies_against_the_pin(monkeypatch, tmp_path):
    """With server_ca, HTTPS verifies against exactly that file — and an
    SSL failure must NOT fall back to unverified (the API key would cross
    to a possible MITM)."""
    import ssl

    from backend.node import pki as node_pki

    real_dir = node_pki._CERT_DIR
    node_pki._CERT_DIR = tmp_path / "node-certs"
    try:
        pem = _self_signed_pem()
        req = NodeRequests(
            address="10.0.0.9",
            port=2083,
            api_key="k",
            use_tls=True,
            server_ca=pem,
            node_id=7,
        )
        assert req.scheme == "https"
        ca_path = node_pki._CERT_DIR / "7.pem"
        assert ca_path.exists() and pem in ca_path.read_text()

        from backend.node import requests as nr_mod

        # The pinned session requires the chain but skips the hostname: the
        # node cert names localhost while the panel dials the public IP, so
        # the exact cert (not its subject) is the identity proof.
        sender = nr_mod._pinned_sender(str(ca_path))
        adapter = sender.__self__.get_adapter("https://x")
        assert adapter._pinned_context.check_hostname is False
        assert adapter._pinned_context.verify_mode == ssl.CERT_REQUIRED

        captured = {}

        def fake_send(self, method, path, **kw):
            captured["sender"] = kw.get("sender")
            assert kw.get("verify", None) is None, "pinned path must not pass verify= (hostname would fail)"
            return {"success": True}

        monkeypatch.setattr(NodeRequests, "_send", fake_send)
        out = req._request("get", "/sync/status")
        assert out == {"success": True}
        assert captured["sender"] is not None
        assert req.tls_verified is True

        def ssl_send(self, method, path, **kw):
            raise nr_mod._req.exceptions.SSLError("cert mismatch")

        monkeypatch.setattr(NodeRequests, "_send", ssl_send)
        assert req._request("get", "/sync/status") is None
    finally:
        node_pki._CERT_DIR = real_dir
        from backend.node import connection as _conn

        _conn._reset_for_tests()


def test_a_pin_works_before_the_node_row_exists(monkeypatch):
    """Add Node has no node id yet, so the PEM itself must pin the connection.

    ``add_node_handler`` fetches the certificate and builds the keyed client
    *before* ``crud.create_node``, so there is no row and no id to name the
    pinned file after. The PEM is the only thing there is to verify against.

    Asserting only "it does not raise" would also accept a fix that silently
    drops the pin and sends the API key down the unverified path — the exact
    thing pinning exists to prevent — so the pinned sender is asserted here.
    """
    import ssl

    from backend.node import requests as nr_mod

    pem = _self_signed_pem()
    req = NodeRequests(address="10.0.0.9", port=2083, api_key="k", use_tls=True, server_ca=pem)

    assert req._verify != "pinned", "the fetched pin was dropped — the key would cross unpinned"

    adapter = nr_mod._pinned_sender(req._verify).__self__.get_adapter("https://x")
    assert adapter._pinned_context.check_hostname is False
    assert adapter._pinned_context.verify_mode == ssl.CERT_REQUIRED

    captured = {}

    def fake_send(self, method, path, **kw):
        captured["sender"] = kw.get("sender")
        return {"success": True}

    monkeypatch.setattr(NodeRequests, "_send", fake_send)
    assert req._request("get", "/sync/status") == {"success": True}
    assert captured["sender"] is not None, "the pinned sender must be used, not the unverified fallback"
    assert req.tls_verified is True


def _registered_node(node_id=4242):
    """A node that the connection manager holds a live client for."""
    from backend.db import crud  # noqa: F401  (ensures the models are importable)
    from backend.node import connection

    node = SimpleNamespace(id=node_id, address="10.0.0.9", port=2083, key="k", use_tls=False, server_ca=None)
    connection.get_connection(node)
    return node


def test_direct_client_use_still_records_health(monkeypatch):
    """The read fanouts use the client directly, so health must be recorded there.

    Before this, only connection.request() recorded an outcome, so a node that
    only ever failed inside a fanout stayed UNKNOWN forever and nothing could
    skip it.
    """
    from backend.node import connection

    connection._reset_for_tests()
    node = _registered_node()
    client = connection.get_connection(node)
    assert client.node_id == node.id
    assert connection.healthy(node) is True, "unknown is not broken"

    # __slots__ makes the client read-only for new attributes, so stub the class.
    monkeypatch.setattr(type(client), "_request_inner", lambda self, *a, **k: None)
    assert client._request("get", "/sync/sessions") is None
    assert connection.healthy(node) is False, "a failed RPC must mark the node broken"

    monkeypatch.setattr(type(client), "_request_inner", lambda self, *a, **k: {"success": True})
    assert client._request("get", "/sync/sessions") == {"success": True}
    assert connection.healthy(node) is True, "a success must clear the broken state"


def test_client_without_a_node_id_is_not_recorded(monkeypatch):
    """Test doubles and signature-only clients have no id; recording must no-op."""
    from backend.node import connection

    connection._reset_for_tests()
    client = NodeRequests(address="10.0.0.9", port=2083, api_key="k")
    assert client.node_id is None
    monkeypatch.setattr(type(client), "_request_inner", lambda self, *a, **k: None)
    assert client._request("get", "/x") is None  # must not raise


def test_active_connection_counts_asks_a_broken_node_cheaply(monkeypatch):
    """The user-list path must not pay 30s for a node it knows is down.

    It is still asked — skipping it entirely is what delayed recovery by up to
    90s — but it is asked with the short timeout, and the healthy node is asked
    with the long one.
    """
    from backend.node import connection, diagnostics
    from backend.node.requests import LONG_TIMEOUT

    connection._reset_for_tests()
    good = _registered_node(1)
    bad = _registered_node(2)
    connection.record(bad.id, False)

    seen: dict = {}

    class FakeClient:
        def __init__(self, node):
            self.node = node

        def get_sessions(self, hours=None, timeout=None):
            seen[self.node.id] = timeout
            sessions = [{"common_name": "7"}] if self.node.id == good.id else []
            return {"live_sessions": sessions}

    monkeypatch.setattr(diagnostics, "node_client", lambda node: FakeClient(node))
    monkeypatch.setattr(diagnostics.crud, "get_active_nodes", lambda db: [good, bad])
    monkeypatch.setattr(diagnostics.crud, "get_user_id_name_pairs", lambda db: [("7", "alice")])

    counts = asyncio.run(diagnostics.get_active_connection_counts(object()))

    assert set(seen) == {good.id, bad.id}, "both nodes must still be asked, or a dead one is sealed out"
    assert seen[good.id] == LONG_TIMEOUT
    assert seen[bad.id] == connection.BROKEN_PROBE_TIMEOUT
    assert counts == {"alice": 1}


def test_rpc_error_map_is_bounded():
    """Keyed by (address, path): a churning address set must not grow it forever."""
    import backend.node.requests as nr

    original = dict(nr._rpc_last_error)
    try:
        nr._rpc_last_error.clear()
        for i in range(nr._RPC_ERROR_CAP + 50):
            nr._rpc_failed(f"10.0.0.{i}:2083", "/sync/status", "boom")
        assert len(nr._rpc_last_error) <= nr._RPC_ERROR_CAP
    finally:
        nr._rpc_last_error.clear()
        nr._rpc_last_error.update(original)
