"""Part D1 (v1.3.0): the subscription-page profile surface.

Covers the v20 settings columns (title, support link, announcement, update
interval), their ``PUT /server/settings/subscription`` validation and
``GET /server/settings`` roundtrip, and what ``GET /sub/{uuid}`` renders once
they are set — and, just as importantly, what it stops rendering when they are
cleared. Every helper carries an ``spf_`` prefix so the module cannot collide
with another suite. The panel is OpenVPN-only: no client formats, no UA rules.
"""

import datetime as dt
import uuid as uuidlib

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.db import migrations
from backend.db.engine import Base, SessionLocal
from backend.db.migrations import SCHEMA_VERSION, verify_schema
from backend.db.models import Settings, User

CSRF = {"X-Requested-With": "XMLHttpRequest"}
_TITLE = "My VPN Page"
_SUPPORT = "https://support.example.com/ticket"
_ANNOUNCE = "Scheduled maintenance this Sunday."
_INTERVAL = 6


@pytest.fixture()
def spf_owner(monkeypatch):
    """Auth + CSRF stand-in for the owner-gated settings endpoints."""
    from fastapi.testclient import TestClient

    from backend.app import api
    from backend.auth.authz import require_owner

    api.dependency_overrides[require_owner] = lambda: "owner"
    try:
        yield TestClient(api)
    finally:
        api.dependency_overrides.pop(require_owner, None)


@pytest.fixture()
def spf_profile_settings():
    """Save/restore the four profile columns on the panel's real settings row."""
    db = SessionLocal()
    row = db.query(Settings).first()
    assert row is not None, "the session schema must seed a settings row"
    before = (
        row.sub_profile_title,
        row.sub_support_url,
        row.sub_announce,
        row.sub_update_interval_hours,
    )
    try:
        yield row
    finally:
        row.sub_profile_title, row.sub_support_url, row.sub_announce, row.sub_update_interval_hours = before
        db.commit()
        db.close()


def spf_profile_payload(**overrides):
    payload = {
        "sub_profile_title": _TITLE,
        "sub_support_url": _SUPPORT,
        "sub_announce": _ANNOUNCE,
        "sub_update_interval_hours": _INTERVAL,
    }
    payload.update(overrides)
    return payload


def test_spf_settings_roundtrip_and_validation(spf_owner, spf_profile_settings):
    """Write all four, read them back, then prove each bad value is refused."""
    res = spf_owner.put("/api/server/settings/subscription", json=spf_profile_payload(), headers=CSRF)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True, body
    assert body["data"]["sub_profile_title"] == _TITLE
    assert body["data"]["sub_support_url"] == _SUPPORT
    assert body["data"]["sub_announce"] == _ANNOUNCE
    assert body["data"]["sub_update_interval_hours"] == _INTERVAL

    data = spf_owner.get("/api/server/settings", headers=CSRF).json()["data"]
    assert data["sub_profile_title"] == _TITLE
    assert data["sub_support_url"] == _SUPPORT
    assert data["sub_announce"] == _ANNOUNCE
    assert data["sub_update_interval_hours"] == _INTERVAL

    # Out-of-range update interval: refused, previous value untouched.
    for bad in (0, 169):
        res = spf_owner.put(
            "/api/server/settings/subscription",
            json={"sub_update_interval_hours": bad},
            headers=CSRF,
        )
        assert res.json()["success"] is False, f"{bad} hours must be rejected"
    data = spf_owner.get("/api/server/settings", headers=CSRF).json()["data"]
    assert data["sub_update_interval_hours"] == _INTERVAL

    # Support link is rendered into an href on a public page: only http(s).
    res = spf_owner.put(
        "/api/server/settings/subscription",
        json={"sub_support_url": "javascript:alert(1)"},
        headers=CSRF,
    )
    assert res.json()["success"] is False
    res = spf_owner.put(
        "/api/server/settings/subscription",
        json={"sub_support_url": _SUPPORT},
        headers=CSRF,
    )
    assert res.json()["success"] is True, "an https link is accepted"

    # Free-text caps: a 65-char title / 501-char announcement are refused.
    res = spf_owner.put(
        "/api/server/settings/subscription",
        json={"sub_profile_title": "x" * 65},
        headers=CSRF,
    )
    assert res.json()["success"] is False
    res = spf_owner.put(
        "/api/server/settings/subscription",
        json={"sub_announce": "x" * 501},
        headers=CSRF,
    )
    assert res.json()["success"] is False

    # Clearing works: an empty title/support/announce is stored as-is.
    res = spf_owner.put(
        "/api/server/settings/subscription",
        json={"sub_profile_title": "", "sub_support_url": "", "sub_announce": ""},
        headers=CSRF,
    )
    assert res.json()["success"] is True
    data = spf_owner.get("/api/server/settings", headers=CSRF).json()["data"]
    assert data["sub_profile_title"] == ""
    assert data["sub_support_url"] == ""
    assert data["sub_announce"] == ""


