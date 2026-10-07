"""Tests for Part E — the unified audit-centric event pipeline.

Covers ``record_event`` (row shape), ``promote_events`` (delivered-marker
de-dupe: notify once, silent on repeat, re-announce after a clear, retry
after a failed send), transition-only recording for the D2 thresholds, node
checks and health checks, and the v23 ``delivered`` migration. Telegram is
never reached: senders are recorders. Every fixture/helper carries the
``ue_`` prefix so this module can never collide with another suite.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid as uuid_mod
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.db import migrations
from backend.db.engine import Base
from backend.db.migrations import SCHEMA_VERSION, ensure_extra_tables, table_names
from backend.db.models import Settings, User
from backend.operations.observability import audit, node_alerts, thresholds


@pytest.fixture()
def ue_db(tmp_path):
    """Session bound to an isolated SQLite file created from the models."""
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = maker()
    ensure_extra_tables(db)
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def ue_sent(ue_db, monkeypatch):
    """Record Telegram messages instead of sending them; every send works."""
    sent: list[str] = []
    monkeypatch.setattr(audit, "send_telegram", lambda body, db=None: sent.append(body) or True)
    return sent


def ue_enroll(db, kind: str = "test.event", message: str = "boom", severity: str = "error") -> str:
    """Record one event that is enrolled for promotion; returns its event_key."""
    key = uuid_mod.uuid4().hex
    audit.record_event(db, kind, severity, message, meta={"event_key": key, "target": "t1"})
    return key


def ue_rows(db, action: str) -> list[dict]:
    return audit.recent_events(db, limit=500, action=action)


def test_ue_record_event_writes_row(ue_db):
    audit.record_event(ue_db, "node.down", "error", "Node de-1 is unreachable.", meta={"target": "de-1", "node_id": 1})

    rows = ue_rows(ue_db, "node.down")
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "system"
    assert row["target"] == "de-1"
    payload = json.loads(row["detail"])
    assert payload["severity"] == "error"
    assert payload["message"] == "Node de-1 is unreachable."
    assert payload["meta"]["node_id"] == 1


def test_ue_promoter_notifies_once_then_stays_silent(ue_db, ue_sent):
    key = ue_enroll(ue_db)

    assert audit.promote_events(ue_db) == 1
    assert audit.promote_events(ue_db) == 0, "a delivered event must never re-send"
    assert ue_sent == ["boom"]

    markers = [(r[0], r[1]) for r in ue_db.execute(text("SELECT subscription, event_key FROM delivered")).fetchall()]
    assert ("test.event", key) in markers


def test_ue_promoter_reannounces_after_clear(ue_db, ue_sent):
    ue_enroll(ue_db, message="first trip")
    assert audit.promote_events(ue_db) == 1

    # clear: an info row without event_key — recorded, never promoted
    audit.record_event(ue_db, "test.event", "info", "condition cleared", meta={"signature": ""})
    assert audit.promote_events(ue_db) == 0

    ue_enroll(ue_db, message="returned")
    assert audit.promote_events(ue_db) == 1, "a cleared-then-returned condition announces again"
    assert ue_sent == ["first trip", "returned"]


def test_ue_failed_send_retries_until_accepted(ue_db):
    key = ue_enroll(ue_db)
    attempts: list[str] = []

    def ue_flaky(body, db=None):
        attempts.append(body)
        return len(attempts) > 1

    assert audit.promote_events(ue_db, send=ue_flaky) == 0
    markers = ue_db.execute(text("SELECT COUNT(*) FROM delivered")).scalar()
    assert markers == 0, "a failed send writes no marker"

    assert audit.promote_events(ue_db, send=ue_flaky) == 1
    assert audit.promote_events(ue_db, send=ue_flaky) == 0
    assert len(attempts) == 2, "the unmarked row retried on the next call, then went silent"
    markers = [(r[0], r[1]) for r in ue_db.execute(text("SELECT subscription, event_key FROM delivered")).fetchall()]
    assert ("test.event", key) in markers


def test_ue_threshold_check_records_transitions_not_ticks(ue_db, monkeypatch):
    """An unchanged condition set writes no second audit row and sends once."""
    ue_db.add(Settings(port=1194, protocol="tcp"))
    ue_db.add(
        User(
            name="soon",
            expiry_date=dt.datetime.now(dt.UTC).date() + timedelta(days=2),
            is_active=True,
            owner="owner",
        )
    )
    ue_db.commit()
    sent: list[str] = []
    monkeypatch.setattr(thresholds, "send_telegram", lambda body, db=None: sent.append(body) or True)

    assert thresholds.check_threshold_alerts(ue_db) == 1
    assert len(ue_rows(ue_db, "threshold_expiry")) == 1

    assert thresholds.check_threshold_alerts(ue_db) == 0, "the same signature on the next tick is silent"
    assert len(ue_rows(ue_db, "threshold_expiry")) == 1, "an unchanged condition never writes a row"
    assert len(sent) == 1


def test_ue_node_check_records_transitions_only(monkeypatch):
    """Seed and unchanged ticks write nothing; down/up transitions write one row each."""
    calls: list[tuple] = []
    node_alerts._node_state.clear()
    node_alerts._last_down_alert.clear()
    node_alerts._alerted_down.clear()
    monkeypatch.setattr(node_alerts, "record_event", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(node_alerts, "send_telegram", lambda *a, **k: True)
    try:

        def ue_row(up: bool) -> dict:
            return {"node_id": 1, "node_name": "de-1", "reachable": 1 if up else 0}

        t0 = 1_000_000.0
        node_alerts.check_node_alerts([ue_row(True)], now=t0)  # seed
        node_alerts.check_node_alerts([ue_row(True)], now=t0 + 300)  # unchanged
        assert calls == []

        node_alerts.check_node_alerts([ue_row(False)], now=t0 + 600)
        assert len(calls) == 1
        assert calls[0][0][1] == "node.down"
        assert calls[0][0][2] == "error"
        assert calls[0][1]["meta"]["target"] == "de-1"

        node_alerts.check_node_alerts([ue_row(False)], now=t0 + 900)  # still down: no row
        assert len(calls) == 1

        node_alerts.check_node_alerts([ue_row(True)], now=t0 + 1200)
        assert len(calls) == 2
        assert calls[1][0][1] == "node.up"
        assert calls[1][0][2] == "info"
    finally:
        node_alerts._node_state.clear()
        node_alerts._last_down_alert.clear()
        node_alerts._alerted_down.clear()


def test_ue_health_check_records_transitions_only(ue_db):
    """First observation seeds, a failing change enrolls, repeats stay silent."""
    from backend.routers import health as health_router

    health_router._check_state.clear()
    try:
        ue_ok = {"id": "disk", "status": "ok", "summary": "100 GB free."}
        ue_warn = {"id": "disk", "status": "warn", "summary": "Only 4.0 GB is free."}

        health_router._record_check_transition(ue_db, ue_ok)  # seed
        assert ue_rows(ue_db, "health.disk") == []

        health_router._record_check_transition(ue_db, ue_warn)  # first failure
        rows = ue_rows(ue_db, "health.disk")
        assert len(rows) == 1
        payload = json.loads(rows[0]["detail"])
        assert payload["severity"] == "warning"
        assert payload["meta"]["event_key"], "a failing transition is enrolled for promotion"

        health_router._record_check_transition(ue_db, ue_warn)  # unchanged tick
        assert len(ue_rows(ue_db, "health.disk")) == 1

        health_router._record_check_transition(ue_db, ue_ok)  # recovery: audit-only
        rows = ue_rows(ue_db, "health.disk")  # newest first
        assert len(rows) == 2
        payload = json.loads(rows[0]["detail"])
        assert payload["severity"] == "info"
        assert "event_key" not in payload["meta"]
    finally:
        health_router._check_state.clear()


def test_ue_migration_adds_delivered_table(tmp_path):
    """A stamped v22 install gains the delivered table on migrate()."""
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        Base.metadata.create_all(bind=engine)  # a v22 install: mapped tables, no delivered
        db.execute(text("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL, note TEXT)"))
        db.execute(
            text("INSERT INTO schema_version (version, applied_at, note) VALUES (:v, 0, 'v22')"),
            {"v": SCHEMA_VERSION - 1},
        )
        db.commit()
        assert "delivered" not in table_names(db)

        assert migrations.migrate(db) == SCHEMA_VERSION

        assert "delivered" in table_names(db)
        sql = db.execute(text("SELECT sql FROM sqlite_master WHERE name = 'delivered'")).scalar()
        assert sql and "UNIQUE" in sql and "subscription" in sql and "event_key" in sql
        assert migrations.verify_schema(db) == []
    finally:
        db.close()
        engine.dispose()
