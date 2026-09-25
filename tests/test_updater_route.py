# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for backend/routers/updater.py (owner-only update check + one-click update).

The router is not registered in backend/routers/__init__.py yet (the
coordinating agent owns that), so the tests mount it on a dedicated app.
GitHub is never called: ``updater.requests.get`` is replaced with a fake, and
Popen is replaced with a recorder so no installer ever runs.

These tests share the dev SQLite database with the rest of the suite, so every
row uses a unique ``upd_`` name and is deleted in a ``finally`` block.
"""

import time
import uuid

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import config
from backend.routers import updater
from backend.routers.updater import router as updater_router
from backend.version import __version__

_app = FastAPI()
_app.include_router(updater_router, prefix="/api")


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _client() -> TestClient:
    return TestClient(_app)


def _headers(username: str, role: str) -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        raw = create_session(db, username, role)
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _owner_headers() -> dict:
    return _headers(config.ADMIN_USERNAME, "owner")


def _create_admin(username: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema import AdminCreate

    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def _cleanup_admin(username: str) -> None:
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


@pytest.fixture(autouse=True)
def _reset_updater_cache(monkeypatch):
    """Each test starts with a cold cache so fetches are observable."""
    monkeypatch.setattr(updater, "_cache", {"ts": 0.0, "latest": None, "source": "unknown", "note": ""})


def _fake_github(monkeypatch, *, release=None, tags=None, error=None):
    """Replace the HTTP layer. Returns the list of requested URLs.

    ``release``/``tags`` are ``(status_code, payload)`` tuples or None to 404.
    ``error`` (an exception) is raised for every call instead.
    """
    calls = []

    def fake_get(url, timeout=None, headers=None):
        calls.append({"url": url, "timeout": timeout})
        if error is not None:
            raise error
        if url.endswith("/releases/latest") and release is not None:
            return _FakeResponse(*release)
        if url.endswith("/tags") and tags is not None:
            return _FakeResponse(*tags)
        return _FakeResponse(404, None)

    monkeypatch.setattr(updater.requests, "get", fake_get)
    return calls


# ── /status ────────────────────────────────────────────────────────────────


def test_status_available_reports_newer_tag(monkeypatch):
    monkeypatch.setenv("OVM_REPO", "upd-owner/upd-repo")
    calls = _fake_github(monkeypatch, release=(200, {"tag_name": "v9.9.9"}), tags=(200, [{"name": "v9.9.9"}]))

    resp = _client().get("/api/updater/status", headers=_owner_headers())
    assert resp.status_code == 200

    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["current"] == __version__
    assert data["latest"] == "v9.9.9"
    assert data["update_available"] is True
    assert data["source"] == "github"
    assert isinstance(data["checked_at"], int) and data["checked_at"] > 0
    # The OVM_REPO override must reach the URL, and the request must be bounded.
    assert "upd-owner/upd-repo" in calls[0]["url"]
    assert calls[0]["timeout"] == 5.0


def test_status_uses_tags_fallback_and_reports_no_update(monkeypatch):
    calls = _fake_github(monkeypatch, release=(404, None), tags=(200, [{"name": "v0.0.1"}]))

    resp = _client().get("/api/updater/status", headers=_owner_headers())
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["latest"] == "v0.0.1"
    assert data["update_available"] is False
    assert data["source"] == "github"
    assert data.get("note", "") == ""
    assert any(c["url"].endswith("/tags") for c in calls)


def test_status_equal_version_is_not_an_update(monkeypatch):
    _fake_github(monkeypatch, release=(200, {"tag_name": f"v{__version__}"}))

    resp = _client().get("/api/updater/status", headers=_owner_headers())
    assert resp.status_code == 200
    assert resp.json()["data"]["update_available"] is False


def test_status_fails_soft_on_network_error(monkeypatch):
    _fake_github(monkeypatch, error=requests.exceptions.ConnectionError("no dns"))

    resp = _client().get("/api/updater/status", headers=_owner_headers())
    assert resp.status_code == 200

    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["latest"] is None
    assert data["source"] == "unknown"
    assert data["update_available"] is False
    assert body["msg"]
    assert data["note"]


def test_status_caches_result_for_one_hour(monkeypatch):
    calls = _fake_github(monkeypatch, release=(200, {"tag_name": "v9.9.9"}))

    client = _client()
    first = client.get("/api/updater/status", headers=_owner_headers())
    second = client.get("/api/updater/status", headers=_owner_headers())

    assert len(calls) == 1
    assert first.json()["data"]["checked_at"] == second.json()["data"]["checked_at"]


# ── version comparison ─────────────────────────────────────────────────────


def test_version_compare_handles_v_prefix_and_components():
    assert updater._is_newer("v2.1.0", "2.0.2") is True
    assert updater._is_newer("2.1.0", "v2.0.2") is True
    assert updater._is_newer("v2.0.10", "2.0.9") is True
    assert updater._is_newer("v2.0.2", "2.0.2") is False
    assert updater._is_newer("v1.9.9", "2.0.2") is False
    assert updater._is_newer("v2.0.2-rc1", "2.0.2") is False
    assert updater._is_newer(None, "2.0.2") is False
    assert updater._is_newer("nightly", "2.0.2") is False


# ── /run ───────────────────────────────────────────────────────────────────


class _PopenRecorder:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs


def _native_env(monkeypatch, tmp_path):
    install_sh = tmp_path / "install.sh"
    install_sh.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("OVM_APP_DIR", str(tmp_path))
    monkeypatch.setattr(updater, "_in_container", lambda: False)
    monkeypatch.setattr(updater, "_has_systemctl", lambda: True)
    monkeypatch.setattr(updater, "DATA_DIR", tmp_path)
    return install_sh


def test_run_native_detaches_exact_installer_argv(monkeypatch, tmp_path):
    install_sh = _native_env(monkeypatch, tmp_path)
    records = []

    def fake_popen(argv, **kwargs):
        records.append(_PopenRecorder(argv, **kwargs))
        return object()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    started = time.monotonic()
    resp = _client().post("/api/updater/run", headers=_owner_headers())
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert elapsed < 2.0  # never blocks on the installer

    assert len(records) == 1
    record = records[0]
    assert record.argv == ["bash", str(install_sh), "update"]
    assert record.kwargs["start_new_session"] is True
    assert record.kwargs["stdin"] == updater.subprocess.DEVNULL
    assert record.kwargs["stderr"] == updater.subprocess.STDOUT
    assert record.kwargs["stdout"].name == str(tmp_path / "update.log")
    assert (tmp_path / "update.log").exists()


def test_run_native_writes_audit_row_with_previous_version(monkeypatch, tmp_path):
    _native_env(monkeypatch, tmp_path)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda argv, **kwargs: object())

    resp = _client().post("/api/updater/run", headers=_owner_headers())
    assert resp.json()["success"] is True

    from backend.db.engine import SessionLocal
    from backend.operations.audit import recent_events

    db = SessionLocal()
    try:
        events = recent_events(db, limit=500, action="panel.update")
    finally:
        db.close()

    mine = [e for e in events if e["actor"] == config.ADMIN_USERNAME and str(tmp_path) in (e["detail"] or "")]
    assert mine, "expected a panel.update audit row for this run"
    assert __version__ in mine[0]["detail"]


def test_run_refuses_in_docker_with_host_command(monkeypatch, tmp_path):
    _native_env(monkeypatch, tmp_path)
    monkeypatch.setattr(updater, "_in_container", lambda: True)
    called = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: called.append(a))

    resp = _client().post("/api/updater/run", headers=_owner_headers())
    assert resp.status_code == 200

    body = resp.json()
    assert body["success"] is False
    assert updater._HOST_COMPOSE_CMD in body["msg"]
    assert updater._HOST_RESTART_CMD in body["msg"]
    assert called == []


def test_run_refuses_when_installer_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OVM_APP_DIR", str(tmp_path / "upd_absent"))
    monkeypatch.setattr(updater, "_in_container", lambda: False)
    monkeypatch.setattr(updater, "_has_systemctl", lambda: True)

    resp = _client().post("/api/updater/run", headers=_owner_headers())
    assert resp.status_code == 200

    body = resp.json()
    assert body["success"] is False
    assert updater._HOST_COMPOSE_CMD in body["msg"]
    assert updater._HOST_RESTART_CMD in body["msg"]


# ── access control ─────────────────────────────────────────────────────────


def test_update_operation_reports_persisted_phase(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(updater, "DATA_DIR", tmp_path)
    (tmp_path / "update-state.json").write_text(
        json.dumps({"phase": "verifying", "from_version": "1.2.7", "to_version": "1.2.8", "pid": 42})
    )
    (tmp_path / "update-maintenance").touch()
    response = _client().get("/api/updater/operation", headers=_owner_headers())
    assert response.status_code == 200
    assert response.json()["data"]["phase"] == "verifying"
    assert response.json()["data"]["maintenance"] is True
    assert response.json()["data"]["finished"] is False


def test_updater_endpoints_require_auth():
    client = _client()
    assert client.get("/api/updater/status").status_code == 401
    assert client.get("/api/updater/operation").status_code == 401
    assert client.post("/api/updater/run").status_code == 401


def test_updater_endpoints_are_owner_only():
    admin = f"upd_admin_{uuid.uuid4().hex[:8]}"
    _create_admin(admin)
    try:
        client = _client()
        headers = _headers(admin, "admin")
        assert client.get("/api/updater/status", headers=headers).status_code == 403
        assert client.get("/api/updater/operation", headers=headers).status_code == 403
        assert client.post("/api/updater/run", headers=headers).status_code == 403
    finally:
        _cleanup_admin(admin)
