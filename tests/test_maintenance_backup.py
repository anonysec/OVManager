# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Backup/restore coverage for backend/routers/maintenance.py.

- Create/list/download hit the real BACKUP_DIR (files only, DB untouched).
- All rejection paths (bad extension, traversal, missing file, garbage DB)
  are exercised without touching the live database.
- The full round-trip (backup → mutate → restore → verify) runs against a
  scratch SQLite file with patched module globals, so the dev database is
  never swapped out from under the rest of the suite.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import backend.routers.maintenance as m
from backend.app import _run_migrations, api
from backend.config import config


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    _run_migrations()
    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def test_backup_create_list_download_roundtrip():
    before = {p.name for p in m.BACKUP_DIR.glob("ovmanager_backup_*.db")} if m.BACKUP_DIR.exists() else set()
    with TestClient(api) as client:
        r = client.post("/api/maintenance/backup", headers=_owner_headers())
        assert r.status_code == 200 and r.json()["success"] is True
        name = r.json()["data"]["filename"]
        assert name not in before

        r = client.get("/api/maintenance/backup/list", headers=_owner_headers())
        names = [b["name"] for b in r.json()["data"]]
        assert name in names

        r = client.get("/api/maintenance/backup/download", headers=_owner_headers())
        assert r.status_code == 200
        assert len(r.content) > 0
        # A real SQLite file, not an error page.
        assert r.content[:6] == b"SQLite"


def test_restore_rejects_bad_extension_and_traversal():
    with TestClient(api) as client:
        h = _owner_headers()
        r = client.post("/api/maintenance/backup/restore", files={"file": ("evil.txt", b"nope")}, headers=h)
        assert r.status_code == 200 and r.json()["success"] is False

        r = client.post("/api/maintenance/backup/restore", data={"restore_from_server": "../../etc/passwd"}, headers=h)
        assert r.json()["success"] is False
        assert "Invalid backup path" in r.json()["msg"]

        r = client.post("/api/maintenance/backup/restore", data={"restore_from_server": "does-not-exist.db"}, headers=h)
        assert r.json()["success"] is False
        assert "not found" in r.json()["msg"]


def test_restore_rejects_garbage_sqlite(tmp_path):
    bad = tmp_path / "garbage.db"
    bad.write_bytes(b"this is not a database")
    with TestClient(api) as client, open(bad, "rb") as fh:
        r = client.post("/api/maintenance/backup/restore", files={"file": ("garbage.db", fh)}, headers=_owner_headers())
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert "Invalid SQLite" in r.json()["msg"]


def test_backup_restore_roundtrip_on_scratch_db(monkeypatch, tmp_path):
    """Full cycle on an isolated SQLite file: backup → mutate → restore."""
    scratch = tmp_path / "live.db"
    conn = sqlite3.connect(str(scratch))
    conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO probe (v) VALUES ('before')")
    conn.commit()
    conn.close()

    fake_engine = create_engine(f"sqlite:///{scratch}")
    fake_backups = tmp_path / "backups"
    monkeypatch.setattr(m, "DB_PATH", scratch)
    monkeypatch.setattr(m, "BACKUP_DIR", fake_backups)
    monkeypatch.setattr(m, "engine", fake_engine)
    try:
        with TestClient(api) as client:
            h = _owner_headers()
            r = client.post("/api/maintenance/backup", headers=h)
            assert r.json()["success"] is True
            snap = r.json()["data"]["filename"]

            # Mutate after the snapshot, then restore and verify rollback.
            conn = sqlite3.connect(str(scratch))
            conn.execute("INSERT INTO probe (v) VALUES ('after')")
            conn.commit()
            conn.close()

            r = client.post("/api/maintenance/backup/restore", data={"restore_from_server": snap}, headers=h)
            assert r.json()["success"] is True, r.json()

            conn = sqlite3.connect(str(scratch))
            try:
                rows = [row[0] for row in conn.execute("SELECT v FROM probe ORDER BY id").fetchall()]
            finally:
                conn.close()
            assert rows == ["before"]
            # Safety net kept: pre-restore backup exists.
            assert any(p.name.startswith("pre_restore_backup_") for p in fake_backups.glob("*.db"))
    finally:
        fake_engine.dispose()


def test_safe_filename_allowlists_and_rejects():
    from backend.routers.maintenance import _safe_filename

    assert _safe_filename("backup.db") == "backup.db"
    assert _safe_filename("my backup 2026.db") == "mybackup2026.db"
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("..\\windows\\x.db") == "x.db"
    assert _safe_filename("") == ""
    assert _safe_filename(None) == ""
    assert _safe_filename("...") == ""
    assert _safe_filename("a\x00b.db") == "ab.db"
