# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Hermetic tests for the backup operator CLI (no root, no real DB)."""

import re
import shutil
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

import cli.backup as backup
import cli.restore as restore
from backend.operations.backup.bundle import extract_database
from cli.env import Install
from cli.main import main


def _install(tmp_path, env_lines=()):
    install_dir = tmp_path / "opt"
    install_dir.mkdir(exist_ok=True)
    env_path = install_dir / ".env"
    if not env_path.exists():
        env_path.write_text("PORT=2095\n", encoding="utf-8")
    for line in env_lines:
        with open(env_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return Install.detect(install_dir=str(install_dir), data_dir=str(data_dir))


def _tmp_session_factory(tmp_path, monkeypatch):
    """Point backend SessionLocal at an isolated SQLite file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import backend.db.engine as engine_mod

    db_file = tmp_path / "cli_backup_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    from backend.db.models import Settings

    Settings.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(engine_mod, "SessionLocal", factory)
    return engine, factory


def test_backup_now_success_with_stubbed_backend(monkeypatch, tmp_path):
    install = _install(tmp_path)
    fake_path = tmp_path / "data" / "ovmanager-backup-test.ovmbak"
    fake_path.write_text("fake", encoding="utf-8")

    import backend.routers.maintenance as maintenance

    calls = {}

    def _stub(keep=None):
        calls["keep"] = keep
        return fake_path

    monkeypatch.setattr(maintenance, "create_panel_backup", _stub)
    data = backup.backup_now(install, keep=5)
    assert data["ok"] is True
    assert data["path"] == str(fake_path)
    assert data["filename"] == fake_path.name
    assert data["keep"] == 5
    assert calls == {"keep": 5}
    assert "verified backup" in backup.render_backup_text(data)


def test_backup_now_default_keep_is_fourteen(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.routers.maintenance as maintenance

    seen = {}
    monkeypatch.setattr(maintenance, "create_panel_backup", lambda keep=None: (seen.update(keep=keep), Path("/tmp/x.ovmbak"))[1])
    data = backup.backup_now(install)
    assert data["ok"] is True
    assert seen["keep"] == 14


def test_backup_now_missing_database_reports_clean_error(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.routers.maintenance as maintenance

    monkeypatch.setattr(maintenance, "create_panel_backup", lambda keep=None: None)
    data = backup.backup_now(install, keep=7)
    assert data["ok"] is False
    assert "not found" in data["error"].lower()
    assert backup.render_backup_text(data).startswith("  ✗")


def test_backup_now_backend_failure_reports_clean_error(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.routers.maintenance as maintenance

    def _boom(keep=None):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(maintenance, "create_panel_backup", _boom)
    data = backup.backup_now(install)
    assert data["ok"] is False
    assert "disk on fire" in data["error"]


def test_backup_now_unimportable_backend_reports_clean_error(monkeypatch, tmp_path):
    install = _install(tmp_path)
    monkeypatch.setitem(sys.modules, "backend.routers.maintenance", None)
    data = backup.backup_now(install)
    assert data["ok"] is False
    assert "Backend" in data["error"]


def test_backup_now_rejects_bad_keep_and_missing_install(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.routers.maintenance as maintenance

    def _forbidden(*a, **k):
        raise AssertionError("backend must not run when keep is invalid")

    monkeypatch.setattr(maintenance, "create_panel_backup", _forbidden)
    for bad in ("0", "501", "abc", "-3", "14.5"):
        data = backup.backup_now(install, keep=bad)
        assert data["ok"] is False and "keep" in data["error"].lower(), bad
    missing = Install.detect(install_dir=str(tmp_path / "nope"), data_dir=str(tmp_path))
    data = backup.backup_now(missing)
    assert data["ok"] is False and "missing" in data["error"]


def test_auto_backup_time_validation_rejects_junk(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.db.engine as engine_mod

    def _forbidden(*a, **k):
        raise AssertionError("DB must not be touched when time is invalid")

    monkeypatch.setattr(engine_mod, "SessionLocal", _forbidden)
    for bad in ("24:00", "3:30", "03:60", "abc", "03:30:00", "", "99:99", "7:07", "12:5", "1:23"):
        data = backup.auto_backup("on", install, time=bad)
        assert data["ok"] is False, bad
        assert "time" in data["error"].lower(), bad
    assert backup.render_auto_backup_text(data).startswith("  ✗")


def test_auto_backup_keep_validation_rejects_junk(monkeypatch, tmp_path):
    install = _install(tmp_path)

    import backend.db.engine as engine_mod

    monkeypatch.setattr(engine_mod, "SessionLocal", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no DB")))
    for bad in ("0", "501", "abc", "-1"):
        data = backup.auto_backup("on", install, time="03:30", keep=bad)
        assert data["ok"] is False and "keep" in data["error"].lower(), bad


def test_auto_backup_unknown_action_rejected(monkeypatch, tmp_path):
    install = _install(tmp_path)
    data = backup.auto_backup("bogus", install)
    assert data["ok"] is False and "Usage" in data["error"]


def test_auto_backup_status_on_off_roundtrip_hermetic(monkeypatch, tmp_path):
    install = _install(tmp_path)
    engine, _factory = _tmp_session_factory(tmp_path, monkeypatch)

    try:
        current = backup.auto_backup("status", install)
        assert current == {"ok": True, "enabled": False, "time": "03:30", "keep": 50}

        enabled = backup.auto_backup("on", install, time="04:45", keep=12)
        assert enabled["ok"] is True and enabled["enabled"] is True
        assert enabled["time"] == "04:45" and enabled["keep"] == 12

        # On without flags preserves the stored schedule.
        preserved = backup.auto_backup("on", install)
        assert preserved["time"] == "04:45" and preserved["keep"] == 12

        text = backup.render_auto_backup_text(preserved)
        assert "enabled" in text and "04:45" in text

        disabled = backup.auto_backup("off", install)
        assert disabled["ok"] is True and disabled["enabled"] is False
        assert disabled["time"] == "04:45" and disabled["keep"] == 12

        final = backup.auto_backup("status", install)
        assert final["enabled"] is False
    finally:
        engine.dispose()


def test_main_dispatch_returns_correct_codes(monkeypatch, tmp_path, capsys):
    install = _install(tmp_path)

    import cli.main as cli_main

    monkeypatch.setattr(cli_main, "Install", type("I", (), {"detect": staticmethod(lambda **kw: install)}))

    import backend.routers.maintenance as maintenance

    monkeypatch.setattr(maintenance, "create_panel_backup", lambda keep=None: tmp_path / "b.ovmbak")
    rc = main(["--install-dir", str(tmp_path / "opt"), "backup", "--keep", "5"])
    assert rc == 0
    assert "verified backup" in capsys.readouterr().out

    def _none(keep=None):
        return None

    monkeypatch.setattr(maintenance, "create_panel_backup", _none)
    rc = main(["--install-dir", str(tmp_path / "opt"), "backup"])
    assert rc != 0

    _tmp_session_factory(tmp_path, monkeypatch)
    rc = main(["--install-dir", str(tmp_path / "opt"), "auto-backup", "status"])
    assert rc == 0
    assert "Auto backup" in capsys.readouterr().out

    rc = main(["--install-dir", str(tmp_path / "opt"), "auto-backup", "on", "--time", "02:15", "--keep", "9"])
    assert rc == 0

    rc = main(["--install-dir", str(tmp_path / "opt"), "auto-backup", "on", "--time", "junk"])
    assert rc != 0
    assert "HH:MM" in capsys.readouterr().out


# ── restore ────────────────────────────────────────────────────────────
# `ovm restore` puts a stored backup back. The transaction itself is the
# panel's (backend.routers.maintenance), so these tests pin the operator
# front end: the listing, the name handling, and the safety copy that makes a
# restore undoable. Everything runs against tmp_path — never the live box.


def _db(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE probe (value TEXT)")
    conn.execute("INSERT INTO probe VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _value(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM probe").fetchone()[0]
    finally:
        conn.close()


def _backup_dir(tmp_path, monkeypatch):
    import backend.routers.maintenance as maintenance

    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True)
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backups)
    return backups


def test_restore_without_a_name_lists_backups_with_dates_and_sizes(monkeypatch, tmp_path, capsys):
    """No name is the listing: names, dates and sizes, and nothing else."""
    install = _install(tmp_path)
    backups = _backup_dir(tmp_path, monkeypatch)
    older = backups / "ovmanager-backup-20260101_000000-v1.ovmbak"
    older.write_bytes(b"x" * 3000)
    newer = backups / "ovmanager-pre-restore-20260102_000000-v1.ovmbak"
    newer.write_bytes(b"y" * 10)

    data = restore.list_backups(install)
    assert data["ok"] is True, data
    assert [item["name"] for item in data["backups"]] == [newer.name, older.name]  # newest first

    text = restore.render_list_text(data)
    for name in (older.name, newer.name):
        assert name in text, text
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text), text
    assert "2.9 KB" in text and "10 B" in text, text
    assert "restore one with: ovm restore <name>" in text
    # A listing is a read: no file was added, moved or removed.
    assert sorted(item.name for item in backups.iterdir()) == sorted([older.name, newer.name])

    rc = main(["--install-dir", str(install.install_dir), "restore"])
    assert rc == 0
    out = capsys.readouterr().out
    assert older.name in out and newer.name in out


def test_restore_reports_no_backups_without_failing(monkeypatch, tmp_path, capsys):
    install = _install(tmp_path)
    backups = _backup_dir(tmp_path, monkeypatch)
    rc = main(["--install-dir", str(install.install_dir), "restore"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "none — create one with: ovm backup" in out
    assert "ovm backup" in out
    assert list(backups.iterdir()) == []


def test_restore_of_an_unknown_name_fails_without_restoring(monkeypatch, tmp_path, capsys):
    install = _install(tmp_path)
    _backup_dir(tmp_path, monkeypatch)
    import backend.routers.maintenance as maintenance

    def forbidden(*args, **kwargs):
        raise AssertionError("an unknown name must not reach the restore transaction")

    monkeypatch.setattr(maintenance, "_restore_artifact", forbidden)
    rc = main(["--install-dir", str(install.install_dir), "restore", "nope.ovmbak"])
    assert rc != 0
    assert "not found" in capsys.readouterr().out


def test_restore_refuses_a_path_instead_of_a_name(monkeypatch, tmp_path):
    """The name comes from the listing; a path must never be accepted."""
    install = _install(tmp_path)
    import backend.routers.maintenance as maintenance

    def forbidden(*args, **kwargs):
        raise AssertionError("the backend must not be asked to restore a path")

    monkeypatch.setattr(maintenance, "restore_stored_backup", forbidden)
    for bad in ("../ovmanager.db", "sub/backup.ovmbak", ".hidden", "", "a\\b.ovmbak"):
        data = restore.restore_backup(install, bad)
        assert data["ok"] is False, bad
        assert "Invalid" in data["error"], (bad, data)


def test_restore_refuses_when_the_panel_is_not_installed(monkeypatch, tmp_path):
    missing = Install.detect(install_dir=str(tmp_path / "nope"), data_dir=str(tmp_path / "data"))
    import backend.routers.maintenance as maintenance

    def forbidden(*args, **kwargs):
        raise AssertionError("nothing may be restored on a missing install")

    monkeypatch.setattr(maintenance, "restore_stored_backup", forbidden)
    data = restore.restore_backup(missing, "ovmanager-backup-20260101_000000-v1.ovmbak")
    assert data["ok"] is False and data["installed"] is False
    assert "missing" in data["error"]


def test_restore_takes_a_safety_backup_before_it_activates(monkeypatch, tmp_path):
    """A restore is undoable: the live database is copied first, and the copy
    is a real bundle — the operator restores it to get back."""
    install = _install(tmp_path)
    import backend.routers.maintenance as maintenance

    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True)
    live = tmp_path / "data" / "ovmanager.db"
    source = backups / "ovmanager-backup-20260101_000000.db"
    _db(live, "live")
    _db(source, "candidate")
    fake_engine = create_engine(f"sqlite:///{live}")
    monkeypatch.setattr(maintenance, "DB_DIR", tmp_path / "data")
    monkeypatch.setattr(maintenance, "DB_PATH", live)
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backups)
    monkeypatch.setattr(maintenance, "engine", fake_engine)
    monkeypatch.setattr(maintenance, "_apply_migrations_after_restore", lambda: None)
    monkeypatch.setattr(maintenance, "log_event", lambda *args, **kwargs: None)

    def stage(src):
        candidate = tmp_path / ".candidate.db"
        shutil.copy2(src, candidate)
        conn = sqlite3.connect(candidate)
        conn.execute("UPDATE probe SET value='staged-and-checked'")
        conn.commit()
        conn.close()
        return candidate

    monkeypatch.setattr(maintenance, "_stage_restore_candidate", stage)

    try:
        data = restore.restore_backup(install, source.name)
        assert data["ok"] is True, data
        assert data["safety_backup"].startswith("ovmanager-pre-restore-"), data

        # The restore landed...
        assert _value(live) == "staged-and-checked"
        # ...and the copy taken before it holds what was replaced.
        safety = backups / data["safety_backup"]
        assert safety.is_file(), data
        extracted = tmp_path / "safety-check.db"
        extract_database(safety, extracted)
        assert _value(extracted) == "live"
        assert "Safety copy" in restore.render_restore_text(data)
    finally:
        fake_engine.dispose()


def test_restore_reports_the_safety_copy_when_the_restore_fails(monkeypatch, tmp_path):
    install = _install(tmp_path)
    import backend.routers.maintenance as maintenance

    _backup_dir(tmp_path, monkeypatch)
    backup = tmp_path / "data" / "backups" / "ovmanager-backup-20260101_000000.db"
    backup.write_bytes(b"not a database")

    class Result:
        success = False
        msg = "Invalid SQLite database: file is not a database"
        data = {"safety_backup": "ovmanager-pre-restore-20260101_000001-v1.ovmbak", "rolled_back": True}

    monkeypatch.setattr(maintenance, "restore_stored_backup", lambda name, actor: Result())
    data = restore.restore_backup(install, backup.name)
    assert data["ok"] is False
    assert data["safety_backup"].startswith("ovmanager-pre-restore-")
    text = restore.render_restore_text(data)
    assert text.startswith("  ✗") and "Safety copy" in text
