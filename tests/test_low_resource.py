"""perf.low_resource: stretch the cadence, trim the memory — off by default.

One settings_kv flag (`perf.low_resource`, env override `OVMANAGER_LOW_RESOURCE`),
default false. The flag picks slower values, never drops a job: prune, metrics
and debounce all keep running, and `enforce_user_limits` keeps its cadence as an
inline call after the 5-minute traffic poll instead of a second cron.
"""

from contextlib import contextmanager

import pytest

import backend.config as config


@pytest.fixture(autouse=True)
def _clean_bot_supervisor():
    import backend.bot_supervisor as sup

    sup._bot_process = None
    sup._bot_disabled_until = None
    yield
    sup._bot_process = None
    sup._bot_disabled_until = None


def _register():
    """Register the worker jobs the way the worker does, then hand back the scheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from backend.worker import register_worker_jobs

    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    register_worker_jobs(scheduler)
    return scheduler


def _flag_on(monkeypatch) -> None:
    monkeypatch.setattr(config, "low_resource_enabled", lambda: True)


def _flag_off(monkeypatch) -> None:
    """Pin the flag off even when the whole suite runs with it forced on."""
    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)
    monkeypatch.setattr(config, "low_resource_enabled", lambda: False)


@pytest.fixture
def flag_cache():
    """Reload the engine's startup flag cache; restore it after the test.

    The cache is resolved once per process, so a test that wants to see the
    other value reads it the way startup does — then the fixture puts the
    original back so the rest of the worker keeps what it booted with.
    """
    from backend.db import engine as engine_mod

    previous = engine_mod._low_resource
    yield engine_mod.load_low_resource_flag
    engine_mod._low_resource = previous


# ── the schedule ────────────────────────────────────────────────────────────


def test_flag_off_keeps_the_default_schedules(monkeypatch):
    _flag_off(monkeypatch)
    scheduler = _register()
    assert str(scheduler.get_job("collect_metrics").trigger) == "cron[minute='2-59/5']"
    assert str(scheduler.get_job("enforce_user_limits").trigger) == "cron[minute='*/10']"
    assert str(scheduler.get_job("check_user_used_traffic").trigger) == "cron[minute='*/5']"
    assert str(scheduler.get_job("reschedule_auto_backup").trigger) == "cron[minute='*']"
    assert scheduler.get_job("process_restart_debounce").trigger.interval.total_seconds() == 30


def test_flag_on_stretches_the_chatty_jobs(monkeypatch):
    _flag_on(monkeypatch)
    scheduler = _register()

    assert str(scheduler.get_job("collect_metrics").trigger) == "cron[minute='2-59/15']"
    assert str(scheduler.get_job("reschedule_auto_backup").trigger) == "cron[minute='*/15']"
    assert scheduler.get_job("process_restart_debounce").trigger.interval.total_seconds() == 60

    # enforce stops being a cron of its own — it still fires inline after the
    # traffic poll (backend/operations/billing/daily.py:336), so low mode keeps
    # the 5-minute cadence rather than losing enforcement.
    assert scheduler.get_job("enforce_user_limits") is None
    assert str(scheduler.get_job("check_user_used_traffic").trigger) == "cron[minute='*/5']"

    # Slower, never dropped.
    for job_id in (
        "auto_sync_limits_job",
        "auto_clean_stale_job",
        "auto_prune_audit_job",
        "auto_prune_daily_job",
        "auto_daily_alerts_job",
        "reschedule_auto_backup",
    ):
        assert scheduler.get_job(job_id) is not None, f"{job_id} must keep running in low mode"


# ── memory ──────────────────────────────────────────────────────────────────


def test_the_page_cache_is_trimmed_only_when_the_flag_is_on(monkeypatch, flag_cache):
    from backend.db import engine as engine_mod

    # The flag is resolved once at startup (env/KV, through the normal
    # session); every connection then reads the cached value in its hook.
    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)
    flag_cache()
    with engine_mod.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA cache_size").scalar() <= -32768

    monkeypatch.setenv("OVMANAGER_LOW_RESOURCE", "1")
    flag_cache()
    with engine_mod.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA cache_size").scalar() == -8192


def test_the_page_cache_follows_the_kv_flag(monkeypatch, flag_cache):
    from sqlalchemy import text

    from backend.db import crud
    from backend.db import engine as engine_mod

    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)
    db = engine_mod.SessionLocal()
    try:
        crud.set_kv(db, "perf.low_resource", "true")
        db.commit()
        flag_cache()
        with engine_mod.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA cache_size").scalar() == -8192

        crud.set_kv(db, "perf.low_resource", "false")
        db.commit()
        flag_cache()
        with engine_mod.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA cache_size").scalar() <= -32768
    finally:
        db.execute(text("DELETE FROM settings_kv WHERE key = 'perf.low_resource'"))
        db.commit()
        db.close()


def test_the_connect_hook_reads_the_cached_flag_and_nothing_else(monkeypatch, flag_cache):
    """The connect event must not open a reader of its own.

    It runs while the connection is being established: a nested SQLAlchemy
    reader deadlocks against the write migrate() holds, and a bare sqlite3
    handle was the same bet. The flag is resolved once at startup instead,
    and the hook only spends it — so every connection keeps its full pragma
    profile.
    """
    import sqlite3

    from backend.db import engine as engine_mod

    flag_cache()
    expected = -8192 if engine_mod._low_resource else -32768

    def forbidden(*args, **kwargs):
        raise AssertionError("the connect hook must not open a connection or re-read the flag")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(config, "low_resource_enabled", forbidden)

    with engine_mod.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA cache_size").scalar() == expected
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# ── live poll cadence ───────────────────────────────────────────────────────


def test_the_live_poll_slows_down_only_when_the_flag_is_on(monkeypatch):
    from backend.operations.observability import live

    monkeypatch.delenv("OVMANAGER_LIVE_POLL_SECONDS", raising=False)
    _flag_off(monkeypatch)
    assert live.poll_seconds() == 10

    _flag_on(monkeypatch)
    assert live.poll_seconds() == 30

    # An explicit .env value wins over the flag — the operator asked for it.
    monkeypatch.setenv("OVMANAGER_LIVE_POLL_SECONDS", "7")
    assert live.poll_seconds() == 7


# ── the telegram bot ────────────────────────────────────────────────────────


class _FakeProc:
    pid = 4242

    def poll(self):
        return None


@contextmanager
def _bot_settings(enabled: bool, token: str | None):
    """Set the panel's bot row, restoring it on the way out."""
    from backend.db import models
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(models.Settings).first()
        if row is None:
            yield
            return
        before = (row.bot_enabled, row.bot_token)
        row.bot_enabled = enabled
        row.bot_token = token
        db.commit()
        try:
            yield
        finally:
            row.bot_enabled, row.bot_token = before
            db.commit()
    finally:
        db.close()


