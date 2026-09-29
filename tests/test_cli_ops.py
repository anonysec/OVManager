# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for doctor --fix and tls status (hermetic, no root/services)."""

import stat

import pytest

import cli.doctor as doctor
import cli.password as password
import cli.tls as tls
import cli.urlpath as urlpath
from cli.env import Install
from cli.main import main


def _install(tmp_path):
    install_dir = tmp_path / "opt"
    install_dir.mkdir()
    (install_dir / ".env").write_text("PORT=2095\nADMIN_USERNAME=admin\n", encoding="utf-8")
    (install_dir / ".env").chmod(0o600)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ovmanager.db").write_bytes(b"")
    return Install.detect(install_dir=str(install_dir), data_dir=str(data_dir))


def test_fix_restarts_service_then_rechecks(monkeypatch, tmp_path):
    install = _install(tmp_path)
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(doctor, "service_state", lambda compose: ("native", "active"))
    monkeypatch.setattr("subprocess.run", lambda argv, **kw: calls.append(argv) or Done())
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: calls.append(argv) or Done())
    bad = doctor.Check("Service", False, "inactive", "ovm restart")
    out = doctor.fix(bad, install)
    assert out.ok is True
    assert calls and calls[0][:2] == ["systemctl", "restart"]


def test_fix_chmods_env_file(tmp_path):
    install = _install(tmp_path)
    (tmp_path / "opt" / ".env").chmod(0o644)
    bad = doctor.check_env_perms(install)
    assert bad.ok is False
    out = doctor.fix(bad, install)
    assert out.ok is True
    assert stat.S_IMODE((tmp_path / "opt" / ".env").stat().st_mode) == 0o600


def test_fix_leaves_ok_and_unfixable_alone(tmp_path):
    install = _install(tmp_path)
    ok = doctor.Check("Disk", True, "plenty", "")
    assert doctor.fix(ok, install) is ok
    disk = doctor.Check("Disk", False, "full", "free disk space")
    assert doctor.fix(disk, install) is disk


def test_tls_status_without_tls(tmp_path):
    install = _install(tmp_path)
    data = tls.status(install)
    assert data == {"ok": True, "tls": False, "key": None, "cert": None, "expiry": None}
    assert "plain HTTP" in tls.render_text(data)


def test_tls_status_reads_expiry(monkeypatch, tmp_path):
    install = _install(tmp_path)
    (tmp_path / "x").mkdir(exist_ok=True)
    (tmp_path / "x" / "cert.pem").write_text("pem", encoding="utf-8")
    (tmp_path / "opt" / ".env").write_text(
        f"PORT=2095\nSSL_KEYFILE={tmp_path}/x/key.pem\nSSL_CERTFILE={tmp_path}/x/cert.pem\n", encoding="utf-8"
    )
    install = Install.detect(install_dir=str(tmp_path / "opt"), data_dir=str(tmp_path / "data"))

    class Done:
        returncode = 0
        stdout = "notAfter=Aug 12 12:00:00 2027 GMT\n"

    monkeypatch.setattr(tls.subprocess, "run", lambda *a, **k: Done())
    data = tls.status(install)
    assert data["tls"] is True
    assert data["expiry"] == "Aug 12 12:00:00 2027 GMT"
    assert "Expires" in tls.render_text(data)


def test_main_doctor_fix_and_tls_status(monkeypatch, tmp_path, capsys, hold_worker_lock):
    install = _install(tmp_path)
    # A healthy install has a running worker; the lock is how doctor knows.
    hold_worker_lock(tmp_path / "data")
    monkeypatch.setattr(doctor, "service_state", lambda compose: ("native", "active"))
    # The Service account check reads a unit file; the host's real one says
    # whatever this machine runs, so point it at a fixture saying it is not root.
    unit = tmp_path / "ovmanager.service"
    unit.write_text("[Service]\nUser=ovmanager\nGroup=ovmanager\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: str(unit))
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.9"))
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "enabled\n", "returncode": 0})())
    # The backup-age check reads the real /var/backups, which is populated on a
    # developer box and empty on a runner. Give it a fresh bundle so the exit
    # code means the same thing in both.
    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "fresh.ovmbak").write_text("x", encoding="utf-8")
    import cli.main as m

    monkeypatch.setattr(m, "Install", type("I", (), {"detect": staticmethod(lambda **kw: install)}))
    assert main(["doctor-fix"]) == 0, capsys.readouterr().out
    assert "Problems" in capsys.readouterr().out
    assert main(["tls-status"]) == 0


def test_flags_work_after_the_subcommand(capsys, tmp_path):
    """`ovm status --all` must parse, not die on 'unrecognized arguments'."""
    install = _install(tmp_path)
    import cli.main as m

    monkey = pytest.MonkeyPatch()
    monkey.setattr(m, "Install", type("I", (), {"detect": staticmethod(lambda **kw: install)}))
    monkey.setattr("cli.status.fetch_health", lambda *a, **k: (True, "1.0.10"))
    monkey.setattr("cli.status.service_state", lambda *a, **k: ("native", "active"))
    try:
        assert m.main(["status", "--all"]) == 0
    finally:
        monkey.undo()

    out = capsys.readouterr().out
    assert "v1.0.10" in out and str(tmp_path / "opt") in out


