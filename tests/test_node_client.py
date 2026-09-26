"""Tests for the node_client() construction seam.

node_client() is the single place a Node row becomes a NodeRequests.
"""

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
    from backend.node.ops import node_version_compat
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

    from backend.operations import node_pki

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
