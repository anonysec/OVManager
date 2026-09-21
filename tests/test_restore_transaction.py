# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

import backend.routers.maintenance as maintenance


def _db(path: Path, value: str) -> None:
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


def test_restore_refuses_activation_when_safety_backup_fails(monkeypatch, tmp_path):
    live = tmp_path / "live.db"
    source = tmp_path / "source.db"
    backups = tmp_path / "backups"
    _db(live, "live")
    _db(source, "candidate")
    fake_engine = create_engine(f"sqlite:///{live}")

    monkeypatch.setattr(maintenance, "DB_DIR", tmp_path)
    monkeypatch.setattr(maintenance, "DB_PATH", live)
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backups)
    monkeypatch.setattr(maintenance, "engine", fake_engine)
    monkeypatch.setattr(maintenance, "_create_panel_backup_unlocked", lambda *args, **kwargs: None)

    def stage(src):
        candidate = tmp_path / ".candidate.db"
        shutil.copy2(src, candidate)
        return candidate

    monkeypatch.setattr(maintenance, "_stage_restore_candidate", stage)
    result = maintenance._atomic_db_restore(source, {"username": "owner"}, "test")
    assert result.success is False
    assert result.data["data_safe"] is True
    assert result.data["rolled_back"] is False
    assert "safety backup" in result.msg
    assert _value(live) == "live"
    fake_engine.dispose()


def test_restore_activates_only_staged_candidate(monkeypatch, tmp_path):
    live = tmp_path / "live.db"
    source = tmp_path / "source.db"
    backups = tmp_path / "backups"
    _db(live, "live")
    _db(source, "candidate")
    fake_engine = create_engine(f"sqlite:///{live}")

    monkeypatch.setattr(maintenance, "DB_DIR", tmp_path)
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
    result = maintenance._atomic_db_restore(source, {"username": "owner"}, "test")
    assert result.success is True
    assert result.data["rolled_back"] is False
    assert result.data["safety_backup"].startswith("ovmanager-pre-restore-")
    assert _value(live) == "staged-and-checked"
    fake_engine.dispose()
