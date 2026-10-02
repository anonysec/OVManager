"""First-run owner claim: the claim key plus a chosen password makes the owner.

The installer mints a key, not a credential, so these tests cover the whole
path: the key becomes an ``admins`` row with a bcrypt hash, is spent on first
use, and cannot be replayed once the panel has an owner. The suite's shared
database already has a claimed owner, so each test unclaims it and puts the
real credential back afterwards.
"""

import pytest
from fastapi.testclient import TestClient

from backend import data_paths
from backend.app import _run_migrations, api
from backend.config import config
from backend.routers import owner_claim

CLAIM_KEY = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh failure counters, and a real owner afterwards.

    The claimed-owner row is shared by the whole suite (tests/conftest.py sets
    its password once per session), so a test that unclaims it has to put that
    back or every later login test fails.
    """
    owner_claim._FAILURES.clear()
    yield
    from backend.auth.hash import hash_password
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        if row is None:
            db.add(Admin(username=config.ADMIN_USERNAME, password=hash_password("test-owner-password-123"), disabled=False))
        else:
            row.password = hash_password("test-owner-password-123")
            row.disabled = False
        db.commit()
    finally:
        db.close()
    owner_claim._FAILURES.clear()


@pytest.fixture
def client():
    _run_migrations()
    return TestClient(api)


@pytest.fixture
def claim_key_file(tmp_path, monkeypatch):
    """A key file where the installer would put one, plus the data dir it is in."""
    monkeypatch.setattr(data_paths, "DATA_DIR", tmp_path)
    path = tmp_path / owner_claim.CLAIM_KEY_FILE
    path.write_text(f"{CLAIM_KEY}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def unclaimed_owner():
    """Put the owner row back to "no credential" for the duration of a test."""
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        assert row is not None, "the suite seeds an owner row"
        row.password = ""
        db.commit()
    finally:
        db.close()
    yield


def _post(client, key=CLAIM_KEY, password="a-strong-password-123"):
    # The CSRF middleware requires the header the frontend's api client sends;
    # the claim path is deliberately not exempt the way /login is.
    return client.post(
        "/api/owner-claim",
        json={"claim_key": key, "password": password},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )


def test_a_claim_creates_the_owner_row_and_spends_the_key(client, claim_key_file, unclaimed_owner):
    """Arrange: an unclaimed panel and a key on disk."""
    r = _post(client, password="chosen-in-the-browser-1")

    # Assert: the response is login-shaped, so the browser goes straight in.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == config.ADMIN_USERNAME
    assert body["role"] == "owner"
    assert body["access_token"]
    assert not claim_key_file.exists(), "the key must be single-use"

    from backend.auth.hash import verify_password
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        assert verify_password("chosen-in-the-browser-1", row.password)
    finally:
        db.close()


def test_the_claim_response_never_echoes_the_key_or_the_password(client, claim_key_file, unclaimed_owner):
    r = _post(client, password="never-echo-this-password")
    assert r.status_code == 200
    assert CLAIM_KEY not in r.text
    assert "never-echo-this-password" not in r.text


def test_a_wrong_key_claims_nothing_and_is_audited(client, claim_key_file, unclaimed_owner):
    r = _post(client, key="f" * 32)

    assert r.status_code == 401
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        assert row.password == ""
    finally:
        db.close()


def test_an_already_claimed_panel_refuses_a_claim(client, claim_key_file):
    """No takeover: the endpoint is dead once the owner exists."""
    r = _post(client)
    assert r.status_code == 409
    assert claim_key_file.exists(), "a refused claim must not spend the key"


def test_a_missing_key_file_says_how_to_mint_one(client, tmp_path, monkeypatch, unclaimed_owner):
    monkeypatch.setattr(data_paths, "DATA_DIR", tmp_path)
    r = _post(client)
    assert r.status_code == 400
    assert "ovm auth key" in r.json()["detail"]


def test_an_unreadable_key_path_is_an_error_not_a_missing_key(client, tmp_path, monkeypatch, unclaimed_owner):
    """The ADR rule: never answer with a default that looks like data."""
    monkeypatch.setattr(data_paths, "DATA_DIR", tmp_path)
    (tmp_path / owner_claim.CLAIM_KEY_FILE).mkdir()
    r = _post(client)
    assert r.status_code == 500
    assert "ovm auth key" in r.json()["detail"]


def test_repeated_failures_are_rate_limited(client, claim_key_file, unclaimed_owner):
    codes = [_post(client, key="f" * 32).status_code for _ in range(owner_claim._MAX_FAILURES + 1)]
    assert codes[-1] == 429
    assert codes[0] == 401


def test_short_passwords_are_rejected(client, claim_key_file, unclaimed_owner):
    r = _post(client, password="short")
    assert r.status_code == 422


def test_status_reports_whether_a_claim_is_possible(client, claim_key_file, unclaimed_owner):
    assert client.get("/api/owner-claim").json() == {"claimable": True}

    key = claim_key_file.read_text(encoding="utf-8").strip()
    assert _post(client, key=key).status_code == 200
    assert client.get("/api/owner-claim").json() == {"claimable": False}


def test_status_is_not_claimable_without_a_key(client, tmp_path, monkeypatch, unclaimed_owner):
    monkeypatch.setattr(data_paths, "DATA_DIR", tmp_path)
    assert client.get("/api/owner-claim").json() == {"claimable": False}


def test_short_passwords_are_not_the_only_rejection(client, claim_key_file, unclaimed_owner):
    """A placeholder is refused here too — .env may not hold a weak owner."""
    r = _post(client, password="change-me-please")
    assert r.status_code == 422
    assert "placeholder" in r.text


def test_the_key_the_installer_mints_is_the_key_the_panel_accepts(tmp_path, monkeypatch, unclaimed_owner):
    """The contract across the language boundary, exercised for real.

    `mint_claim_key` — an inline helper in install.sh — writes the file; this
    endpoint reads it. A typo in either the path or the file name would only
    show up on a live install, which is precisely the failure this catches.
    """
    import subprocess

    from inline_lib import path as lib_path

    data = tmp_path / "data"
    monkeypatch.setattr(data_paths, "DATA_DIR", data)
    harness = "\n".join(f'source "{lib_path(name)}"' for name in ("common.sh", "policy.sh"))
    r = subprocess.run(
        ["bash", "-c", f'{harness}\nDATA_DIR="{data}" MODE=native mint_claim_key'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    minted = r.stdout.strip()

    from fastapi.testclient import TestClient

    from backend.app import _run_migrations, api

    _run_migrations()
    response = TestClient(api).post(
        "/api/owner-claim",
        json={"claim_key": minted, "password": "claimed-from-the-installer"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200, response.text
    assert not (data / owner_claim.CLAIM_KEY_FILE).exists(), "the key must be spent"
