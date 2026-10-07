"""Part F: certificate-required node add (no TOFU), X-Panel-ID, node 409
surfacing, owner-inclusive admin rename, and the claim username/verify.

The suite shares one SQLite database, so every test that moves the owner's
username or clears its credential is undone by the autouse teardown below —
without it the next login test in the suite would fail for reasons that have
nothing to do with the code under test.

This file also absorbs the still-valid coverage of the retired
``test_node_pin_order.py``: a pasted PEM is the pin, it reaches the keyed
client, and the constructor accepts it before the node row exists.
"""

import uuid as uuid_mod

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import TEST_OWNER_PASSWORD
from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.db.models import Admin, AuthSession, User
from backend.node.requests import NodeRequests, node_client, panel_id_for
from backend.routers import owner_claim
from backend.schema import NodeCreate

CERT_PEM = "-----BEGIN CERTIFICATE-----\nMIIB-partf-test\n-----END CERTIFICATE-----\n"
OLD_PIN = "-----BEGIN CERTIFICATE-----\nOLD-PIN\n-----END CERTIFICATE-----\n"
RENAMED_OWNER = "partf_owner_renamed"
CLAIMED_OWNER = "partf_claim_owner"
CLAIM_KEY = "0123456789abcdef0123456789abcdef"
CSRF = {"X-Requested-With": "XMLHttpRequest"}


# ── helpers ───────────────────────────────────────────────────────────────


def _token(username: str, role: str) -> str:
    db = SessionLocal()
    try:
        return create_session(db, username, role, user_agent="pytest", ip="127.0.0.1")
    finally:
        db.close()


