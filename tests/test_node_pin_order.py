"""The node API key must never cross an unpinned TLS connection.

Adding a node used to send the long-lived API key in ``check_node()`` and
``update_config()`` *before* ``_pin_node_certificate()`` stored the pin, so a
first-contact MITM captured the key and only later calls were protected.

Order is the whole fix, so it is asserted directly: the pin must be fetched
before any keyed request is attempted.
"""

import pytest

from backend.schema import NodeCreate

CERT_PEM = "-----BEGIN CERTIFICATE-----\nMIIB-pin-order-test\n-----END CERTIFICATE-----\n"


def _payload(**over):
    data = {
        "name": "pin-order-node",
        "address": "10.9.9.9",
        "port": 2083,
        "key": "long-lived-api-key",
        "protocol": "tcp",
        "ovpn_port": 1194,
        "use_tls": True,
        "set_new_setting": False,
    }
    data.update(over)
    return NodeCreate(**data)


@pytest.fixture
def seq(monkeypatch):
    """Record the order of pin-fetch / client-build / keyed-request."""
    events: list[tuple] = []

    def fake_geolocate(address):
        return {"country_code": None, "latitude": None, "longitude": None}

    async def fake_pin(address, port):
        events.append(("pin", address))
        return CERT_PEM

    class FakeNR:
        def __init__(self, **kw):
            events.append(("client", kw.get("server_ca")))

        def check_node(self):
            events.append(("check_node", None))
            return True

        def update_config(self, **kw):
            events.append(("update_config", None))
            return True

    import backend.node.management as ops

    monkeypatch.setattr(ops, "geolocate", fake_geolocate)
    monkeypatch.setattr(ops, "_pin_node_certificate", fake_pin)
    monkeypatch.setattr(ops, "NodeRequests", FakeNR)
    return events


class FakeRow:
    """Stand-in for the Node row create_node() returns."""

    def __init__(self, node_id=4242):
        self.id = node_id
        self.server_ca = None


def _fake_create_node(row):
    def _create(db, request, geo):
        return row

    return _create


@pytest.mark.anyio
async def test_add_node_pins_before_sending_the_key(seq, monkeypatch):
    import backend.node.management as ops

    monkeypatch.setattr(ops.crud, "create_node", _fake_create_node(FakeRow()))

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        await ops.add_node_handler(_payload(set_new_setting=True), db)
    finally:
        db.close()

    kinds = [e[0] for e in seq]
    assert "pin" in kinds, "certificate must be fetched when use_tls is true"
    assert kinds.index("pin") < kinds.index("check_node"), "the pin must be fetched BEFORE the first keyed request"
    assert kinds.index("pin") < kinds.index("update_config")


@pytest.mark.anyio
async def test_add_node_passes_the_pin_to_the_key_sending_client(seq, monkeypatch):
    import backend.node.management as ops

    row = FakeRow()
    monkeypatch.setattr(ops.crud, "create_node", _fake_create_node(row))

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        await ops.add_node_handler(_payload(), db)
    finally:
        db.close()

    assert row.server_ca == CERT_PEM, "the pin must be stored on the node row"

    client_pins = [e[1] for e in seq if e[0] == "client"]
    assert client_pins, "a client must be built"
    assert all(pin == CERT_PEM for pin in client_pins), "every client that sends the API key must verify against the pinned cert"


@pytest.mark.anyio
async def test_update_node_pins_before_sending_the_key(seq, monkeypatch):
    import backend.node.management as ops

    class FakeRow:
        id = 77
        key = "existing-key"
        server_ca = None

    monkeypatch.setattr(ops.crud, "get_node_by_id", lambda db, node_id: FakeRow())
    monkeypatch.setattr(ops.crud, "update_node", lambda db, node_id, req, geo: True)

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        await ops.update_node_handler(77, _payload(set_new_setting=True), db)
    finally:
        db.close()

    kinds = [e[0] for e in seq]
    assert "pin" in kinds
    assert kinds.index("pin") < kinds.index("check_node")
    client_pins = [e[1] for e in seq if e[0] == "client"]
    assert client_pins and all(pin == CERT_PEM for pin in client_pins)


