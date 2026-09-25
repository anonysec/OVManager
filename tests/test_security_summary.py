# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Security summary: policy rejects must not be presented as auth failures.

The owner saw a scary "13 auth errors" that were really a disabled test user
reconnecting. These tests pin the split, the per-event context (node, user,
timestamp, ongoing) and the old-node fallback.
"""

import time
import uuid as _uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.auth.sessions import create_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal
from backend.routers import security as security_router
from backend.schema._input import CreateUser, NodeCreate


def _owner():
    _run_migrations()
    db = SessionLocal()
    try:
        return create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()


def _make_node():
    db = SessionLocal()
    try:
        return crud.create_node(
            db,
            NodeCreate(
                name=f"secnode_{_uuid.uuid4().hex[:8]}",
                address="203.0.113.91",
                key="test-api-key-12345678",
            ),
            None,
        )
    finally:
        db.close()


def _make_user(name: str):
    db = SessionLocal()
    try:
        return crud.create_user(db, CreateUser(name=name), config.ADMIN_USERNAME)
    finally:
        db.close()


class _FakeSessions:
    def __init__(self, payload):
        self.payload = payload

    def get_sessions(self, common_name, hours=8):
        return self.payload


def _patch_node(monkeypatch, payload, node_id):
    """Answer only for the node under test; other suite nodes stay quiet."""
    sessions = _FakeSessions(payload)

    def _client_for(node, **kw):
        if getattr(node, "id", None) == node_id:
            return sessions
        return _FakeSessions({})

    monkeypatch.setattr(security_router, "node_client", _client_for)


def _client():
    return TestClient(api)


def test_disabled_user_rejects_are_informational_not_danger(monkeypatch):
    node = _make_node()
    user = _make_user(f"secpol_{_uuid.uuid4().hex[:6]}")
    now = time.time()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 0,
            "policy_rejects": 3,
            "warn_rejects": 0,
            "rejects": 3,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": now - 120,
                    "cn": str(user.id),
                    "action": "disabled",
                    "severity": "policy",
                    "reason": "user disabled in the panel",
                    "peer": "",
                }
            ]
            * 3,
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["auth_failures"] == 0
    assert data["policy_rejects"] == 3
    assert data["ongoing_users"] == [user.name]
    ev = data["events"][0]
    assert ev["node"] == node.name
    assert ev["user"] == user.name
    assert ev["severity"] == "policy"
    assert ev["ongoing"] is True
    assert ev["time_local"]
    row = next(r for r in data["per_node"] if r["node"] == node.name)
    assert row["ongoing"] == 3
    assert row["policy_rejects"] == 3
    assert row["auth_failures"] == 0


def test_tls_failure_is_the_only_danger_bucket(monkeypatch):
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 2,
            "policy_rejects": 1,
            "warn_rejects": 0,
            "rejects": 1,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": time.time() - 7200,
                    "cn": "",
                    "action": "tls",
                    "severity": "failure",
                    "reason": "incoming packet authentication failed",
                    "peer": "9.9.9.9:1194",
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    assert data["auth_failures"] == 2
    assert data["auth_errors"] == 2  # back-compat alias
    assert data["policy_rejects"] == 1
    ev = data["events"][0]
    assert ev["severity"] == "failure"
    assert ev["peer"] == "9.9.9.9:1194"
    # Two hours old: not being retried right now.
    assert ev["ongoing"] is False
    assert data["ongoing_users"] == []


def test_legacy_node_without_events_is_classified_by_the_panel(monkeypatch):
    """A 1.0.0 node counts every reject as an auth error. The panel re-reads
    the text so a disabled user does not raise the danger counter."""
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            # What the old node reports: 143 rejects, all counted as errors.
            "auth_errors": 143,
            "rejects": 143,
            "stale_marker_count": 0,
            "live_count": 0,
            "last_error": {"1": "CN=1 ip=1.2.3.4:5000 limit=1 active=2; REJECT"},
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    assert data["auth_failures"] == 0
    assert data["policy_rejects"] == 143
    assert node.name in data["unclassified_nodes"]
    ev = data["events"][0]
    assert ev["severity"] == "policy"
    assert ev["node"] == node.name
    assert ev["classified"] is False


def test_legacy_node_reports_fail_closed_as_danger(monkeypatch):
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 2,
            "rejects": 2,
            "stale_marker_count": 0,
            "live_count": 0,
            "last_error": {
                "8": "CN=8 USERS_DIR missing or not a directory — fail-closed; REJECT"
            },
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    assert data["auth_failures"] == 1
    assert data["policy_rejects"] == 1
    assert data["events"][0]["severity"] == "failure"


def test_legacy_event_marks_unknown_identity(monkeypatch):
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "rejects": 1,
            "stale_marker_count": 0,
            "live_count": 0,
            # u1 was my deleted integration-test identity, not a panel user.
            "last_error": {"u1": "CN=u1 ip=9.9.9.9:1194 limit=1 active=2; REJECT"},
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    ev = resp.json()["data"]["events"][0]
    assert ev["user"] == "u1"
    assert ev["user_known"] is False


def test_undated_event_is_not_marked_ongoing(monkeypatch):
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "policy_rejects": 0,
            "warn_rejects": 0,
            "rejects": 0,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": 0,
                    "cn": "9",
                    "action": "disabled",
                    "severity": "policy",
                    "reason": "user disabled in the panel",
                    "peer": "",
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    ev = data["events"][0]
    assert ev["ts"] == 0
    assert ev["time_local"] is None
    assert ev["ongoing"] is False


def test_event_time_is_rendered_in_the_panel_timezone(monkeypatch):
    node = _make_node()
    ts = datetime(2026, 9, 25, 12, 0, tzinfo=UTC).timestamp()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "policy_rejects": 0,
            "warn_rejects": 0,
            "rejects": 0,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": ts,
                    "cn": "",
                    "action": "tls",
                    "severity": "failure",
                    "reason": "TLS Error",
                    "peer": "1.1.1.1:1194",
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    ev = data["events"][0]
    assert ev["time_local"]
    assert ev["time_local"].startswith(datetime.fromtimestamp(ts, UTC).astimezone().strftime("%Y-%m-%d"))


def test_strict_max_login_line_is_policy_not_unclassified(monkeypatch):
    """The hook's strict-reject line says "limit=2", not "max login reached"."""
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 7,
            "rejects": 7,
            "stale_marker_count": 0,
            "live_count": 0,
            "last_error": {
                "3": "CN=3 ip=1.2.3.4:5000 pool=10.8.0.3 limit=2 active=2 status=2; REJECT"
            },
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    assert data["auth_failures"] == 0
    assert data["warn_events"] == 0
    assert data["policy_rejects"] == 7
    assert data["events"][0]["action"] == "max_logins"