def _record_popen(monkeypatch) -> list:
    import subprocess

    spawned: list = []

    def fake_popen(*args, **kwargs):
        spawned.append(args)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return spawned


def test_flag_off_spawns_the_bot_exactly_as_before(monkeypatch):
    """Unchanged: the child itself decides, and exits 0 when nothing is set."""
    import backend.bot_supervisor as sup

    with _bot_settings(enabled=False, token=None):
        _flag_off(monkeypatch)
        spawned = _record_popen(monkeypatch)
        sup.start_bot()
    assert len(spawned) == 1


def test_flag_on_skips_the_spawn_when_the_bot_is_disabled(monkeypatch):
    import backend.bot_supervisor as sup

    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with _bot_settings(enabled=False, token=None):
        _flag_on(monkeypatch)
        spawned = _record_popen(monkeypatch)
        assert sup.start_bot() is None, "low mode with no bot to run must not start a process"
        assert sup._watchdog_bot() is None, "nothing spawned → nothing to watch"
    assert spawned == []


def test_flag_on_still_spawns_a_configured_bot(monkeypatch):
    """Enabled path untouched: low mode only skips a bot that cannot run."""
    import backend.bot_supervisor as sup

    with _bot_settings(enabled=True, token="123:abc"):
        _flag_on(monkeypatch)
        spawned = _record_popen(monkeypatch)
        proc = sup.start_bot()
    assert proc is not None
    assert len(spawned) == 1


def test_the_watchdog_starts_the_bot_once_the_operator_enables_it(monkeypatch):
    """Suppression is re-evaluated every tick — never latched at startup.

    Low mode with no bot configured skips the spawn; the operator who then
    turns the bot on must get it started on the next watchdog tick, without
    a panel restart.
    """
    import backend.bot_supervisor as sup

    with _bot_settings(enabled=False, token=None):
        _flag_on(monkeypatch)
        spawned = _record_popen(monkeypatch)
        sup._bot_process = None
        sup._watchdog_bot()
        assert spawned == [], "still suppressed → the tick spawns nothing"

        with _bot_settings(enabled=True, token="123:abc"):
            sup._watchdog_bot()
            assert len(spawned) == 1, "enabled mid-run → the next tick must start the bot"
            assert sup._bot_process is not None


def test_the_watchdog_leaves_the_first_spawn_to_the_lifespan_when_flag_off(monkeypatch):
    """Flag off: unchanged — the lifespan owns the first spawn, watchdog only restarts."""
    import backend.bot_supervisor as sup

    with _bot_settings(enabled=True, token="123:abc"):
        _flag_off(monkeypatch)
        spawned = _record_popen(monkeypatch)
        sup._bot_process = None
        sup._watchdog_bot()
    assert spawned == []


# ── the flag itself ─────────────────────────────────────────────────────────


def test_the_flag_reads_settings_kv_with_a_truthy_parse(monkeypatch):
    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)
    for raw, expected in (("1", True), ("true", True), (True, True), ("0", False), ("false", False), (False, False), (0, False)):
        monkeypatch.setattr(config, "get_setting", lambda key, default=None, _raw=raw: _raw)
        assert config.low_resource_enabled() is expected, f"{raw!r} must read as {expected}"


def test_the_flag_reads_the_env_override(monkeypatch):
    monkeypatch.setattr(config, "get_setting", lambda key, default=None: True)
    monkeypatch.setenv("OVMANAGER_LOW_RESOURCE", "1")
    assert config.low_resource_enabled() is True

    monkeypatch.setattr(config, "get_setting", lambda key, default=None: False)
    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)
    assert config.low_resource_enabled() is False


def test_a_missing_database_reads_as_flag_off(monkeypatch):
    """A missing table must never keep the panel from starting."""
    monkeypatch.delenv("OVMANAGER_LOW_RESOURCE", raising=False)

    def boom(key, default=None):
        raise RuntimeError("no such table: settings_kv")

    monkeypatch.setattr(config, "get_setting", boom)
    assert config.low_resource_enabled() is False
