# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Abuse-surface regression tests: the API must never become a file reader
or a shell. Only the owner reaches sensitive endpoints (over SSH for the
terminal); every byte the API touches is validated before use."""

import io
import tarfile

import pytest
from fastapi.testclient import TestClient

from backend.app import _run_migrations, api
from backend.config import config


def _ensure_schema():
    _run_migrations()
    from backend.db.engine import SessionLocal
    from backend.operations.audit import ensure_audit_table

    db = SessionLocal()
    try:
        ensure_audit_table(db)
    finally:
        db.close()


def _owner_headers():
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        token = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_offsite_target_rejects_shell_metacharacters():
    from backend.operations.offsite_backup import InvalidTarget, parse_target

    assert parse_target("backup@server:/backups/panel") == ("backup", "server", "/backups/panel")
    for evil in (
        "backup@server:/backups; rm -rf /",
        "backup@server:/backups && id",
        "backup@server:/backups | tee /tmp/x",
        "backup@server:/backups $(id)",
        "backup@server:/backups `id`",
        "backup@server:/backups\nsh",
        "backup@server:relative/path",
        "backup@server:C:\\windows",
        "-oProxyCommand=evil server:/x",
        " server : /with spaces ",
    ):
        with pytest.raises(InvalidTarget):
            parse_target(evil)


def test_restore_upload_traversal_writes_nothing_outside(monkeypatch, tmp_path):
    _ensure_schema()
    from backend.routers import maintenance

    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    client = TestClient(api)
    owner = _owner_headers()

    for filename in ("../../evil.db", "/abs/evil.db", "..\\evil.db", "sub/../../evil.db"):
        resp = client.post(
            "/api/maintenance/backup/restore",
            files={"file": (filename, b"not a database", "application/octet-stream")},
            headers=owner,
        )
        # Rejected as invalid, or fails later as a non-bundle — but never as
        # a file written outside the backup dir.
        assert resp.status_code in (200, 400, 422), resp.text
    assert list(tmp_path.rglob("evil.db")) == []
    assert (tmp_path / "abs").exists() is False


def test_tls_renew_rejects_malicious_domains_without_executing(monkeypatch):
    _ensure_schema()
    import backend.routers.tls as tls_router

    calls = []
    monkeypatch.setattr(tls_router, "_run_acme", lambda args, timeout: calls.append(args))
    client = TestClient(api)
    owner = _owner_headers()

    for evil in ("example.com; rm -rf /", "example.com$(id)", "exa mple.com", "a" * 300 + ".com", "-dfoo.com"):
        resp = client.post("/api/tls/renew", json={"domain": evil}, headers=owner)
        assert resp.json()["success"] is False, evil
    assert calls == []


def test_bundle_extract_rejects_zipslip_member_names(tmp_path):
    from backend.operations import backup_bundle as bb

    evil = tmp_path / "evil.ovmbak"
    with tarfile.open(evil, "w:gz") as tf:
        for name in ("../../evil.db", "/abs/evil.db", "panel.db"):
            data = b"data-" + name.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    out = tmp_path / "out.db"
    with pytest.raises(bb.BackupBundleError):
        bb.extract_database(evil, out)
    assert not out.exists()
    assert not (tmp_path / "evil.db").exists()
    assert not (tmp_path / "abs").exists()


def test_spawn_detached_never_uses_a_shell(monkeypatch):
    import backend.routers.tls as tls_router

    seen = []

    class _DummyProc:
        pass

    monkeypatch.setattr(
        tls_router.subprocess, "Popen", lambda *a, **k: seen.append((a, k)) or _DummyProc()
    )

    tls_router._spawn_detached(["systemctl", "restart", "ovmanager"])
    assert len(seen) == 1
    (args, kwargs) = seen[0]
    assert kwargs.get("shell", False) is not True
    joined = " ".join(args[0])
    assert "systemctl" in joined and "restart" in joined and "ovmanager" in joined
