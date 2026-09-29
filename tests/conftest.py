"""Shared pytest fixtures."""

import anyio.abc
import anyio.from_thread

if "BlockingPortal" not in anyio.abc.__dict__:
    anyio.abc.BlockingPortal = anyio.from_thread.BlockingPortal  # type: ignore[attr-defined]

import os
import shutil
import tempfile

import pytest

# Point the panel at a throwaway data dir BEFORE anything imports
# backend.data_paths (it resolves DATA_DIR at import time). Without this the
# suite writes into the developer's real panel database: test nodes and users
# survive between runs and end up in /opt/ovmanager's or ./data/ovmanager.db,
# where every unreachable leftover node makes a list request pay the full
# node timeout — a single API test took 90s against 119 leftover nodes.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="ovmanager-tests-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR

# cli/ commands fall back to /opt/ovmanager when no --install-dir is given, so
# a test that forgets the override rewrites a live panel's .env — which is how
# an ADMIN_PASSWORD_HASH=HASHED fixture value once crash-looped a real install
# for 90 minutes. Point the fallback at the throwaway tree as well.
os.environ["OVM_APP_DIR"] = _TEST_DATA_DIR

# Do not spawn the jobs worker. The app lifespan starts a real second
# interpreter, and a unit test that exercises the lifespan should not fork
# one per test; the worker's own behaviour is covered in test_worker_process.py,
# which re-enables this deliberately.
os.environ["OVM_WORKER"] = "0"

os.environ.setdefault("ADMIN_USERNAME", "admin")

# The owner credential lives in the database (v16+), so tests need a real
# admin row rather than an env password. Seeded after the schema exists.
TEST_OWNER_PASSWORD = "test-owner-password-123"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir():
    yield
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


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
    import backend.urlpath._core as urlpath_mod

    global _real_get_urlpath, _real_cache_value, _real_cache_ts
    if _real_get_urlpath is None:
        _real_get_urlpath = urlpath_mod.get_urlpath
        _real_cache_value = urlpath_mod._cache_value
        _real_cache_ts = urlpath_mod._cache_ts

    def _test_get_urlpath() -> str:
        with urlpath_mod._lock:
            if urlpath_mod._cache_ts != _real_cache_ts and urlpath_mod._cache_value:
                return urlpath_mod._cache_value
        return ""

    urlpath_mod.get_urlpath = _test_get_urlpath  # type: ignore[assignment]
    urlpath_mod._cache_value = ""
    urlpath_mod._cache_ts = 0.0


@pytest.fixture(autouse=True)
def _reset_urlpath_cache_after_each_test():
    """After each test, restore the URLPATH cache so the session-wide fixture
    continues to short-circuit get_urlpath() to '' by default. Tests that
    call set_urlpath() set _cache_value directly; this fixture clears the
    'explicit' marker back to base state so the next test isn't poisoned."""
    yield
    import backend.urlpath._core as urlpath_mod

    with urlpath_mod._lock:
        urlpath_mod._cache_value = ""
        urlpath_mod._cache_ts = 0.0


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema(_disable_urlpath_for_tests):  # pylint: disable=redefined-outer-name
    """Bring the schema to HEAD (users/admins/settings/nodes/sessions + audit) once per session.

    Also gives the owner a real credential: authentication reads the `admins`
    table since v16, so a suite without this row could not log in as owner.

    The password is set unconditionally. The fresh-install migration path now
    imports ADMIN_PASSWORD_HASH from .env when one is present — correct for a
    real install, but it meant a developer's local .env decided what the test
    owner's password was, and every login test failed for reasons that had
    nothing to do with the code under test.
    """
    from backend.auth.hash import hash_password
    from backend.config import config
    from backend.db.engine import SessionLocal
    from backend.db.migrations import migrate
    from backend.db.models import Admin

    migrate()

    db = SessionLocal()
    try:
        owner = (config.ADMIN_USERNAME or "admin").strip()
        row = db.query(Admin).filter(Admin.username == owner).first()
        if row is None:
            db.add(Admin(username=owner, password=hash_password(TEST_OWNER_PASSWORD), disabled=False))
        else:
            row.password = hash_password(TEST_OWNER_PASSWORD)
            row.disabled = False
        db.commit()
    finally:
        db.close()


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


@pytest.fixture
def hold_worker_lock():
    """Factory: hold the worker lock on a data dir, as a live worker would.

    doctor's Worker check reports on that lock, so a test asserting a fully
    healthy install has to have one held — otherwise the panel looks fine
    while the periodic jobs are not running, which is the case the check
    exists to catch.

    A plain call rather than a context manager: an entered-but-unreferenced
    generator context manager is collected, its finally closes the handle, and
    the flock is released again — which made the check report "stale" while the
    test believed it was holding it.
    """
    import fcntl
    from pathlib import Path

    held: list = []

    def _hold(data_dir) -> None:
        lock = Path(data_dir) / "scheduler.lock"
        handle = lock.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write("4242\n")
        handle.flush()
        held.append(handle)

    yield _hold
    for handle in held:
        try:
            handle.close()
        except OSError:  # pragma: no cover
            pass
