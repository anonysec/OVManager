"""Shared pytest fixtures."""

import hashlib
import subprocess
from pathlib import Path

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

    Solution: only the *first call* is patched (before any explicit set_urlpath
    runs). Tests that call set_urlpath re-cache directly, so they bypass this
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
            db.add(Admin(username=owner, password=hash_password(TEST_OWNER_PASSWORD), disabled=False, is_owner=True))
        else:
            row.password = hash_password(TEST_OWNER_PASSWORD)
            row.disabled = False
            row.is_owner = True
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


# ── Shared test helpers ──────────────────────────────────────────────────
#
# Helpers that were byte-identical in more than one test file, hoisted here so
# the copies cannot drift. Only bodies verified identical in every file that
# defined them belong in this block: several same-named helpers across the suite
# differ meaningfully (some call `_run_migrations()`, some add an
# `X-Requested-With` header, some restore a previous value where others
# reset), and a merged file would silently adopt one file's behaviour for all
# of them. Those stayed where they are.
#
# `_ensure_schema` is deliberately absent. It is byte-identical in three files,
# but conftest already defines a session-scoped `_ensure_schema` fixture, and
# these three call it as a plain function — hoisting would shadow the fixture.


def create_admin(username: str) -> None:
    """Create a throwaway admin row, if one is not already there."""
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def cleanup_admin(username: str) -> None:
    """Remove an admin row and every session belonging to it."""
    from backend.auth.sessions import revoke_user_sessions
    from backend.db import crud
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        revoke_user_sessions(db, username)
        admin = crud.get_admin_by_username(db, username)
        if admin is not None:
            crud.delete_admin(db, admin)
    finally:
        db.close()


def delete_node(node) -> None:
    """Delete a node row by ORM instance, for a test's own cleanup."""
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        db.delete(db.merge(node))
        db.commit()
    finally:
        db.close()


def probe_value(path) -> str:
    """Read the single `value` column out of a throwaway SQLite probe db."""
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM probe").fetchone()[0]
    finally:
        conn.close()


def bot_all_texts(update) -> list:
    """Every string the handler replied with, across the message and the edit."""
    out = [text for text, _ in update.effective_message.sent if isinstance(text, str)]
    if update.callback_query:
        out += [text for text, _ in update.callback_query.edited]
    return out


def bot_all_markups(update) -> list:
    """Every reply_markup the handler sent or edited."""
    out = [kw.get("reply_markup") for _, kw in update.effective_message.sent]
    if update.callback_query:
        out += [kw.get("reply_markup") for _, kw in update.callback_query.edited]
    return [m for m in out if m is not None]


def bot_callbacks(markup) -> list:
    """The callback_data values carried by an inline keyboard."""
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def bot_make_actor(role: str = "owner"):
    """A telegram Actor double for handler tests."""
    from backend.bot.identity import Actor

    return Actor(telegram_id=7, username="boss", role=role, token="tok-1")


def bot_make_context(**extra):
    """A telegram Context double carrying only user_data."""
    from types import SimpleNamespace

    return SimpleNamespace(user_data={"lang": "en", **extra})


# ── The suite must not touch the running install ──────────────────────────
#
# The node has had a guard like this since its self-signed sweep wrote over the
# panel's certificate on a shared host. The panel had none, and within a day
# test_cli_shape.py's dispatch sweep was disabling autostart on the live panel
# every time the suite ran — four of the thirteen verbs it exercises act on the
# service, and with the root gate neutered for the test they reached the real
# systemctl.
#
# Nothing failed. A 907-test suite went green while reconfiguring production,
# which is the worst version of that bug: it looks like the tests are working.
# The per-test assertion in test_cli_shape.py catches the one verb set that
# caused it; this catches everything else, including whatever is written next.
#
# Only paths nothing legitimate touches are listed. /var/lib/ovmanager and
# /var/backups were in the first version of this and made it fail on its first
# run — the running panel rewrites its own database, WAL and log continuously,
# and its backup timer writes the other. A guard that fires on normal operation
# is a guard that gets deleted.
_LIVE_STATE_UNTOUCHED = (
    "/etc/ssl/self-signed",
    "/etc/systemd/system/ovmanager.service",
)


def _live_state() -> dict:
    """Name, size and mtime under each path, plus the service's enable state.

    Size and mtime rather than a content hash: a byte-for-byte hash of a live
    path twice per session is slow, and it flakes on anything else on the host
    touching the same files. What matters is whether the *suite* created,
    truncated or removed something — and whether it left the unit disabled.
    """
    out: dict = {}
    for raw in _LIVE_STATE_UNTOUCHED:
        path = Path(raw)
        try:
            if not path.exists():
                out[raw] = None
                continue
            digest = hashlib.sha256()
            for item in sorted(path.rglob("*")):
                try:
                    stat = item.stat()
                    digest.update(f"{item}:{stat.st_size}:{stat.st_mtime_ns}".encode())
                except OSError:
                    # Vanished or unreadable between walk and stat. Raising here
                    # would fail the suite for something it cannot attribute.
                    digest.update(f"{item}:unreadable".encode())
            out[raw] = digest.hexdigest()
        except OSError as exc:
            out[raw] = f"unreadable: {exc}"
    out["<ovmanager-enabled>"] = subprocess.run(
        ["systemctl", "is-enabled", "ovmanager"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out


@pytest.fixture(scope="session", autouse=True)
def _live_install_untouched():
    before = _live_state()
    yield
    after = _live_state()
    changed = [k for k in before if before[k] != after[k]]
    assert not changed, (
        f"the test suite changed the live install: {changed}. A test is acting "
        "outside its sandbox — stub the command, or skip the verb."
    )
