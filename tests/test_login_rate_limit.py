# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Login rate limiting: 5 bad attempts lock out, isolation, expiry, reset.

The limiter is intentionally in-memory only (see backend/auth/auth.py), so
tests reset the process-global buckets directly instead of touching the DB.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api


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


def _try_login(client: TestClient, username: str, password: str = "wrong-password-123") -> int:
    r = client.post("/api/login", data={"username": username, "password": password})
    return r.status_code


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
        # Same IP, different user: unaffected.
        assert _try_login(client, "lockout_iso_b") == 401


def test_expired_attempts_stop_counting():
    import backend.auth.auth as auth

    _run_migrations()
    with TestClient(api) as client:
        for _ in range(5):
            _try_login(client, "lockout_exp")
        assert _try_login(client, "lockout_exp") == 429
        # Backdate the bucket past the window: attempts no longer count.
        old = time.time() - auth._LOCKOUT_SECONDS - 1
        for k in list(auth._login_attempts):
            auth._login_attempts[k] = [old]
        assert _try_login(client, "lockout_exp") == 401


def test_successful_login_clears_bucket():
    from backend.config import config

    _run_migrations()
    with TestClient(api) as client:
        for _ in range(4):
            _try_login(client, config.ADMIN_USERNAME)
        r = client.post(
            "/api/login",
            data={"username": config.ADMIN_USERNAME, "password": config.ADMIN_PASSWORD},
        )
        assert r.status_code == 200
        # Counter restarted: next failure is strike one, not a lockout.
        assert _try_login(client, config.ADMIN_USERNAME) == 401
