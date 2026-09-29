# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for the mutating CLI account commands (hermetic, no root)."""

import os
import tempfile
from pathlib import Path as _Path

import cli.password as password
import cli.urlpath as urlpath
from cli.main import main


def _install(tmp_path, env="ADMIN_USERNAME=admin\n"):
    install_dir = tmp_path / "opt"
    install_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (install_dir / ".env").write_text(f"{env}DATA_DIR={data_dir}\n", encoding="utf-8")
    return str(install_dir)


def test_password_validate_rejects_policy_violations():
    assert password.validate("") == "must not be empty"
    assert password.validate("short") == "must be at least 8 characters (the panel requires >= 8)"
    assert password.validate("change-me-12345") == "looks like a placeholder — choose a strong password"
    assert password.validate("a\nbcd12345") == "must be a single line"
    assert password.validate("long-enough-password") is None


def test_reset_password_rejects_weak_without_touching_env(tmp_path):
    install_dir = _install(tmp_path)
    before = _Path(os.path.join(install_dir, ".env")).read_text(encoding="utf-8")
    out = password.reset_password(install_dir, "short")
    assert out["ok"] is False and "8 characters" in out["error"]
    assert _Path(os.path.join(install_dir, ".env")).read_text(encoding="utf-8") == before


def test_reset_password_missing_install(tmp_path):
    out = password.reset_password(str(tmp_path / "missing"), "long-enough-password")
    assert out["ok"] is False and "Not installed" in out["error"]


def test_reset_password_writes_the_hash_to_the_database(tmp_path, monkeypatch):
    """The credential goes to the owner's admins row, never to .env."""
    install_dir = _install(tmp_path)
    data_dir = str(tmp_path / "data")
    (tmp_path / "data" / "ovmanager.db").write_bytes(b"")
    before = _Path(os.path.join(install_dir, ".env")).read_text(encoding="utf-8")
    calls = {}
    monkeypatch.setattr(password, "hash_password", lambda p: "$2b$12$STUBHASH")

    def fake_write(data_dir_arg, hashed, owner):
        calls.update(data_dir=data_dir_arg, hashed=hashed, owner=owner)
        return {"ok": True}

    monkeypatch.setattr(password, "_write_owner_hash", fake_write)
    out = password.reset_password(install_dir, "long-enough-password", data_dir)
    assert out["ok"] is True and out["scope"] == "database"
    assert calls == {"data_dir": data_dir, "hashed": "$2b$12$STUBHASH", "owner": "admin"}
    assert _Path(os.path.join(install_dir, ".env")).read_text(encoding="utf-8") == before


def test_reset_password_refuses_when_the_database_is_absent(tmp_path, monkeypatch):
    install_dir = _install(tmp_path)
    monkeypatch.setattr(password, "hash_password", lambda p: "$2b$12$STUBHASH")
    out = password.reset_password(install_dir, "long-enough-password", str(tmp_path / "data"))
    assert out["ok"] is False and "not found" in out["error"]


def test_reset_password_reports_a_missing_data_dir(tmp_path, monkeypatch):
    """Without a data dir the CLI must say so, not guess at /var/lib/ovmanager."""
    install_dir = tmp_path / "opt"
    install_dir.mkdir()
    (install_dir / ".env").write_text("ADMIN_USERNAME=admin\n", encoding="utf-8")
    monkeypatch.setattr(password, "hash_password", lambda p: "$2b$12$STUBHASH")
    out = password.reset_password(str(install_dir), "long-enough-password")
    assert out["ok"] is False and "DATA_DIR" in out["error"]


def test_reset_urlpath_missing_install(tmp_path):
    out = urlpath.reset_urlpath(str(tmp_path / "missing"), str(tmp_path / "compose.yml"))
    assert out["ok"] is False and "Not installed" in out["error"]


def test_reset_urlpath_runs_panel_entrypoint(monkeypatch, tmp_path):
    install_dir = _install(tmp_path)
    calls = {}

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kw):
        calls["argv"] = argv
        calls["cwd"] = kw.get("cwd")
        return Done()

    monkeypatch.setattr(urlpath.subprocess, "run", fake_run)
    out = urlpath.reset_urlpath(install_dir, str(tmp_path / "compose-missing.yml"))
    assert out == {"ok": True}
    assert calls["argv"][-2:] == ["main.py", "--reset-urlpath"]
    assert calls["cwd"] == install_dir


def test_reset_urlpath_docker_uses_exec(monkeypatch, tmp_path):
    install_dir = _install(tmp_path)
    compose = tmp_path / "compose.yml"
    compose.write_text("x", encoding="utf-8")
    calls = {}

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kw):
        calls["argv"] = argv
        return Done()

    monkeypatch.setattr(urlpath.subprocess, "run", fake_run)
    out = urlpath.reset_urlpath(install_dir, str(compose))
    assert out == {"ok": True}
    assert calls["argv"][:2] == ["docker", "exec"]


def test_reset_urlpath_reports_failure(monkeypatch, tmp_path):
    install_dir = _install(tmp_path)

    class Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(urlpath.subprocess, "run", lambda *a, **k: Bad())
    out = urlpath.reset_urlpath(install_dir, str(tmp_path / "compose-missing.yml"))
    assert out["ok"] is False and "boom" in out["error"]


def test_main_reset_password_and_urlpath(monkeypatch, tmp_path, capsys):
    install_dir = _install(tmp_path)
    (tmp_path / "data" / "ovmanager.db").write_bytes(b"")
    monkeypatch.setattr(password, "hash_password", lambda p: "$2b$12$STUBHASH")
    monkeypatch.setattr(password, "_write_owner_hash", lambda d, h, o: {"ok": True})
    rc = main(["--install-dir", install_dir, "reset-password", "--admin-pass", "long-enough-password"])
    assert rc == 0
    assert "database" in capsys.readouterr().out
    rc = main(["--install-dir", install_dir, "reset-password", "--admin-pass", "short"])
    assert rc == 1
    monkeypatch.setattr(
        urlpath.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    rc = main(["--install-dir", install_dir, "reset-urlpath"])
    assert rc == 0
    assert "served at /" in capsys.readouterr().out


def test_reset_password_never_touches_a_path_outside_the_sandbox(tmp_path):
    """A forgotten --install-dir must not reach a real install.

    The CLI defaults to /opt/ovmanager, so a test that omits the override
    edits a live panel's .env. conftest points OVM_APP_DIR at a throwaway
    tree; this pins that contract instead of trusting it.
    """
    import os

    from cli.env import Install

    default_install = Install.detect()
    assert default_install.install_dir == os.environ["OVM_APP_DIR"]
    assert default_install.install_dir != "/opt/ovmanager"
    assert default_install.install_dir.startswith(tempfile.gettempdir())

    out = password.reset_password(default_install.install_dir, "long-enough-password")
    assert out["ok"] is False, "no .env there, so it must refuse rather than create one"
    assert not os.path.exists(os.path.join(default_install.install_dir, ".env"))
