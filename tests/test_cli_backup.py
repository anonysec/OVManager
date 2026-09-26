# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Hermetic tests for the backup operator CLI (no root, no real DB)."""

import json
import sys
from pathlib import Path

import cli.backup as backup
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
    assert "Verified backup" in backup.render_backup_text(data)
    assert json.loads(backup.render_backup_json(data))["path"] == str(fake_path)


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
    assert backup.render_backup_text(data).startswith("  Error:")


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
    assert backup.render_auto_backup_text(data).startswith("  Error:")


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
        assert json.loads(backup.render_auto_backup_json(preserved))["enabled"] is True

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
    assert "Verified backup" in capsys.readouterr().out

    rc = main(["--install-dir", str(tmp_path / "opt"), "--json", "backup", "--keep", "5"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

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
    assert "Error" in capsys.readouterr().out

    rc = main(["--install-dir", str(tmp_path / "opt"), "--json", "auto-backup", "status"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
