# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Shared pytest fixtures."""

# anyio 4.15 moved BlockingPortal to anyio.from_thread and emits a
# DeprecationWarning on the old anyio.abc alias — which starlette's
# TestClient still reads at import (annotations evaluated eagerly). Both
# packages are at latest; pre-binding the new location keeps the suite
# warning-free (filterwarnings = error) until starlette catches up.
import anyio.abc
import anyio.from_thread

if "BlockingPortal" not in anyio.abc.__dict__:
    anyio.abc.BlockingPortal = anyio.from_thread.BlockingPortal  # type: ignore[attr-defined]

import pytest

# This dict holds the pre-test reference to the real get_urlpath() so the
# autouse fixture below can restore it for tests that actually exercise
# the URLPathMiddleware (test_urlpath_hardening, test_app::test_urlpath_*).
# Without this, our short-circuit closure would shadow the real function and
# break tests that intentionally call set_urlpath() and then expect the
# middleware to read the new value.
_real_get_urlpath = None
_real_cache_value = None
_real_cache_ts = None


@pytest.fixture(scope="session", autouse=True)
def _disable_urlpath_for_tests():
    """Tests that hit the API at root (/api/...) but the on-disk .env has
    URLPATH=dashboard (production) collide with the URLPathMiddleware: any
    non-matching path returns an empty 200, which then JSONDecodeErrors
    inside resp.json(). This fixture monkey-patches get_urlpath to return
    '' for the test session, but the tests that *intentionally* exercise
    URLPathMiddleware behaviour (test_urlpath_hardening, test_urlpath_middleware_*
    in test_app.py) call set_urlpath() first, so they expect the real
    middleware to read that value.

    Solution: we patch only the *first call* (before any explicit set_urlpath
    runs). Tests that call set_urlpath re-cache directly, so they bypass our
    short-circuit."""
    import backend.urlpath as urlpath_mod

    global _real_get_urlpath, _real_cache_value, _real_cache_ts
    if _real_get_urlpath is None:
        _real_get_urlpath = urlpath_mod.get_urlpath
        _real_cache_value = urlpath_mod._cache_value
        _real_cache_ts = urlpath_mod._cache_ts

    def _test_get_urlpath() -> str:
        # If a test has explicitly cached a value (via set_urlpath), respect
        # that — those tests are exercising the middleware, not fighting it.
        with urlpath_mod._lock:
            if urlpath_mod._cache_ts != _real_cache_ts and urlpath_mod._cache_value:
                return urlpath_mod._cache_value
        # Default: pretend URLPATH is empty so the test client works.
        return ""

    urlpath_mod.get_urlpath = _test_get_urlpath  # type: ignore[assignment]
    # Reset the cache so _test_get_urlpath's "explicit" branch never fires
    # before the first set_urlpath call. Tests that call set_urlpath update
    # _cache_value/_cache_ts directly, which the helper above detects.
    urlpath_mod._cache_value = ""
    urlpath_mod._cache_ts = 0.0


@pytest.fixture(autouse=True)
def _reset_urlpath_cache_after_each_test():
    """After each test, restore the URLPATH cache so the session-wide fixture
    continues to short-circuit get_urlpath() to '' by default. Tests that
    call set_urlpath() set _cache_value directly; this fixture clears the
    'explicit' marker back to base state so the next test isn't poisoned."""
    yield
    import backend.urlpath as urlpath_mod

    with urlpath_mod._lock:
        urlpath_mod._cache_value = ""
        urlpath_mod._cache_ts = 0.0


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema(_disable_urlpath_for_tests):  # pylint: disable=redefined-outer-name
    """Bring the schema to HEAD (users/admins/settings/nodes/sessions + audit) once per session."""
    from backend.db.migrations import migrate

    migrate()


@pytest.fixture(scope="session")
def make_session_token():
    """Factory: mint a real opaque session token for tests.

    Auth is DB-backed, so a valid Bearer token requires a real session row —
    there is no offline-signed shortcut anymore (by design).
    """

    def _make(username: str, role: str) -> str:
        from backend.auth.sessions import create_session
        from backend.db.engine import SessionLocal

        db = SessionLocal()
        try:
            return create_session(db, username, role, user_agent="pytest", ip="127.0.0.1")
        finally:
            db.close()

    return _make