def _self_signed_cert(tmp_path):
    """A real self-signed PEM, or skip when openssl is unavailable."""
    import shutil
    import subprocess

    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    done = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        timeout=60,
    )
    if done.returncode != 0:
        pytest.skip("openssl could not generate a test certificate")
    return str(cert)


def test_health_probe_accepts_self_signed_when_pinned(tmp_path, monkeypatch):
    """A self-signed panel must not read as 'unreachable' when its cert is known."""
    import ssl

    import cli.probes as probes

    cert = _self_signed_cert(tmp_path)
    seen = {}

    class Resp:
        def read(self):
            return b'{"version": "1.0.10"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, **kw):
        seen.update(kw)
        return Resp()

    monkeypatch.setattr(probes.urllib.request, "urlopen", fake_urlopen)
    ok, ver = probes.fetch_health("https://127.0.0.1:2095/health", cafile=cert)
    assert (ok, ver) == (True, "1.0.10")
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED, "must pin to the installed cert"
    # The installer's cert carries the public IP as CN and no SANs while the
    # probe dials 127.0.0.1: a name check fails on a healthy panel with
    # "IP address mismatch". Identity is the pinned cert, not the hostname.
    assert seen["context"].check_hostname is False

    # Unreadable cert: mirror the bash path's `curl -k` so both agree on health.
    probes.fetch_health("https://127.0.0.1:2095/health", cafile=str(tmp_path / "missing.pem"))
    assert seen["context"].verify_mode == ssl.CERT_NONE


def test_health_probe_http_has_no_ssl_context(monkeypatch):
    import cli.probes as probes

    seen = {}

    class Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(probes.urllib.request, "urlopen", lambda url, **kw: seen.update(kw) or Resp())
    probes.fetch_health("http://127.0.0.1:2095/health")
    assert "context" not in seen


def test_install_cafile_reads_env(tmp_path):
    (tmp_path / "opt").mkdir()
    (tmp_path / "opt" / ".env").write_text("SSL_CERTFILE=/x/c.pem\n", encoding="utf-8")
    install = Install.detect(install_dir=str(tmp_path / "opt"), data_dir=str(tmp_path / "data"))
    assert install.cafile == "/x/c.pem"
    assert Install.detect(install_dir=str(tmp_path / "none"), data_dir=str(tmp_path)).cafile is None


def test_in_container_flag_skips_the_env_perms_check(tmp_path):
    """In a container there is no host .env to stat, so the check stands down."""
    install = _install(tmp_path)
    (tmp_path / "opt" / ".env").unlink()
    assert doctor.check_env_perms(install).ok is False, "a missing .env fails natively"
    inside = doctor.check_env_perms(install, in_container=True)
    assert inside.ok is True and "host-managed" in inside.detail


def test_service_state_override_is_used_when_given(tmp_path, monkeypatch):
    """The host tells the CLI what it saw; the container cannot ask docker."""
    install = _install(tmp_path)
    monkeypatch.setattr(doctor, "service_state", lambda compose: ("docker", "unknown"))
    assert doctor.check_service(install).ok is False
    assert doctor.check_service(install, "running").ok is True
    assert doctor.check_service(install, "stopped").ok is False


def test_status_service_override(tmp_path, monkeypatch):
    import cli.status as status_mod

    install = _install(tmp_path)
    monkeypatch.setattr(status_mod, "service_state", lambda compose: ("docker", "unknown"))
    monkeypatch.setattr(status_mod, "fetch_health", lambda *a, **k: (True, "1.0.12"))
    assert status_mod.collect(install)["service"] == "unknown"
    assert status_mod.collect(install, "running")["service"] == "running"


def test_reset_password_reads_the_secret_from_the_environment(tmp_path, monkeypatch):
    """The manager passes the secret in the environment, never in argv."""
    install = _install(tmp_path)
    monkeypatch.setattr(password, "hash_password", lambda p: "$2b$12$STUBHASH")
    monkeypatch.setattr(password, "_write_owner_hash", lambda d, h, o: {"ok": True})
    monkeypatch.setenv("OVM_ADMIN_PASS", "long-enough-password")
    out = password.reset_password(install.install_dir, data_dir=install.data_dir)
    assert out["ok"] is True and out["scope"] == "database"
    assert "OVM_ADMIN_PASS" not in (tmp_path / "opt" / ".env").read_text(encoding="utf-8")
    monkeypatch.delenv("OVM_ADMIN_PASS")
    out = password.reset_password(install.install_dir, data_dir=install.data_dir)
    assert out["ok"] is False and "No password given" in out["error"]


def test_reset_urlpath_uses_the_native_path_in_container(tmp_path, monkeypatch):
    """`docker exec` cannot work from inside the container; main.py is here."""
    install = _install(tmp_path)
    calls = {}

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kw):
        calls["argv"] = argv
        return Done()

    monkeypatch.setattr(urlpath.subprocess, "run", fake_run)
    compose = tmp_path / "ovmanager-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    assert urlpath.reset_urlpath(install.install_dir, str(compose), in_container=True)["ok"] is True
    assert calls["argv"][0].endswith("python"), calls["argv"]