def test_spf_page_renders_profile_and_omits_when_empty(spf_owner, spf_profile_settings):
    """The customer page carries the profile when set and drops it when cleared."""
    user_uuid = uuidlib.uuid4().hex
    db = SessionLocal()
    user = User(
        name=f"spf-{user_uuid[:8]}",
        uuid=user_uuid,
        expiry_date=dt.date.today() + dt.timedelta(days=30),
        total=None,
        used=0,
        is_active=True,
        owner="owner",
    )
    db.add(user)
    db.commit()
    try:
        res = spf_owner.put(
            "/api/server/settings/subscription",
            json=spf_profile_payload(sub_announce="Careful: <script>alert(1)</script>"),
            headers=CSRF,
        )
        assert res.json()["success"] is True, res.text

        page = spf_owner.get(f"/sub/{user_uuid}")
        assert page.status_code == 200, page.text
        html = page.text
        assert _TITLE in html, "profile title must replace the brand name"
        assert f'href="{_SUPPORT}"' in html, "support link must be rendered as a link"
        assert 'id="announce-banner"' in html, "announcement renders only when set"
        assert "&lt;script&gt;" in html, "announcement is escaped"
        assert "<script>alert(1)</script>" not in html
        assert f"Refreshes every {_INTERVAL} hours" in html

        res = spf_owner.put(
            "/api/server/settings/subscription",
            json={"sub_profile_title": "", "sub_support_url": "", "sub_announce": ""},
            headers=CSRF,
        )
        assert res.json()["success"] is True, res.text

        page = spf_owner.get(f"/sub/{user_uuid}")
        assert page.status_code == 200, page.text
        html = page.text
        assert _TITLE not in html, "an empty title falls back to the plain brand name"
        assert "OVManager" in html
        assert 'id="announce-banner"' not in html, "no banner when the announcement is empty"
        assert 'id="support-link"' not in html, "no support link when it is empty"
        assert "javascript:" not in html
    finally:
        db.delete(db.merge(user))
        db.commit()
        db.close()


def test_spf_migration_v20_adds_profile_columns():
    """Step 20 adds the four columns to a database stamped at 19."""
    engine = create_engine("sqlite://")
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        Base.metadata.create_all(bind=engine)
        assert migrations.migrate(db) == SCHEMA_VERSION
        columns = {c["name"] for c in inspect(engine).get_columns("settings")}
        assert {"sub_profile_title", "sub_support_url", "sub_announce", "sub_update_interval_hours"} <= columns

        for name in ("sub_profile_title", "sub_support_url", "sub_announce", "sub_update_interval_hours"):
            db.execute(text(f"ALTER TABLE settings DROP COLUMN {name}"))
        db.execute(text("DELETE FROM schema_version"))
        db.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (19, 0, 'pre-v20')"))
        db.commit()

        assert migrations.migrate(db) == SCHEMA_VERSION
        columns = {c["name"] for c in inspect(engine).get_columns("settings")}
        assert {"sub_profile_title", "sub_support_url", "sub_announce", "sub_update_interval_hours"} <= columns
        assert verify_schema(db) == []
    finally:
        db.close()
        engine.dispose()
