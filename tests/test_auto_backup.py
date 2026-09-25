# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for the scheduled automatic database backup (v7 schema + scheduler).

Every test/fixture is named ``ab_*`` so this module cannot collide with another
suite. Migration tests build throwaway SQLite files; the settings/scheduler
tests share the dev database and restore every setting they touch in a
``finally`` block (an autouse fixture makes that unconditional).
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import backend.app as app_module
import backend.routers.maintenance as maintenance
import backend.scheduler as sched_module
from backend.db import migrations
from backend.db.engine import SessionLocal
from backend.db.migrations import SCHEMA_VERSION
from backend.db.models import Settings

AUTO_BACKUP_COLUMNS = {"auto_backup_enabled", "auto_backup_time", "auto_backup_keep"}


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def ab_session(tmp_path):
    """Session bound to an isolated SQLite file (never the dev database)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'ab_auto_backup.db'}", connect_args={"check_same_thread": False})
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def ab_client():
    """TestClient with owner auth overridden (same style as test_notifier)."""
    from backend.auth.authz import require_owner

    app_module.api.dependency_overrides[require_owner] = lambda: "owner"
    client = TestClient(app_module.api)
    try:
        yield client
    finally:
        app_module.api.dependency_overrides.pop(require_owner, None)


@pytest.fixture(autouse=True)
def ab_preserve_settings():
    """Snapshot/restore the three auto-backup settings on the shared dev DB."""

    def _snapshot():
        db = SessionLocal()
        try:
            row = db.query(Settings).first()
            return (bool(row.auto_backup_enabled), str(row.auto_backup_time), int(row.auto_backup_keep))
        finally:
            db.close()

    before = _snapshot()
    try:
        yield
    finally:
        db = SessionLocal()
        try:
            row = db.query(Settings).first()
            row.auto_backup_enabled, row.auto_backup_time, row.auto_backup_keep = before
            db.commit()
        finally:
            db.close()


def ab_set_settings(*, enabled: bool, time: str = "03:30", keep: int = 50):
    db = SessionLocal()
    try:
        row = db.query(Settings).first()
        row.auto_backup_enabled = enabled
        row.auto_backup_time = time
        row.auto_backup_keep = keep
        db.commit()
    finally:
        db.close()


def ab_max_audit_id() -> int:
    db = SessionLocal()
    try:
        return int(db.execute(text("SELECT COALESCE(MAX(id), 0) FROM audit_logs")).scalar() or 0)
    finally:
        db.close()


class ab_FakeScheduler:
    """Records add_job/remove_job calls without touching APScheduler."""

    def __init__(self):
        self.added: list[dict] = []
        self.removed: list[str] = []

    def add_job(self, func, trigger, **kwargs):
        self.added.append({"func": func, "trigger": trigger, **kwargs})

    def remove_job(self, job_id):
        self.removed.append(job_id)


# ── Migration v7 ─────────────────────────────────────────────────────────────


def test_ab_migration_adds_auto_backup_columns(ab_session):
    assert migrations.migrate(ab_session) == SCHEMA_VERSION
    assert SCHEMA_VERSION >= 7

    columns = {c["name"] for c in inspect(ab_session.bind).get_columns("settings")}
    assert AUTO_BACKUP_COLUMNS <= columns

    row = ab_session.execute(text("SELECT auto_backup_enabled, auto_backup_time, auto_backup_keep FROM settings")).fetchone()
    assert row == (0, "03:30", 50), "defaults must be off, 03:30 and 50"
    assert migrations.verify_schema(ab_session) == []


def test_ab_migration_v7_upgrades_database_stamped_at_v6(ab_session):
    """An existing install keeps its settings row and gains the new columns."""
    migrations.migrate(ab_session)
    for name in AUTO_BACKUP_COLUMNS:
        ab_session.execute(text(f"ALTER TABLE settings DROP COLUMN {name}"))
    ab_session.execute(text("DELETE FROM schema_version"))
    ab_session.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (6, 0, 'pre-v7')"))
    ab_session.commit()

    assert migrations.migrate(ab_session) == SCHEMA_VERSION

    columns = {c["name"] for c in inspect(ab_session.bind).get_columns("settings")}
    assert AUTO_BACKUP_COLUMNS <= columns
    row = ab_session.execute(text("SELECT auto_backup_enabled, auto_backup_time, auto_backup_keep FROM settings")).fetchone()
    assert row == (0, "03:30", 50), "existing rows must get the backward-compatible defaults"
    assert migrations.current_version(ab_session) == SCHEMA_VERSION
    assert migrations.verify_schema(ab_session) == []


# ── Settings API roundtrip ───────────────────────────────────────────────────


def test_ab_settings_defaults_roundtrip_and_validation(ab_client):
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    # Start from the documented defaults so the assertions are deterministic
    # even if a previous run left the shared row modified.
    res = ab_client.put(
        "/api/server/settings/bot",
        json={"auto_backup_enabled": False, "auto_backup_time": "03:30", "auto_backup_keep": 50},
        headers=csrf,
    )
    assert res.status_code == 200 and res.json()["success"] is True

    data = ab_client.get("/api/server/settings").json()["data"]
    assert data["auto_backup_enabled"] is False
    assert data["auto_backup_time"] == "03:30"
    assert data["auto_backup_keep"] == 50

    # Valid update is persisted and echoed back.
    res = ab_client.put(
        "/api/server/settings/bot",
        json={"auto_backup_enabled": True, "auto_backup_time": "04:45", "auto_backup_keep": 12},
        headers=csrf,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["auto_backup_enabled"] is True
    assert body["data"]["auto_backup_time"] == "04:45"
    assert body["data"]["auto_backup_keep"] == 12

    data = ab_client.get("/api/server/settings").json()["data"]
    assert data["auto_backup_enabled"] is True
    assert data["auto_backup_time"] == "04:45"
    assert data["auto_backup_keep"] == 12

    # Invalid values are rejected with success=false and change nothing.
    for bad_time in ("24:00", "3:30", "03:60", "abc", "03:30:00", ""):
        res = ab_client.put("/api/server/settings/bot", json={"auto_backup_time": bad_time}, headers=csrf)
        assert res.status_code == 200, res.text
        assert res.json()["success"] is False
        assert "auto_backup_time" in res.json()["msg"]

    for bad_keep in (0, -1, 501, 1000):
        res = ab_client.put("/api/server/settings/bot", json={"auto_backup_keep": bad_keep}, headers=csrf)
        assert res.status_code == 200, res.text
        assert res.json()["success"] is False
        assert "auto_backup_keep" in res.json()["msg"]

    data = ab_client.get("/api/server/settings").json()["data"]
    assert data["auto_backup_enabled"] is True
    assert data["auto_backup_time"] == "04:45"
    assert data["auto_backup_keep"] == 12


# ── Scheduled job ────────────────────────────────────────────────────────────


def test_ab_job_does_nothing_when_disabled(monkeypatch):
    def ab_forbidden(*args, **kwargs):
        raise AssertionError("create_panel_backup must not run while auto backup is disabled")

    monkeypatch.setattr(maintenance, "create_panel_backup", ab_forbidden)
    ab_set_settings(enabled=False)

    before_id = ab_max_audit_id()
    asyncio.run(app_module.auto_backup_job())

    db = SessionLocal()
    try:
        count = db.execute(text("SELECT COUNT(*) FROM audit_logs WHERE actor = 'auto' AND id > :i"), {"i": before_id}).scalar()
    finally:
        db.close()
    assert count == 0


def test_ab_job_creates_one_backup_and_audit_row_when_enabled(monkeypatch):
    calls = []

    def ab_spy_create(*args, **kwargs):
        calls.append((args, kwargs))
        return Path("/tmp/ab_fake_backup.db")

    monkeypatch.setattr(maintenance, "create_panel_backup", ab_spy_create)
    ab_set_settings(enabled=True, time="03:30", keep=50)

    before_id = ab_max_audit_id()
    try:
        asyncio.run(app_module.auto_backup_job())

        assert len(calls) == 1, "exactly one backup must be created per run"
        assert calls[0][0] == (50,), "the configured keep count must be passed through"

        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT action, actor, detail FROM audit_logs WHERE actor = 'auto' AND id > :i ORDER BY id DESC LIMIT 1"),
                {"i": before_id},
            ).fetchone()
        finally:
            db.close()
        assert row is not None, "the scheduled backup must write an audit row"
        assert row[0] == "maintenance.backup"
        assert row[1] == "auto"
        assert "ab_fake_backup.db" in row[2]
    finally:
        # Keep the shared audit log clean: drop only rows this test created.
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM audit_logs WHERE actor = 'auto' AND id > :i"), {"i": before_id})
            db.commit()
        finally:
            db.close()


def test_ab_job_never_raises_when_backup_fails(monkeypatch):
    def ab_boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(maintenance, "create_panel_backup", ab_boom)
    ab_set_settings(enabled=True)

    before_id = ab_max_audit_id()
    try:
        asyncio.run(app_module.auto_backup_job())  # must not raise

        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT detail FROM audit_logs WHERE actor = 'auto' AND id > :i ORDER BY id DESC LIMIT 1"),
                {"i": before_id},
            ).fetchone()
        finally:
            db.close()
        assert row is not None and "disk on fire" in row[0]
    finally:
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM audit_logs WHERE actor = 'auto' AND id > :i"), {"i": before_id})
            db.commit()
        finally:
            db.close()


# ── Rescheduling ─────────────────────────────────────────────────────────────


def test_ab_reschedule_registers_and_removes_job(monkeypatch):
    fake = ab_FakeScheduler()
    monkeypatch.setattr(sched_module, "_scheduler", fake)

    ab_set_settings(enabled=False)
    sched_module.reschedule_auto_backup()
    assert fake.removed == ["auto_backup"]
    assert fake.added == []

    ab_set_settings(enabled=True, time="04:45")
    sched_module.reschedule_auto_backup()
    assert fake.removed == ["auto_backup", "auto_backup"]
    assert len(fake.added) == 1

    job = fake.added[0]
    assert job["id"] == "auto_backup"
    assert job["func"] is app_module.auto_backup_job
    fields = {f.name: str(f) for f in job["trigger"].fields}
    assert fields["hour"] == "4"
    assert fields["minute"] == "45"


def test_ab_reschedule_is_noop_without_scheduler(monkeypatch):
    monkeypatch.setattr(sched_module, "_scheduler", None)
    sched_module.reschedule_auto_backup()  # must not raise
