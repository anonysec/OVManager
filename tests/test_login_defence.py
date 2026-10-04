# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Two defences on /api/login, grouped because they guard the same endpoint.

**Rate limiting** — 5 bad attempts lock a username out, with per-username
isolation, expiry, and a bucket cleared by a success. The limiter is
intentionally in-memory only (see backend/auth/auth.py), so tests reset the
process-global buckets directly instead of touching the DB.

**Timing** — a failed login must cost the same whether or not the account
exists. bcrypt is deliberately slow: if the unknown-username path returned
before calling it, a 401 would come back in microseconds for a name that does
not exist and in ~100ms for one that does, making the endpoint a username
oracle. The fix is to verify against a hash nobody can supply, so every
failure pays the same price. The assertion is on the mechanism (was a verify
attempted?) rather than wall-clock time, which would flake on a shared box.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth import auth as auth_mod
from backend.auth.hash import hash_password
from backend.config import config


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


@pytest.fixture(autouse=True)
def _clean_buckets():
    import backend.auth.auth as auth

    auth._login_attempts.clear()
    auth._last_cleanup = 0.0
    yield
    auth._login_attempts.clear()
    auth._last_cleanup = 0.0


@pytest.fixture
def db_session():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def spy_verify(monkeypatch):
    """Count verify_password calls without changing its behaviour."""
    calls: list[str] = []
    real = auth_mod.verify_password

    def wrapper(password, hashed):
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(auth_mod, "verify_password", wrapper)
    return calls


def _try_login(client: TestClient, username: str, password: str = "wrong-password-123") -> int:
    r = client.post("/api/login", data={"username": username, "password": password})
    return r.status_code


# ── rate limiting ───────────────────────────────────────────────────────


def test_five_strikes_then_429_with_retry_after():
    _run_migrations()
    with TestClient(api) as client:
        for _ in range(5):
            assert _try_login(client, "lockout_probe") == 401
        r = client.post("/api/login", data={"username": "lockout_probe", "password": "wrong-password-123"})
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "300"


def test_lockout_is_per_username():
    _run_migrations()
    with TestClient(api) as client:
        for _ in range(5):
            _try_login(client, "lockout_iso_a")
        assert _try_login(client, "lockout_iso_a") == 429
        assert _try_login(client, "lockout_iso_b") == 401


def test_expired_attempts_stop_counting():
    import backend.auth.auth as auth

    _run_migrations()
    with TestClient(api) as client:
        for _ in range(5):
            _try_login(client, "lockout_exp")
        assert _try_login(client, "lockout_exp") == 429
        old = time.time() - auth._LOCKOUT_SECONDS - 1
        for k in list(auth._login_attempts):
            auth._login_attempts[k] = [old]
        assert _try_login(client, "lockout_exp") == 401


def test_successful_login_clears_bucket():
    # Must match the owner credential seeded by the session schema fixture.
    # Imported lazily from the module object, not `tests.conftest`: importing
    # the latter as a package re-executes its module-level bootstrap and
    # repoints DATA_DIR, which breaks later tests that spawn a subprocess.
    import conftest

    _run_migrations()
    with TestClient(api) as client:
        for _ in range(4):
            _try_login(client, config.ADMIN_USERNAME)
        r = client.post(
            "/api/login",
            data={"username": config.ADMIN_USERNAME, "password": conftest.TEST_OWNER_PASSWORD},
        )
        assert r.status_code == 200
        assert _try_login(client, config.ADMIN_USERNAME) == 401


# ── timing ──────────────────────────────────────────────────────────────


def test_unknown_username_still_pays_for_a_verify(db_session, spy_verify):
    assert auth_mod.authenticate_user(db_session, "no-such-user-at-all", "whatever") is None
    assert spy_verify, "an unknown username returned without attempting a verify — timing oracle"


def test_disabled_admin_still_pays_for_a_verify(db_session, spy_verify):
    from backend.db.models import Admin

    db_session.add(Admin(username="timing-disabled", password=hash_password("a-real-password-1"), disabled=True))
    db_session.commit()
    try:
        assert auth_mod.authenticate_user(db_session, "timing-disabled", "a-real-password-1") is None
        assert spy_verify, "a disabled admin returned without attempting a verify"
    finally:
        db_session.query(Admin).filter(Admin.username == "timing-disabled").delete()
        db_session.commit()


def test_admin_with_no_password_still_pays_for_a_verify(db_session, spy_verify):
    from backend.db.models import Admin

    db_session.add(Admin(username="timing-nopass", password="", disabled=False))
    db_session.commit()
    try:
        assert auth_mod.authenticate_user(db_session, "timing-nopass", "anything") is None
        assert spy_verify, "an admin with no stored credential returned without a verify"
    finally:
        db_session.query(Admin).filter(Admin.username == "timing-nopass").delete()
        db_session.commit()


def test_the_dummy_hash_is_a_real_bcrypt_hash():
    """A malformed placeholder would raise instead of costing time."""
    assert auth_mod._DUMMY_HASH.startswith("$2")
    # It must not accidentally be a usable credential for any input.
    assert not auth_mod.verify_password("", auth_mod._DUMMY_HASH)


def test_a_correct_login_still_succeeds(db_session):
    """The oracle fix must not break the happy path."""
    import conftest

    ok = auth_mod.authenticate_user(db_session, config.ADMIN_USERNAME, conftest.TEST_OWNER_PASSWORD)
    assert ok and ok["type"] == "owner"


def test_rotating_source_address_cannot_beat_the_per_username_bucket():
    """Both address-keyed buckets reset when the address changes.

    An attacker with a proxy pool gets a fresh 5-attempt (IP, user) bucket AND
    a fresh 20-attempt per-IP bucket for every request, so neither one bounds a
    distributed attempt against a known account. The per-username bucket has no
    address in its key and does.
    """
    from backend.auth import auth

    assert "_ip_hash" not in auth._user_key("admin"), "the per-user bucket must not key on the address"
    # distinct addresses, same account -> one shared bucket
    assert auth._rate_key("1.2.3.4", "admin") != auth._rate_key("5.6.7.8", "admin")
    assert auth._user_key("admin") == auth._user_key("ADMIN"), "case-insensitive, like the other keys"
    assert auth._user_key("admin") != auth._user_key("bob")
