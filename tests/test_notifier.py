# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for backend/operations/notifier.py and the v6 notification columns.

Every test is named ``test_nt_*`` (selectable with ``-k test_nt_``) and every
fixture/helper carries the ``nt_`` prefix so this module can never collide with
another suite. No test ever reaches Telegram: the HTTPS call and token
decryption are patched, and the panel's real database is left as it was.
"""

import datetime as dt
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import backend.db.crud.crypto as crud_crypto
from backend.db import crud, migrations
from backend.db.engine import Base
from backend.db.migrations import SCHEMA_VERSION
from backend.db.models import Settings, User
from backend.operations import notifier


@pytest.fixture()
def nt_session(tmp_path):
    """Session bound to an isolated SQLite file created from the models."""
    engine = create_engine(f"sqlite:///{tmp_path / 'notifier.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def nt_settings(nt_session):
    """The singleton settings row for the isolated session."""
    row = Settings(port=1194, protocol="tcp")
    nt_session.add(row)
    nt_session.commit()
    return row


def nt_user(name, *, expiry=None, total=None, used=0, active=True):
    return User(
        name=name,
        expiry_date=expiry or (dt.datetime.now(dt.UTC).date() + timedelta(days=30)),
        total=total,
        used=used,
        is_active=active,
        owner="owner",
    )


# ── collect_alerts ───────────────────────────────────────────────────────────


def test_nt_collect_alerts_groups_users(nt_session):
    today = dt.datetime.now(dt.UTC).date()
    nt_session.add_all(
        [
            nt_user("expiring_soon", expiry=today + timedelta(days=2)),
            nt_user("expiring_edge", expiry=today + timedelta(days=3)),
            nt_user("expires_later", expiry=today + timedelta(days=10)),
            nt_user("over_quota", total=100, used=100),
            nt_user("under_quota", total=100, used=50),
            nt_user("unlimited", total=None, used=10**12),
            nt_user("disabled_expired", expiry=today - timedelta(days=1), active=False),
            nt_user("disabled_quota", total=10, used=99, active=False),
            nt_user("disabled_plain", active=False),
        ]
    )
    nt_session.commit()

    alerts = notifier.collect_alerts(nt_session)

    assert alerts["expiring"] == ["expiring_edge", "expiring_soon"]
    assert alerts["out_of_traffic"] == ["over_quota"]
    assert alerts["disabled_expiry"] == ["disabled_expired"]
    assert alerts["disabled_traffic"] == ["disabled_quota"]


# ── build_summary ────────────────────────────────────────────────────────────


def test_nt_summary_compact_format():
    text = notifier.build_summary(
        {"expiring": ["a", "b", "c"], "out_of_traffic": ["d", "e"]},
        notify_expiry=True,
        notify_traffic=True,
    )
    assert text == "3 users expire within 3 days: a, b, c · 2 users are out of traffic: d, e"


def test_nt_summary_respects_category_flags():
    alerts = {
        "expiring": ["alice"],
        "out_of_traffic": ["bob"],
        "disabled_expiry": ["carol"],
        "disabled_traffic": ["dave"],
    }

    expiry_only = notifier.build_summary(alerts, notify_expiry=True, notify_traffic=False)
    assert "alice" in expiry_only and "carol" in expiry_only
    assert "bob" not in expiry_only and "dave" not in expiry_only

    traffic_only = notifier.build_summary(alerts, notify_expiry=False, notify_traffic=True)
    assert "bob" in traffic_only and "dave" in traffic_only
    assert "alice" not in traffic_only and "carol" not in traffic_only

    assert notifier.build_summary(alerts, notify_expiry=False, notify_traffic=False) == ""


# ── send_telegram ────────────────────────────────────────────────────────────


def nt_forbidden_post(*args, **kwargs):
    raise AssertionError("send_telegram must not call Telegram in this case")


def test_nt_send_skips_when_bot_disabled(nt_session, nt_settings, monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", nt_forbidden_post)
    nt_settings.bot_enabled = False
    nt_settings.bot_token = "irrelevant"
    nt_settings.owner_telegram_id = 123
    nt_session.commit()

    assert notifier.send_telegram("hello", db=nt_session) is False


def test_nt_send_skips_without_token(nt_session, nt_settings, monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", nt_forbidden_post)
    nt_settings.bot_enabled = True
    nt_settings.bot_token = None
    nt_settings.owner_telegram_id = 123
    nt_session.commit()

    assert notifier.send_telegram("hello", db=nt_session) is False


def test_nt_send_skips_without_owner(nt_session, nt_settings, monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", nt_forbidden_post)
    nt_settings.bot_enabled = True
    nt_settings.bot_token = "some-token"
    nt_settings.owner_telegram_id = None
    nt_session.commit()

    assert notifier.send_telegram("hello", db=nt_session) is False


def test_nt_send_skips_undecryptable_token(nt_session, nt_settings, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(notifier.requests, "post", nt_forbidden_post)
    monkeypatch.setattr(crud_crypto, "_fernet", Fernet(Fernet.generate_key()))
    nt_settings.bot_enabled = True
    nt_settings.bot_token = "enc:not-valid-ciphertext"
    nt_settings.owner_telegram_id = 123
    nt_session.commit()

    assert notifier.send_telegram("hello", db=nt_session) is False


def test_nt_send_posts_escaped_html(nt_session, nt_settings, monkeypatch):
    from cryptography.fernet import Fernet

    fernet = Fernet(Fernet.generate_key())
    nt_settings.bot_enabled = True
    nt_settings.bot_token = fernet.encrypt(b"123456:token").decode()
    nt_settings.owner_telegram_id = 555
    nt_session.commit()
    monkeypatch.setattr(crud_crypto, "_fernet", fernet)

    captured = {}

    class NtFakeResponse:
        ok = True
        status_code = 200

    def nt_fake_post(url, json=None, timeout=None):
        captured.update(url=url, json=json, timeout=timeout)
        return NtFakeResponse()

    monkeypatch.setattr(notifier.requests, "post", nt_fake_post)

    assert notifier.send_telegram("ali<admin> & co", db=nt_session) is True
    assert captured["url"].endswith("/bot123456:token/sendMessage")
    assert captured["json"]["chat_id"] == 555
    assert captured["json"]["parse_mode"] == "HTML"
    assert captured["json"]["text"] == "ali&lt;admin&gt; &amp; co"
    assert captured["timeout"] == notifier.HTTP_TIMEOUT_SECONDS


def test_nt_send_returns_false_on_http_error(nt_session, nt_settings, monkeypatch):
    from cryptography.fernet import Fernet

    fernet = Fernet(Fernet.generate_key())
    nt_settings.bot_enabled = True
    nt_settings.bot_token = fernet.encrypt(b"123456:token").decode()
    nt_settings.owner_telegram_id = 555
    nt_session.commit()
    monkeypatch.setattr(crud_crypto, "_fernet", fernet)

    class NtBadResponse:
        ok = False
        status_code = 400

    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: NtBadResponse())

    assert notifier.send_telegram("hello", db=nt_session) is False


# ── run_daily_alerts ─────────────────────────────────────────────────────────


def nt_alerts():
    return {"expiring": ["alice"], "out_of_traffic": [], "disabled_expiry": [], "disabled_traffic": []}


def test_nt_daily_guard_prevents_second_send(nt_session, nt_settings, monkeypatch):
    monkeypatch.setattr(notifier, "collect_alerts", lambda db: nt_alerts())
    monkeypatch.setattr(notifier, "SessionLocal", lambda: nt_session)
    monkeypatch.setattr(notifier, "_last_sent_day", None)
    sends = []
    monkeypatch.setattr(notifier, "send_telegram", lambda text, db=None: sends.append(text) or True)

    assert notifier.run_daily_alerts() is True
    assert notifier.run_daily_alerts() is False
    assert len(sends) == 1
    assert "alice" in sends[0]


def test_nt_daily_respects_disabled_flags(nt_session, nt_settings, monkeypatch):
    nt_settings.notify_expiry = False
    nt_settings.notify_traffic = False
    nt_session.commit()
    monkeypatch.setattr(notifier, "collect_alerts", lambda db: nt_alerts())
    monkeypatch.setattr(notifier, "SessionLocal", lambda: nt_session)
    monkeypatch.setattr(notifier, "_last_sent_day", None)
    sends = []
    monkeypatch.setattr(notifier, "send_telegram", lambda text, db=None: sends.append(text) or True)

    assert notifier.run_daily_alerts() is False
    assert sends == []


def test_nt_daily_never_raises(nt_session, monkeypatch):
    def nt_boom(db):
        raise RuntimeError("collect blew up")

    monkeypatch.setattr(notifier, "collect_alerts", nt_boom)
    monkeypatch.setattr(notifier, "SessionLocal", lambda: nt_session)
    monkeypatch.setattr(notifier, "_last_sent_day", None)

    assert notifier.run_daily_alerts() is False

    def nt_no_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(notifier, "SessionLocal", nt_no_session)
    assert notifier.run_daily_alerts() is False


# ── Settings endpoint roundtrip ──────────────────────────────────────────────


def test_nt_settings_endpoint_roundtrip():
    from fastapi.testclient import TestClient

    from backend.app import api
    from backend.auth.authz import require_owner
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    current = crud.get_settings(db)
    before = (bool(current.notify_expiry), bool(current.notify_traffic))
    api.dependency_overrides[require_owner] = lambda: "owner"
    client = TestClient(api)
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    try:
        res = client.put("/api/server/settings/bot", json={"notify_expiry": False, "notify_traffic": True}, headers=csrf)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["data"]["notify_expiry"] is False
        assert body["data"]["notify_traffic"] is True

        res = client.get("/api/server/settings")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["notify_expiry"] is False
        assert data["notify_traffic"] is True
    finally:
        api.dependency_overrides.pop(require_owner, None)
        current.notify_expiry, current.notify_traffic = before
        db.commit()
        db.close()


# ── Migration v6 ─────────────────────────────────────────────────────────────


def test_nt_migration_v6_adds_notification_flags(nt_session):
    migrations.migrate(nt_session)
    settings_columns = {c["name"] for c in inspect(nt_session.bind).get_columns("settings")}
    assert {"notify_expiry", "notify_traffic"} <= settings_columns

    # Pretend the database was stamped before v6, as an existing install would be.
    nt_session.execute(text("ALTER TABLE settings DROP COLUMN notify_expiry"))
    nt_session.execute(text("ALTER TABLE settings DROP COLUMN notify_traffic"))
    nt_session.execute(text("DELETE FROM schema_version"))
    nt_session.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (5, 0, 'pre-v6')"))
    nt_session.commit()

    assert migrations.migrate(nt_session) == SCHEMA_VERSION
    columns = {c["name"] for c in inspect(nt_session.bind).get_columns("settings")}
    assert {"notify_expiry", "notify_traffic"} <= columns
    row = nt_session.execute(text("SELECT notify_expiry, notify_traffic FROM settings")).fetchone()
    assert row == (1, 1), "existing rows must get the backward-compatible True default"
    assert migrations.current_version(nt_session) == SCHEMA_VERSION
