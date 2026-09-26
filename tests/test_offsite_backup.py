"""Tests for the offsite backup copy (rsync/scp push of scheduled backups).

Every test/fixture is named ``ob_*`` so this module cannot collide with
another suite. The push is fully mocked at the subprocess boundary; the
settings roundtrip uses the same style as test_auto_backup.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as _text

import backend.app as app_module
from backend.db.engine import SessionLocal
from backend.db.models import Settings
from backend.operations import offsite_backup as ob
from backend.operations.offsite_backup import InvalidTarget, parse_target, push_offsite


def test_ob_parse_target_accepts_user_host_path():
    assert parse_target("backup@server:/backups/panel") == ("backup", "server", "/backups/panel")


def test_ob_parse_target_without_user():
    assert parse_target("server:/backups") == ("", "server", "/backups")


def test_ob_parse_target_strips_whitespace():
    assert parse_target("  user@host:/a/b  ") == ("user", "host", "/a/b")


def test_ob_parse_target_dotted_hosts_and_paths():
    assert parse_target("ops@srv01.example.com:/mnt/disk1/ov-backups.d") == (
        "ops",
        "srv01.example.com",
        "/mnt/disk1/ov-backups.d",
    )


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        "no-colon-at-all",
        "host:relative/path",
        "user@:/path",
        "host:",
        "user@host:/path with spaces",
        "user@host:/path;rm -rf",
        "user@host:/path$(boom)",
        "user@host:/pa|th",
        "user@host:/pa`th`",
        "user@ho&st:/path",
        "user@host:/path\n/evil",
    ],
)
def test_ob_parse_target_rejects_garbage(bad):
    with pytest.raises(InvalidTarget):
        parse_target(bad)


@pytest.fixture()
def ob_backup(tmp_path):
    p = tmp_path / "ovmanager_backup_20260918_030000.db"
    p.write_bytes(b"sqlite")
    return p


class ob_FakeRun:
    """Records subprocess.run calls and returns scripted results."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        rc, err = self.script.pop(0)
        import subprocess

        if rc == "timeout":
            raise subprocess.TimeoutExpired(argv, 300)
        if rc == "missing":
            raise FileNotFoundError(argv[0])
        import types

        res = types.SimpleNamespace(returncode=rc, stderr=err.encode() if err else b"")
        return res


@pytest.fixture()
def ob_no_rsync(monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: None if name == "rsync" else f"/usr/bin/{name}")