@pytest.mark.anyio
async def test_failed_refetch_keeps_the_existing_pin(monkeypatch):
    """A network blip must not silently downgrade a pinned node."""
    import backend.node.management as ops

    old_pin = "-----BEGIN CERTIFICATE-----\nOLD-PIN\n-----END CERTIFICATE-----\n"
    seen: list = []

    class FakeRow:
        id = 78
        key = "existing-key"
        server_ca = old_pin

    class FakeNR:
        def __init__(self, **kw):
            seen.append(kw.get("server_ca"))

        def check_node(self):
            return True

        def update_config(self, **kw):
            return True

    async def failed_pin(address, port):
        return None

    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    monkeypatch.setattr(ops, "_pin_node_certificate", failed_pin)
    monkeypatch.setattr(ops, "NodeRequests", FakeNR)
    monkeypatch.setattr(ops.crud, "get_node_by_id", lambda db, node_id: FakeRow())
    monkeypatch.setattr(ops.crud, "update_node", lambda db, node_id, req, geo: True)

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        await ops.update_node_handler(78, _payload(set_new_setting=True), db)
    finally:
        db.close()

    assert seen == [old_pin], "the previous pin must still guard the keyed request"


def _real_self_signed_pem() -> str:
    """A parseable certificate, unlike ``CERT_PEM`` above.

    The no-id path hands the PEM to ``ssl`` as ``cadata``, which parses it —
    the placeholder string in this file is not a certificate and cannot
    stand in for that.
    """
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=1))
        .not_valid_after(_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.mark.anyio
async def test_add_node_uses_provided_cert_without_fetching(seq, monkeypatch):
    """A pasted PEM is the pin; no TOFU fetch is attempted."""
    import backend.node.management as ops

    row = FakeRow()
    monkeypatch.setattr(ops.crud, "create_node", _fake_create_node(row))

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        await ops.add_node_handler(_payload(cert=CERT_PEM), db)
    finally:
        db.close()

    assert row.server_ca == CERT_PEM
    assert all(e[0] != "pin" for e in seq), "no TOFU fetch when the operator pasted a cert"
    client_pins = [e[1] for e in seq if e[0] == "client"]
    assert client_pins and all(pin == CERT_PEM for pin in client_pins)


def test_cert_validator_requires_pem_markers():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _payload(cert="not a certificate")
    assert _payload(cert="   ").cert is None


@pytest.mark.anyio
async def test_add_node_with_tls_survives_pinning_before_the_row_exists(monkeypatch):
    """The real client must accept the pin the handler fetches before create.

    ``add_node_handler`` pins the certificate *before* ``crud.create_node``,
    so the client is built with a ``server_ca`` and **no** ``node_id``: there
    is no row yet, so there is no id to name the pinned file after. Rejecting
    that combination made every TLS Add Node answer HTTP 500 while "Test
    connection" kept reporting the node reachable — that endpoint builds a
    client with no pin, so it never hit the guard.

    The order tests above cannot see this. They replace ``NodeRequests`` with
    ``FakeNR``, so the one thing they never run is the constructor that
    refuses the input.
    """
    import backend.node.management as ops

    pem = _real_self_signed_pem()
    created: list = []

    async def real_pin(address, port):
        return pem

    class RealRow:
        id = 4242
        server_ca = None

    # Keep the real constructor — it is the code under test — and stub only
    # the wire, so a network failure cannot stand in for a construction one.
    monkeypatch.setattr("backend.node.requests.NodeRequests.check_node", lambda self, **kw: True)
    monkeypatch.setattr("backend.node.requests.NodeRequests.update_config", lambda self, **kw: True)
    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    monkeypatch.setattr(ops, "_pin_node_certificate", real_pin)
    monkeypatch.setattr(ops.crud, "create_node", lambda db, req, geo: created.append(1) or RealRow())

    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        result = await ops.add_node_handler(_payload(set_new_setting=False), db)
    finally:
        db.close()

    assert created, "the handler must get past building the keyed client"
    assert result is True
