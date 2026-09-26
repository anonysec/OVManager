# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for the read-only operator CLI (fast, hermetic — no root/services)."""

import json

import cli.doctor as doctor
import cli.logs as logs
import cli.status as status
from cli.env import Install
from cli.main import main


def _install(tmp_path, env_lines=(), data=True):
    install_dir = tmp_path / "opt"
    install_dir.mkdir()
    (install_dir / ".env").write_text(
        "PORT=2095\nURLPATH=abc\nADMIN_USERNAME=admin\nADMIN_PASSWORD=long-enough-password\n",
        encoding="utf-8",
    )
    for line in env_lines:
        with open(install_dir / ".env", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    data_dir = tmp_path / "data"
    if data:
        data_dir.mkdir()
    return Install.detect(install_dir=str(install_dir), data_dir=str(data_dir))


def test_env_detect_reads_port_prefix_tls():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        install = _install(Path(td), env_lines=("SSL_KEYFILE=/x.pem",))
        assert install.port == 2095
        assert install.path_prefix == "abc"
        assert install.scheme == "https"
        assert install.health_url == "https://127.0.0.1:2095/health"


def test_env_detect_defaults_without_env():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        install_dir = Path(td) / "opt"
        install_dir.mkdir()
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        install = Install.detect(install_dir=str(install_dir), data_dir=str(data_dir))
        assert install.port == 2095
        assert install.scheme == "http"


def test_status_collect_uninstalled(tmp_path):
    install = Install.detect(install_dir=str(tmp_path / "missing"), data_dir=str(tmp_path))
    data = status.collect(install)
    assert data["ok"] is False and data["installed"] is False


def test_status_collect_healthy(monkeypatch, tmp_path):
    install = _install(tmp_path)
    monkeypatch.setattr(status, "fetch_health", lambda url, timeout=5.0: (True, "1.0.8"))
    monkeypatch.setattr(status, "service_state", lambda compose: ("native", "active"))
    monkeypatch.setattr(status, "primary_ip", lambda: "10.0.0.1")
    data = status.collect(install)
    assert data == {
        "ok": True,
        "installed": True,
        "mode": "native",
        "service": "active",
        "health": "ok",
        "version": "1.0.8",
        "url": "http://10.0.0.1:2095/abc/",
        "install_dir": str(tmp_path / "opt"),
        "data_dir": str(tmp_path / "data"),
        "port": 2095,
    }
    text = status.render_text(data, show_all=True)
    assert "active" in text and "v1.0.8" in text and "Mode" in text
    parsed = json.loads(status.render_json(data))
    assert parsed["health"] == "ok"


def test_logs_command_selection(tmp_path):
    _install(tmp_path)
    assert logs.build_command(str(tmp_path / "opt"), str(tmp_path / "data" / "nope"), "100") == [
        "journalctl",
        "-u",
        "ovmanager.service",
        "-n",
        "100",
        "--no-pager",
    ]
    assert logs.build_command(str(tmp_path / "opt"), str(tmp_path / "data" / "nope"), "-f") == [
        "journalctl",
        "-u",
        "ovmanager.service",
        "-n",
        "100",
        "-f",
    ]
    (tmp_path / "data" / "ovmanager-compose.yml").write_text("x", encoding="utf-8")
    assert logs.build_command(str(tmp_path / "opt"), str(tmp_path / "data" / "ovmanager-compose.yml"), "50") == [
        "docker",
        "logs",
        "--tail",
        "50",
        "ovmanager",
    ]


def test_doctor_checks_shape(monkeypatch, tmp_path):
    install = _install(tmp_path)
    (tmp_path / "opt" / ".env").chmod(0o600)
    monkeypatch.setattr(doctor, "service_state", lambda compose: ("native", "active"))
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0: (True, "1.0.8"))
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "enabled\n"})(),
    )
    checks = doctor.collect(install)
    assert [c.name for c in checks] == [
        "Service",
        "Auto start",
        "Config perms",
        "Data dir",
        "Disk",
        "Panel health",
    ]
    assert all(c.ok for c in checks), [(c.name, c.detail) for c in checks]
    assert "Problems" in doctor.render_text(checks)


def test_doctor_flags_bad_env_perms(monkeypatch, tmp_path):
    install = _install(tmp_path)
    (tmp_path / "opt" / ".env").chmod(0o644)
    c = doctor.check_env_perms(install)
    assert c.ok is False and "chmod 600" in c.fix


def test_main_status_json(monkeypatch, tmp_path, capsys):
    install = _install(tmp_path)
    monkeypatch.setattr(status, "fetch_health", lambda url, timeout=5.0: (True, "1.0.8"))
    monkeypatch.setattr(status, "service_state", lambda compose: ("native", "active"))
    monkeypatch.setattr(status, "primary_ip", lambda: "10.0.0.1")
    import cli.main as m

    monkeypatch.setattr(m, "Install", type("I", (), {"detect": staticmethod(lambda **kw: install)}))
    rc = main(["--install-dir", str(tmp_path / "opt"), "--data-dir", str(tmp_path / "data"), "--json", "status"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["version"] == "1.0.8"