def test_classified_event_keeps_unknown_identity_visible(monkeypatch):
    """A node that still reports CNs for dropped users must not render blank."""
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "policy_rejects": 0,
            "warn_rejects": 0,
            "rejects": 1,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": time.time() - 30,
                    "cn": "u1",
                    "action": "disabled",
                    "severity": "policy",
                    "reason": "user disabled in the panel",
                    "peer": "",
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    ev = resp.json()["data"]["events"][0]
    assert ev["user"] == "u1"
    assert ev["user_known"] is False
    assert ev["classified"] is True


def test_tls_event_without_identity_shows_its_peer(monkeypatch):
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "policy_rejects": 0,
            "warn_rejects": 0,
            "rejects": 0,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    "ts": time.time() - 30,
                    "cn": "",
                    "action": "tls",
                    "severity": "failure",
                    "reason": "tls-crypt unwrapping failed",
                    "peer": "185.200.116.40:45929",
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    ev = resp.json()["data"]["events"][0]
    assert ev["user"] == "185.200.116.40:45929"
    assert ev["peer"] == "185.200.116.40:45929"
    # No identity to label: null, not "no such user" (that is for a CN the
    # panel used to know).
    assert ev["user_known"] is None


def test_node_ongoing_flag_wins_over_the_panel_clock(monkeypatch):
    """Log-derived events carry a node-computed ongoing flag: the panel must
    not override it with its own timestamp heuristic."""
    node = _make_node()
    _patch_node(
        monkeypatch,
        {
            "auth_errors": 1,
            "policy_rejects": 0,
            "warn_rejects": 0,
            "rejects": 0,
            "stale_marker_count": 0,
            "live_count": 0,
            "events": [
                {
                    # Two hours old, so the panel rule would say "not ongoing".
                    "ts": time.time() - 7200,
                    "cn": "",
                    "action": "tls",
                    "severity": "failure",
                    "reason": "tls-crypt unwrapping failed",
                    "peer": "10.0.0.9:1194",
                    "ongoing": True,
                }
            ],
        },
        node.id,
    )

    resp = _client().get(
        "/api/security/summary?hours=8",
        headers={"Authorization": f"Bearer {_owner()}"},
    )
    data = resp.json()["data"]
    assert data["events"][0]["ongoing"] is True
    assert data["ongoing_users"] == ["10.0.0.9:1194"]
