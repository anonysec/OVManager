"""Tests for the D2 threshold alert engine.

Covers ``backend/operations/observability/thresholds.py`` (trip / no-trip,
de-dupe, toggles, failed-send retry, inbox rows), the v19 settings columns,
and the ``POST /server/alerts/test`` endpoint. Every test is named
``test_th_*`` (selectable with ``-k test_th_``) and every fixture/helper
carries the ``th_`` prefix so this module can never collide with another
suite. Telegram is never reached: ``send_telegram`` is replaced with a
recorder, and the panel's real database is left as it was.
"""

import datetime as dt
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.db import crud, migrations
from backend.db.engine import Base
from backend.db.migrations import SCHEMA_VERSION, ensure_extra_tables
from backend.db.models import Settings, User
from backend.operations.observability import notifier, thresholds


@pytest.fixture()
def th_session(tmp_path):
    """Session bound to an isolated SQLite file created from the models."""
    engine = create_engine(f"sqlite:///{tmp_path / 'thresholds.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = maker()
    ensure_extra_tables(db)  # node_health_snapshots feeds the CPU threshold
    thresholds._notified.clear()
    try:
        yield db
    finally:
        thresholds._notified.clear()
        db.close()
        engine.dispose()


@pytest.fixture()
def th_settings(th_session):
    """The singleton settings row for the isolated session."""
    row = Settings(port=1194, protocol="tcp")
    th_session.add(row)
    th_session.commit()
    return row


@pytest.fixture()
def th_sent(monkeypatch):
    """Record Telegram messages instead of sending them; every send "works"."""
    sent = []
    monkeypatch.setattr(thresholds, "send_telegram", lambda body, db=None: sent.append(body) or True)
    return sent


def th_user(name, *, expiry=None, total=None, used=0, active=True):
    return User(
        name=name,
        expiry_date=expiry or (dt.datetime.now(dt.UTC).date() + timedelta(days=30)),
        total=total,
        used=used,
        is_active=active,
        owner="owner",
    )


def th_set_cpu(db, node_id: int, name: str, cpu: float) -> None:
    """Insert or update one node's latest recorded CPU."""
    row = db.execute(text("SELECT id FROM node_health_snapshots WHERE node_id = :i"), {"i": node_id}).fetchone()
    if row:
        db.execute(text("UPDATE node_health_snapshots SET cpu = :c WHERE id = :id"), {"c": cpu, "id": row[0]})
    else:
        db.execute(
            text(
                "INSERT INTO node_health_snapshots (ts, node_id, node_name, cpu, memory, live_count, latency_ms, reachable) "
                "VALUES (1.0, :i, :n, :c, 0, 0, 0, 1)"
            ),
            {"i": node_id, "n": name, "c": cpu},
        )
    db.commit()


def test_th_expiry_trips_once_then_stays_silent(th_session, th_settings, th_sent):
    """A persistent condition pages on the first run and never again."""
    today = dt.datetime.now(dt.UTC).date()
    th_session.add(th_user("soon", expiry=today + timedelta(days=2)))
    th_session.commit()

    assert thresholds.check_threshold_alerts(th_session) == 1
    assert thresholds.check_threshold_alerts(th_session) == 0
    assert len(th_sent) == 1
    assert "soon" in th_sent[0]


def test_th_no_trip_when_under_every_threshold(th_session, th_settings, th_sent):
    today = dt.datetime.now(dt.UTC).date()
    th_session.add_all(
        [
            th_user("later", expiry=today + timedelta(days=10), total=100, used=50),
            th_user("quiet", total=100, used=79),
        ]
    )
    th_session.commit()

    assert thresholds.threshold_items(th_session) == []
    assert thresholds.check_threshold_alerts(th_session) == 0
    assert th_sent == []


def test_th_usage_trips_at_the_limit(th_session, th_settings, th_sent):
    th_session.add(th_user("edge", total=100, used=79))
    th_session.commit()

    assert thresholds.check_threshold_alerts(th_session) == 0, "79% must stay under the 80% default"

    th_session.query(User).filter_by(name="edge").update({"used": 80})
    th_session.commit()
    assert thresholds.check_threshold_alerts(th_session) == 1
    assert "80%" in th_sent[0]

    # Over quota: a changed condition set is a new signature -> one more page.
    th_session.query(User).filter_by(name="edge").update({"used": 100})
    th_session.commit()
    items = thresholds.threshold_items(th_session)
    assert items and items[0]["level"] == "danger"
    assert thresholds.check_threshold_alerts(th_session) == 1
    assert len(th_sent) == 2


def test_th_cpu_trip_clear_and_retrip(th_session, th_settings, th_sent):
    th_set_cpu(th_session, 1, "de-1", 90.0)

    assert thresholds.check_threshold_alerts(th_session) == 1
    assert thresholds.check_threshold_alerts(th_session) == 0, "second run must be silent"

    th_set_cpu(th_session, 1, "de-1", 40.0)
    assert thresholds.check_threshold_alerts(th_session) == 0

    th_set_cpu(th_session, 1, "de-1", 95.0)
    assert thresholds.check_threshold_alerts(th_session) == 1, "a cleared-then-returned condition announces again"
    assert len(th_sent) == 2
    assert "de-1" in th_sent[0] and "90%" in th_sent[0]


def test_th_disabled_events_send_nothing(th_session, th_settings, th_sent):
    today = dt.datetime.now(dt.UTC).date()
    th_settings.notify_expiry = False
    th_settings.alert_usage_enabled = False
    th_settings.alert_cpu_enabled = False
    th_session.commit()
    th_session.add_all([th_user("soon", expiry=today + timedelta(days=1)), th_user("hog", total=100, used=100)])
    th_session.commit()
    th_set_cpu(th_session, 1, "de-1", 99.0)

    assert thresholds.threshold_items(th_session) == []
    assert thresholds.check_threshold_alerts(th_session) == 0
    assert th_sent == []


def test_th_failed_send_is_retried_next_run(th_session, th_settings, monkeypatch):
    """Nothing marks a threshold announced until Telegram says yes."""
    today = dt.datetime.now(dt.UTC).date()
    th_session.add(th_user("soon", expiry=today + timedelta(days=1)))
    th_session.commit()

    results = [False, True]
    attempts = []

    def th_flaky(body, db=None):
        attempts.append(body)
        return results[len(attempts) - 1]

    monkeypatch.setattr(thresholds, "send_telegram", th_flaky)

    assert thresholds.check_threshold_alerts(th_session) == 0
    assert thresholds.check_threshold_alerts(th_session) == 1
    assert len(attempts) == 2
    assert thresholds._notified.get("threshold_expiry") is not None


def test_th_inbox_rows_carry_severity(th_session, th_settings, th_sent):
    """``/notifications/`` reads the same conditions the Telegram path does."""
    today = dt.datetime.now(dt.UTC).date()
    th_session.add_all(
        [
            th_user("soon", expiry=today + timedelta(days=3)),
            th_user("hog", total=100, used=100),
        ]
    )
    th_session.commit()
    th_set_cpu(th_session, 7, "nl-1", 85.0)

    by_type = {item["type"]: item for item in thresholds.threshold_items(th_session)}
    assert by_type["threshold_expiry"]["level"] == "warning"
    assert by_type["threshold_usage"]["level"] == "danger"
    assert by_type["threshold_cpu"]["target"] == "nl-1"
    assert set(by_type) <= {"threshold_expiry", "threshold_usage", "threshold_cpu"}

    # Usage rows stay out of the inbox (the client derives quota warnings);
    # expiry and CPU are the ones only this engine knows about.
    assert "threshold_usage" not in thresholds.INBOX_TYPES
    assert set(by_type) - {"threshold_usage"} <= thresholds.INBOX_TYPES


def test_th_migration_v19_adds_threshold_columns(th_session):
    assert migrations.migrate(th_session) == SCHEMA_VERSION
    columns = {c["name"] for c in inspect(th_session.bind).get_columns("settings")}
    assert {"alert_days_left", "alert_usage_enabled", "alert_usage_pct", "alert_cpu_enabled", "alert_cpu_pct"} <= columns

    th_session.execute(text("ALTER TABLE settings DROP COLUMN alert_usage_pct"))
    th_session.execute(text("DELETE FROM schema_version"))
    th_session.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (18, 0, 'pre-v19')"))
    th_session.commit()

    assert migrations.migrate(th_session) == SCHEMA_VERSION
    columns = {c["name"] for c in inspect(th_session.bind).get_columns("settings")}
    assert "alert_usage_pct" in columns
    assert migrations.verify_schema(th_session) == []


def test_th_test_endpoint_sends(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import api
    from backend.auth.authz import require_owner

    sent = []
    monkeypatch.setattr(notifier, "send_telegram", lambda body, db=None: sent.append(body) or True)
    api.dependency_overrides[require_owner] = lambda: "owner"
    client = TestClient(api)
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    try:
        res = client.post("/api/server/alerts/test", json={"channel": "telegram"}, headers=csrf)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["data"]["channel"] == "telegram"
        assert len(sent) == 1 and "test alert" in sent[0].lower()

        res = client.post("/api/server/alerts/test", json={"channel": "smtp"}, headers=csrf)
        assert res.json()["success"] is False, "unknown channels are refused"
        assert len(sent) == 1

        monkeypatch.setattr(notifier, "send_telegram", lambda body, db=None: False)
        res = client.post("/api/server/alerts/test", json={}, headers=csrf)
        assert res.json()["success"] is False, "a failed send must not read as success"
    finally:
        api.dependency_overrides.pop(require_owner, None)


def test_th_settings_roundtrip():
    from fastapi.testclient import TestClient

    from backend.app import api
    from backend.auth.authz import require_owner
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    current = crud.get_settings(db)
    before = (
        current.alert_days_left,
        current.alert_usage_enabled,
        current.alert_usage_pct,
        current.alert_cpu_enabled,
        current.alert_cpu_pct,
    )
    api.dependency_overrides[require_owner] = lambda: "owner"
    client = TestClient(api)
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    try:
        res = client.put(
            "/api/server/settings/bot",
            json={"alert_days_left": 5, "alert_usage_pct": 90, "alert_cpu_pct": 70, "alert_cpu_enabled": False},
            headers=csrf,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["alert_days_left"] == 5
        assert data["alert_usage_pct"] == 90
        assert data["alert_cpu_pct"] == 70
        assert data["alert_cpu_enabled"] is False

        res = client.put("/api/server/settings/bot", json={"alert_usage_pct": 101}, headers=csrf)
        assert res.json()["success"] is False, "out-of-range thresholds are rejected"

        res = client.put("/api/server/settings/bot", json={"alert_days_left": 0}, headers=csrf)
        assert res.json()["success"] is True, "0 days (today only) is a real value"
        res = client.get("/api/server/settings")
        data = res.json()["data"]
        assert data["alert_days_left"] == 0
        assert data["alert_usage_pct"] == 90, "the rejected write must not have applied"
        assert data["alert_cpu_enabled"] is False
    finally:
        api.dependency_overrides.pop(require_owner, None)
        (
            current.alert_days_left,
            current.alert_usage_enabled,
            current.alert_usage_pct,
            current.alert_cpu_enabled,
            current.alert_cpu_pct,
        ) = before
        db.commit()
        db.close()