def test_ob_push_via_rsync_success(ob_backup, monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: "/usr/bin/rsync" if name == "rsync" else None)
    fake = ob_FakeRun([(0, "")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "backup@server:/backups/panel") is True
    assert len(fake.calls) == 1
    argv = fake.calls[0]["argv"]
    assert argv[0] == "/usr/bin/rsync"
    assert str(ob_backup) in argv
    assert argv[-1] == "backup@server:/backups/panel/"


def test_ob_push_falls_back_to_scp_when_rsync_missing(ob_backup, monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: None)
    fake = ob_FakeRun([(0, "")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "server:/backups") is True
    assert len(fake.calls) == 1
    assert fake.calls[0]["argv"][0] == "scp"


def test_ob_push_falls_back_to_scp_when_rsync_fails(ob_backup, monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: "/usr/bin/rsync")
    fake = ob_FakeRun([(255, "connection refused"), (0, "")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "backup@server:/backups") is True
    assert [c["argv"][0] for c in fake.calls] == ["/usr/bin/rsync", "scp"]


def test_ob_push_returns_false_when_every_tool_fails(ob_backup, monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: "/usr/bin/rsync" if name == "rsync" else None)
    fake = ob_FakeRun([(1, "permission denied"), (255, "ssh: connect failed")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "backup@server:/backups") is False
    assert len(fake.calls) == 2


def test_ob_push_never_raises_on_timeout(ob_backup, monkeypatch):
    monkeypatch.setattr(ob, "which", lambda name: None)
    fake = ob_FakeRun([("timeout", "")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "server:/backups") is False
    assert len(fake.calls) == 1
    assert fake.calls[0].get("timeout") == ob.PUSH_TIMEOUT_SECONDS


def test_ob_push_rejects_invalid_target_without_running(ob_backup, monkeypatch):
    def ob_boom(*args, **kwargs):
        raise AssertionError("subprocess must not run for an invalid target")

    monkeypatch.setattr(ob.subprocess, "run", ob_boom)
    assert push_offsite(ob_backup, "not a target") is False


def test_ob_push_skips_missing_file(monkeypatch):
    def ob_boom(*args, **kwargs):
        raise AssertionError("subprocess must not run for a missing file")

    monkeypatch.setattr(ob.subprocess, "run", ob_boom)
    assert push_offsite(Path("/nonexistent/backup.db"), "server:/backups") is False


def test_ob_push_uses_batch_mode_ssh(ob_backup, monkeypatch):
    """A hung password prompt must be impossible: BatchMode is always on."""
    monkeypatch.setattr(ob, "which", lambda name: "/usr/bin/rsync" if name == "rsync" else None)
    fake = ob_FakeRun([(0, "")])
    monkeypatch.setattr(ob.subprocess, "run", fake)
    assert push_offsite(ob_backup, "backup@server:/backups") is True
    argv = fake.calls[0]["argv"]
    assert any("BatchMode=yes" in part for part in argv)
    assert fake.calls[0]["capture_output"] is True


@pytest.fixture()
def ob_client():
    from backend.auth.authz import require_owner

    app_module.api.dependency_overrides[require_owner] = lambda: "owner"
    client = TestClient(app_module.api)
    try:
        yield client
    finally:
        app_module.api.dependency_overrides.pop(require_owner, None)


@pytest.fixture(autouse=True)
def ob_preserve_settings():
    """Snapshot/restore the offsite target on the shared dev DB."""
    db = SessionLocal()
    try:
        row = db.query(Settings).first()
        before = getattr(row, "offsite_backup_target", None)
    finally:
        db.close()
    try:
        yield
    finally:
        db = SessionLocal()
        try:
            row = db.query(Settings).first()
            row.offsite_backup_target = before
            db.commit()
        finally:
            db.close()


def test_ob_settings_roundtrip_and_validation(ob_client):
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    try:
        res = ob_client.put(
            "/api/server/settings/bot",
            json={"offsite_backup_target": "backup@server.example:/backups/panel"},
            headers=csrf,
        )
        assert res.status_code == 200 and res.json()["success"] is True
        assert res.json()["data"]["offsite_backup_target"] == "backup@server.example:/backups/panel"

        data = ob_client.get("/api/server/settings").json()["data"]
        assert data["offsite_backup_target"] == "backup@server.example:/backups/panel"

        res = ob_client.put("/api/server/settings/bot", json={"offsite_backup_target": ""}, headers=csrf)
        assert res.json()["success"] is True
        assert res.json()["data"]["offsite_backup_target"] == ""
        data = ob_client.get("/api/server/settings").json()["data"]
        assert data["offsite_backup_target"] == ""
    finally:
        db = SessionLocal()
        try:
            row = db.query(Settings).first()
            row.offsite_backup_target = None
            db.commit()
        finally:
            db.close()

    for bad in ("no-colon", "host:relative/path", "user@:/path", "user@host:/pa;th"):
        res = ob_client.put("/api/server/settings/bot", json={"offsite_backup_target": bad}, headers=csrf)
        assert res.status_code == 200, res.text
        assert res.json()["success"] is False
        assert "target" in res.json()["msg"].lower()


def test_ob_scheduled_job_pushes_newest_backup(monkeypatch, tmp_path):
    """auto_backup_job audits a successful offsite push."""
    import asyncio

    calls = []

    def ob_spy_create(*args, **kwargs):
        p = Path("/tmp/ob_fake_backup.db")
        calls.append(("create", p))
        return p

    def ob_spy_push(path, target):
        calls.append(("push", path, target))
        return True

    monkeypatch.setattr(app_module, "create_panel_backup", ob_spy_create, raising=False)
    import backend.routers.maintenance as maintenance

    monkeypatch.setattr(maintenance, "create_panel_backup", ob_spy_create)
    import backend.operations.offsite_backup as ob_module

    monkeypatch.setattr(ob_module, "push_offsite", ob_spy_push)

    db = SessionLocal()
    try:
        row = db.query(Settings).first()
        row.auto_backup_enabled = True
        row.auto_backup_time = "03:30"
        row.auto_backup_keep = 50
        row.offsite_backup_target = "backup@server:/backups"
        db.commit()
    finally:
        db.close()

    before_id = db_audit_max()
    try:
        asyncio.run(app_module.auto_backup_job())
        assert ("push", Path("/tmp/ob_fake_backup.db"), "backup@server:/backups") in calls
        db = SessionLocal()
        try:
            row = db.execute(
                _text(
                    "SELECT detail FROM audit_logs"
                    " WHERE action = 'maintenance.offsite_backup' AND id > :i"
                    " ORDER BY id DESC LIMIT 1"
                ),
                {"i": before_id},
            ).fetchone()
        finally:
            db.close()
        assert row is not None and "ob_fake_backup.db" in row[0]
    finally:
        db = SessionLocal()
        try:
            db.execute(_text("DELETE FROM audit_logs WHERE action = 'maintenance.offsite_backup' AND id > :i"), {"i": before_id})
            row = db.query(Settings).first()
            row.offsite_backup_target = None
            db.commit()
        finally:
            db.close()


def db_audit_max() -> int:
    db = SessionLocal()
    try:
        return int(db.execute(_text("SELECT COALESCE(MAX(id), 0) FROM audit_logs")).scalar() or 0)
    finally:
        db.close()