def _auth(username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {_token(username, role)}"}


def _owner_headers() -> dict:
    return _auth(config.ADMIN_USERNAME, "owner")


def _payload(**over) -> NodeCreate:
    data = {
        "name": "partf-node",
        "address": "10.9.9.9",
        "port": 2083,
        "key": "long-lived-api-key",
        "protocol": "tcp",
        "ovpn_port": 1194,
    }
    data.update(over)
    return NodeCreate(**data)


def _make_user(name: str, owner: str) -> None:
    from datetime import date, timedelta

    db = SessionLocal()
    try:
        if db.query(User).filter(User.name == name).first() is None:
            db.add(
                User(
                    uuid=str(uuid_mod.uuid4()),
                    name=name,
                    owner=owner,
                    max_logins=1,
                    expiry_date=date.today() + timedelta(days=30),
                    is_active=True,
                    used=0,
                )
            )
            db.commit()
    finally:
        db.close()


def _drop_user(name: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(User).filter(User.name == name).first()
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _restore_owner_state() -> None:
    """Put the shared owner row (and its users) back under the config name."""
    from backend.auth.hash import hash_password

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.is_owner.is_(True)).first()
        if row is None:
            row = crud.get_admin_by_username(db, config.ADMIN_USERNAME)
        if row is None:
            db.add(
                Admin(
                    username=config.ADMIN_USERNAME,
                    password=hash_password(TEST_OWNER_PASSWORD),
                    disabled=False,
                    is_owner=True,
                )
            )
        else:
            if row.username != config.ADMIN_USERNAME:
                db.query(User).filter(User.owner == row.username).update({"owner": config.ADMIN_USERNAME})
                row.username = config.ADMIN_USERNAME
            row.password = hash_password(TEST_OWNER_PASSWORD)
            row.disabled = False
            row.is_owner = True
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _suite_restored():
    yield
    _restore_owner_state()
    owner_claim._FAILURES.clear()


@pytest.fixture
def client():
    _run_migrations()
    return TestClient(api)


@pytest.fixture
def unclaimed_owner():
    """Owner row present, credential blank — claimable for this test."""
    _run_migrations()
    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        assert row is not None, "the suite seeds an owner row"
        row.password = ""
        db.commit()
    finally:
        db.close()


@pytest.fixture
def claim_key_file(tmp_path, monkeypatch):
    from backend import data_paths

    monkeypatch.setattr(data_paths, "DATA_DIR", tmp_path)
    path = tmp_path / owner_claim.CLAIM_KEY_FILE
    path.write_text(f"{CLAIM_KEY}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


# ── 1. certificate required on add ────────────────────────────────────────


def test_add_node_without_a_certificate_is_422():
    client = TestClient(api)
    _run_migrations()
    payload = {
        "name": "partf-nocert",
        "address": "10.9.9.9",
        "port": 2083,
        "key": "long-lived-api-key",
        "protocol": "tcp",
        "ovpn_port": 1194,
    }
    for cert in (None, "   "):
        body = dict(payload)
        if cert is not None:
            body["cert"] = cert
        resp = client.post("/api/nodes/", json=body, headers=_owner_headers())
        assert resp.status_code == 422, resp.text

    db = SessionLocal()
    try:
        assert crud.get_node_by_name(db, "partf-nocert") is None, "a rejected add must not persist anything"
    finally:
        db.close()


# ── 2. TOFU is gone ───────────────────────────────────────────────────────


class _PlainRow:
    def __init__(self, node_id=4242, server_ca=None):
        self.id = node_id
        self.server_ca = server_ca


async def test_add_node_never_fetches_a_certificate(monkeypatch):
    """No trust-on-first-use: the pasted PEM is the only pin source."""
    import backend.node.management as ops

    assert not hasattr(ops, "_resolve_pinned_ca"), "the TOFU fetch helper must be gone"
    assert not hasattr(ops, "_pin_node_certificate"), "the TOFU fetch helper must be gone"

    def boom(*_args, **_kw):
        raise AssertionError("add must not fetch the node certificate")

    monkeypatch.setattr("backend.node.pki.fetch_server_cert", boom)
    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    seen: dict = {}

    class FakeNR:
        def __init__(self, **kw):
            seen.update(kw)

        def check_node(self):
            return True

        def update_config(self, **kw):
            return True

    monkeypatch.setattr(ops, "NodeRequests", FakeNR)
    row = _PlainRow()
    monkeypatch.setattr(ops.crud, "create_node", lambda db, request, geo: row)

    db = SessionLocal()
    try:
        result = await ops.add_node_handler(_payload(cert=CERT_PEM), db)
    finally:
        db.close()

    assert result == (True, "Node added successfully")
    assert seen.get("server_ca") == CERT_PEM, "the client must verify against the pasted PEM"
    assert row.server_ca == CERT_PEM, "the pin must be stored on the node row"


# ── 3. panel identity ─────────────────────────────────────────────────────


def test_panel_id_is_generated_and_exposed():
    _run_migrations()
    db = SessionLocal()
    try:
        pid = panel_id_for(db)
    finally:
        db.close()
    assert pid, "settings.panel_id must be generated"
    assert str(uuid_mod.UUID(pid)) == pid, "panel_id is a UUID string"

    resp = TestClient(api).get("/api/server/settings", headers=_owner_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["panel_id"] == pid


def test_panel_id_header_is_sent_when_available_and_omitted_when_not(monkeypatch):
    import backend.node.requests as nr_mod

    captured: dict = {}

    class _Resp:
        status_code = 200
        headers: dict = {}

        @staticmethod
        def json():
            return {"success": True, "data": {}}

    def fake_get(url, **kw):
        captured.update(kw.get("headers") or {})
        return _Resp()

    monkeypatch.setattr(nr_mod._req, "get", fake_get)

    nr = NodeRequests(address="10.9.9.9", port=2083, api_key="k" * 16, panel_id="pid-1")
    assert nr.check_node() is True
    assert captured["X-Panel-ID"] == "pid-1"
    assert captured["key"] == "k" * 16

    captured.clear()
    plain = NodeRequests(address="10.9.9.9", port=2083, api_key="k" * 16)
    assert plain.check_node() is True
    assert "X-Panel-ID" not in captured, "no settings row → no header (first-install path)"

    assert panel_id_for(None) is None
    assert panel_id_for(object()) is None


def test_node_client_stamps_the_header_on_the_cached_client():
    from types import SimpleNamespace

    from backend.node import connection

    connection._reset_for_tests()
    node = SimpleNamespace(id=990001, address="10.9.9.8", port=2083, key="k" * 16, server_ca=None)
    try:
        first = node_client(node, panel_id="pid-cached")
        assert first.headers["X-Panel-ID"] == "pid-cached"
        second = node_client(node)
        assert second is first, "the header must ride the connection-cached client"
        assert second.headers["X-Panel-ID"] == "pid-cached"
    finally:
        connection.forget(990001)
        connection._reset_for_tests()


# ── 4. node 409 surfaces the node's own message ───────────────────────────


def test_node_409_surfaces_the_nodes_message_without_retry(monkeypatch):
    import backend.node.requests as nr_mod

    calls = {"n": 0}

    class _Resp:
        status_code = 409
        headers: dict = {}

        @staticmethod
        def json():
            return {"detail": "Node is paired with another panel. Wait for the 30-minute lease."}

    def fake_get(url, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(nr_mod._req, "get", fake_get)

    nr = NodeRequests(address="10.9.9.7", port=2083, api_key="k" * 16)
    assert nr.check_node() is False
    assert nr.conflict_msg.startswith("Node is paired with another panel")
    assert calls["n"] == 1, "a 409 must not be retried"

    envelope = nr._request("get", "/sync/config", require_success=False)
    assert envelope["success"] is False
    assert envelope["conflict"] is True
    assert envelope["msg"] == nr.conflict_msg


# ── 5. admin rename: cascade, revoke, conflict ────────────────────────────


def test_admin_rename_cascades_users_and_revokes_sessions():
    from conftest import cleanup_admin, create_admin

    old, new = "partf_admin_a", "partf_admin_renamed"
    cleanup_admin(old)
    cleanup_admin(new)
    create_admin(old)
    _make_user("partf_admin_a_user", old)
    token = _token(old, "admin")
    try:
        resp = TestClient(api).put(
            "/api/admin/",
            json={"current_username": old, "username": new},
            headers=_owner_headers(),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["username"] == new

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.name == "partf_admin_a_user").first()
            assert user.owner == new, "the rename must cascade to users.owner"
            sessions = db.query(AuthSession).filter(AuthSession.username == old).count()
            assert sessions == 0, "the renamed admin's sessions must be revoked"
        finally:
            db.close()

        # The old token dies with the row it names.
        resp = TestClient(api).get("/api/admin/me/defaults", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
    finally:
        _drop_user("partf_admin_a_user")
        cleanup_admin(old)
        cleanup_admin(new)


def test_admin_rename_conflict_is_409():
    from conftest import cleanup_admin, create_admin

    a, b = "partf_admin_c", "partf_admin_d"
    cleanup_admin(a)
    cleanup_admin(b)
    create_admin(a)
    create_admin(b)
    try:
        resp = TestClient(api).put(
            "/api/admin/",
            json={"current_username": a, "username": b},
            headers=_owner_headers(),
        )
        assert resp.status_code == 409, resp.text
        assert "already exists" in resp.json()["detail"]

        db = SessionLocal()
        try:
            assert crud.get_admin_by_username(db, a) is not None, "a refused rename must change nothing"
        finally:
            db.close()
    finally:
        cleanup_admin(a)
        cleanup_admin(b)


def test_owner_can_rename_themselves_and_stays_owner():
    _run_migrations()
    _make_user("partf_owner_user", config.ADMIN_USERNAME)
    client = TestClient(api)
    try:
        resp = client.put(
            "/api/admin/",
            json={"current_username": config.ADMIN_USERNAME, "username": RENAMED_OWNER},
            headers=_owner_headers(),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["username"] == RENAMED_OWNER

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.name == "partf_owner_user").first()
            assert user.owner == RENAMED_OWNER, "the owner rename must cascade to users.owner"
        finally:
            db.close()

        # The renamed owner logs in and still gets the owner role.
        login = client.post(
            "/api/login",
            headers=CSRF,
            data={"username": RENAMED_OWNER, "password": TEST_OWNER_PASSWORD},
        )
        assert login.status_code == 200, login.text
        body = login.json()
        assert body["role"] == "owner"
        assert body["username"] == RENAMED_OWNER

        settings = client.get(
            "/api/server/settings",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert settings.status_code == 200, settings.text
        assert settings.json()["data"]["panel_id"]
    finally:
        _drop_user("partf_owner_user")


# ── 6. claim with a username + verify endpoint ────────────────────────────


def _claim(client, **fields):
    payload = {"claim_key": CLAIM_KEY, "password": "a-strong-password-123", **fields}
    return client.post("/api/owner-claim", json=payload, headers=CSRF)


def test_claim_with_a_username_renames_the_owner(client, claim_key_file, unclaimed_owner):
    _make_user("partf_claim_user", config.ADMIN_USERNAME)
    try:
        r = _claim(client, username=CLAIMED_OWNER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == CLAIMED_OWNER
        assert body["role"] == "owner"
        assert not claim_key_file.exists(), "the key must be spent"

        db = SessionLocal()
        try:
            row = crud.get_admin_by_username(db, CLAIMED_OWNER)
            assert row is not None and row.is_owner, "the claimed row is the owner"
            from backend.auth.hash import verify_password

            assert verify_password("a-strong-password-123", row.password)
            assert crud.get_admin_by_username(db, config.ADMIN_USERNAME) is None, "the fixed name was renamed away"
            user = db.query(User).filter(User.name == "partf_claim_user").first()
            assert user.owner == CLAIMED_OWNER, "the claim rename must cascade to users.owner"
        finally:
            db.close()
    finally:
        _drop_user("partf_claim_user")


def test_claim_verify_answers_valid_without_spending_the_key(client, claim_key_file, unclaimed_owner):
    r = client.post("/api/owner-claim/verify", json={"claim_key": CLAIM_KEY}, headers=CSRF)
    assert r.status_code == 200, r.text
    assert r.json() == {"valid": True}
    assert claim_key_file.exists(), "verify must consume nothing"
    assert client.get("/api/owner-claim").json()["claimable"] is True

    wrong = {"claim_key": "f" * 32}
    first_round = [client.post("/api/owner-claim/verify", json=wrong, headers=CSRF) for _ in range(owner_claim._MAX_FAILURES)]
    assert all(r.status_code == 200 and r.json() == {"valid": False} for r in first_round)

    # Verify shares the claim's rate limit, so the next attempt is throttled.
    limited = client.post("/api/owner-claim/verify", json=wrong, headers=CSRF)
    assert limited.status_code == 429


# ── 7. ported pin coverage (the pasted PEM is the pin) ─────────────────────


async def test_add_node_passes_the_certificate_to_the_keyed_client(monkeypatch):
    import backend.node.management as ops

    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    client_pins: list = []

    class FakeNR:
        def __init__(self, **kw):
            client_pins.append(kw.get("server_ca"))

        def check_node(self):
            return True

        def update_config(self, **kw):
            return True

    monkeypatch.setattr(ops, "NodeRequests", FakeNR)
    row = _PlainRow()
    monkeypatch.setattr(ops.crud, "create_node", lambda db, request, geo: row)

    db = SessionLocal()
    try:
        ok, _msg = await ops.add_node_handler(_payload(cert=CERT_PEM), db)
    finally:
        db.close()

    assert ok is True
    assert row.server_ca == CERT_PEM
    assert client_pins and all(pin == CERT_PEM for pin in client_pins)


async def test_update_without_a_certificate_keeps_the_stored_pin(monkeypatch):
    """Blank-means-keep on update: no fetch, no downgrade."""
    import backend.node.management as ops

    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    seen: list = []

    class FakeNR:
        def __init__(self, **kw):
            seen.append(kw.get("server_ca"))

        def check_node(self):
            return True

        def update_config(self, **kw):
            return True

    monkeypatch.setattr(ops, "NodeRequests", FakeNR)
    monkeypatch.setattr(ops.crud, "get_node_by_id", lambda db, node_id: _PlainRow(77, OLD_PIN))
    monkeypatch.setattr(ops.crud, "update_node", lambda db, node_id, request, geo: True)

    db = SessionLocal()
    try:
        ok, _msg = await ops.update_node_handler(77, _payload(), db)
    finally:
        db.close()

    assert ok is True
    assert seen == [OLD_PIN], "the previous pin must still guard the keyed request"


def test_cert_validator_requires_pem_markers():
    with pytest.raises(ValidationError):
        _payload(cert="not a certificate")
    assert _payload(cert="   ").cert is None


async def test_real_client_accepts_the_pem_before_the_row_exists(monkeypatch):
    """The constructor must take a PEM pin with no node id to name a file after.

    ``add_node_handler`` builds the keyed client before ``crud.create_node``,
    so there is no row yet — only the real constructor exercises that path.
    """
    import backend.node.management as ops

    created: list = []

    monkeypatch.setattr("backend.node.requests.NodeRequests.check_node", lambda self, **kw: True)
    monkeypatch.setattr("backend.node.requests.NodeRequests.update_config", lambda self, **kw: True)
    monkeypatch.setattr(ops, "geolocate", lambda address: {})
    monkeypatch.setattr(ops.crud, "create_node", lambda db, req, geo: created.append(1) or _PlainRow())

    db = SessionLocal()
    try:
        result = await ops.add_node_handler(_payload(cert=CERT_PEM), db)
    finally:
        db.close()

    assert created, "the handler must get past building the keyed client"
    assert result[0] is True
