# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for the read-only operator CLI (fast, hermetic — no root/services)."""

import os
import stat
from pathlib import Path

import pytest

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
    monkeypatch.setattr(status, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.8"))
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


def test_doctor_checks_shape(monkeypatch, tmp_path, hold_worker_lock):
    install = _install(tmp_path)
    # A healthy install has a running worker; the lock is how doctor knows.
    hold_worker_lock(tmp_path / "data")
    _shape_and_all_ok(monkeypatch, tmp_path, install)


def _shape_and_all_ok(monkeypatch, tmp_path, install):
    (tmp_path / "opt" / ".env").chmod(0o600)
    monkeypatch.setattr(doctor, "service_state", lambda compose: ("native", "active"))
    # The Service account check reads a unit file. The host's real one says
    # whatever this machine runs, so point it at a fixture that says the panel
    # is not root -- the arrangement 1.0.25 installs.
    unit = tmp_path / "ovmanager.service"
    unit.write_text("[Service]\nUser=ovmanager\nGroup=ovmanager\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: str(unit))
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.8"))
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": "enabled\n"})(),
    )
    (tmp_path / "data").chmod(0o700)  # the Permissions check is real
    # /var/backups is real on a developer box and empty on a runner, so a fresh
    # bundle in the temp data dir is what makes this check mean the same thing
    # in both places.
    bundles = tmp_path / "data" / "backups"
    bundles.mkdir(parents=True, exist_ok=True)
    bundles.chmod(0o700)  # the Permissions check wants 0700 on the backups dir
    (bundles / "fresh.ovmbak").write_text("x", encoding="utf-8")
    checks = doctor.collect(install, legacy_backup_dir=str(tmp_path / "no-legacy-backups"))
    # The four checks below the original six were ported back from the bash
    # doctor: certificate expiry, interrupted update, backup age and private
    # permissions. They went missing when the CLI became the default in
    # 1.0.10, and this list is what stops that recurring.
    assert [c.name for c in checks] == [
        "Service",
        "Auto start",
        "Certificate",
        "Update",
        "Backup",
        "Permissions",
        "Disk",
        "Config perms",
        "TLS key",
        "Data dir",
        "Panel health",
        "Worker",
        "Service account",
    ]
    assert all(c.ok for c in checks), [(c.name, c.detail) for c in checks]
    assert "Problems" in doctor.render_text(checks)


def test_doctor_flags_bad_env_perms(monkeypatch, tmp_path):
    """A world-readable .env is wrong either way; the advice depends on the unit.

    On a root panel `0600` is the answer. On a panel running as a service
    account, `0640` to that account's group is: still unreadable by any other
    local account, and readable by the panel. Telling a service-account install
    to `chmod 600` would leave it unable to read its own configuration.
    """
    install = _install(tmp_path)
    (tmp_path / "opt" / ".env").chmod(0o644)

    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "root"))
    as_root = doctor.check_env_perms(install)
    assert as_root.ok is False and "chmod 600" in as_root.fix

    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "ovmanager"))
    monkeypatch.setattr(doctor, "_group_name", lambda gid: "ovmanager")
    as_service = doctor.check_env_perms(install)
    assert as_service.ok is False
    assert "chmod 640" in as_service.fix, as_service.fix
    assert "chgrp ovmanager" in as_service.fix, as_service.fix


def test_main_status_prints_the_human_table(monkeypatch, tmp_path, capsys):
    install = _install(tmp_path)
    monkeypatch.setattr(status, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.8"))
    monkeypatch.setattr(status, "service_state", lambda compose: ("native", "active"))
    monkeypatch.setattr(status, "primary_ip", lambda: "10.0.0.1")
    import cli.main as m

    monkeypatch.setattr(m, "Install", type("I", (), {"detect": staticmethod(lambda **kw: install)}))
    rc = main(["--install-dir", str(tmp_path / "opt"), "--data-dir", str(tmp_path / "data"), "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Version" in out and "v1.0.8" in out


def test_global_flags_work_on_either_side_of_the_subcommand():
    """`ovm --all status` and `ovm status --all` must parse identically.

    argparse re-declares a shared parent parser's actions on the subparser, so
    a plain `parents=[common]` silently overwrites the main parser's value with
    the subparser's default — the flag looked accepted and was then ignored.
    """
    from cli.main import build_parser

    for argv in (
        ["--all", "status"],
        ["status", "--all"],
    ):
        args = build_parser().parse_args(argv)
        assert args.show_all is True, argv
    plain = build_parser().parse_args(["status"])
    assert plain.show_all is False
    assert plain.install_dir is None and plain.data_dir is None


# ── the service account ───────────────────────────────────────────────────
#
# 1.0.25 stops running the panel as root: it is a network-facing service that
# parses untrusted input, and a compromise of the web app should not be a
# compromise of the host.


def _unit(tmp_path, user: str) -> str:
    path = tmp_path / f"unit-{user or 'root'}.service"
    path.write_text(f"[Service]\nUser={user}\nGroup={user}\n", encoding="utf-8")
    return str(path)


def test_service_account_check_flags_a_root_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "root"))
    result = doctor.check_service_account(_install(tmp_path))
    assert result.ok is False
    assert "root" in result.detail
    assert result.fix, "a failing check must say what to run"


def test_service_account_check_accepts_a_service_user(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "ovmanager"))
    result = doctor.check_service_account(_install(tmp_path))
    assert result.ok is True
    assert "ovmanager" in result.detail


def test_service_account_check_reads_the_unit_not_a_hardcoded_name(tmp_path, monkeypatch):
    """A renamed account is not a misconfiguration, so do not hard-code one."""
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "vpnpanel"))
    assert doctor.check_service_account(_install(tmp_path)).ok is True


def test_service_account_check_is_happy_on_docker(tmp_path, monkeypatch):
    """The image has its own appuser; there is nothing to see from the host."""
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "root"))
    assert doctor.check_service_account(_install(tmp_path), in_container=True).ok is True


def test_config_perms_accepts_the_service_group(tmp_path, monkeypatch):
    """0640 root:ovmanager is the correct arrangement, not a lax one.

    No local account other than that service can read the admin hash, the JWT
    key or the secret URL path — which is the same property 0600 gave, reached
    without making the panel unable to read its own configuration.
    """
    install = _install(tmp_path)
    env = install.install_dir + "/.env"
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: _unit(tmp_path, "ovmanager"))
    monkeypatch.setattr(doctor, "_group_name", lambda gid: "ovmanager")
    os.chmod(env, 0o640)
    result = doctor.check_env_perms(install)
    assert result.ok is True, result.detail
    assert "ovmanager" in result.detail


def test_config_perms_still_rejects_a_world_readable_env(tmp_path, monkeypatch):
    """Group-readable is only acceptable when the group is the service."""
    install = _install(tmp_path)
    env = install.install_dir + "/.env"
    monkeypatch.setattr(doctor, "_group_name", lambda gid: "ovmanager")
    os.chmod(env, 0o644)
    result = doctor.check_env_perms(install)
    assert result.ok is False
    assert "0640" in result.detail or "0600" in result.detail


def test_config_perms_accepts_0600_whatever_the_group(tmp_path):
    """Regression: 0600 was wrongly conditional on the file being root-grouped.

    Only the owner can read a 0600 file, so the group is irrelevant to it.
    Requiring gid 0 meant a correct .env was reported as a misconfiguration
    the moment the suite ran as a user whose files are not root-grouped — which
    is what CI does, and what hid it locally.
    """
    install = _install(tmp_path)
    os.chmod(install.install_dir + "/.env", 0o600)
    result = doctor.check_env_perms(install)
    assert result.ok is True, result.detail


# ── the migration itself ──────────────────────────────────────────────────
#
# `ovm update` cannot perform the migration that moves the panel off root,
# because the installer doing the updating is the previous release's copy:
# do_update swaps the tree that holds it partway through. So the migration
# lives in `ovm doctor --fix`, which runs out of the updated tree.


def _migration_env(tmp_path, monkeypatch, user: str = "ovtest"):
    """Point the fix at a sandbox, and fake the two accounts it touches."""
    install = _install(tmp_path)
    unit = tmp_path / "ovmanager.service"
    # The real unit's shape, all three sections: a fixture with only [Service]
    # would not catch a Group= appended past [Install], which is the bug this
    # is testing for.
    unit.write_text(
        "[Unit]\nDescription=OVManager\n\n[Service]\nType=simple\nUser=root\n"
        "WorkingDirectory=/opt/ovmanager\nExecStart=/root/.local/bin/uv run main.py\n"
        "\n[Install]\nWantedBy=multi-user.target\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: str(unit))
    monkeypatch.setattr(doctor, "PANEL_USER", user)
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.9"))
    calls: list[list[str]] = []
    monkeypatch.setattr(doctor, "_run", lambda argv, **kw: calls.append(argv) or True)
    monkeypatch.setattr(doctor.pwd, "getpwnam", lambda n: _Named("ovtest", 4242, 4242))
    monkeypatch.setattr(doctor.grp, "getgrnam", lambda n: _Named("ovtest", 4242, 4242))
    return install, unit, calls


class _Named:
    def __init__(self, name, uid, gid):
        self.pw_name = name
        self.pw_uid = uid
        self.gr_name = name
        self.gr_gid = gid


def test_migration_inserts_group_beside_user_and_not_at_the_end(tmp_path, monkeypatch):
    """Appending Group= at the end of the file would land it in [Install].

    systemd rejects a Service= directive in the wrong section, and the panel
    would not start — so this asserts the section, not just the presence.
    """
    install, unit, _ = _migration_env(tmp_path, monkeypatch)
    doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))
    body = unit.read_text(encoding="utf-8")
    service = body[body.index("[Service]") : body.index("[Install]")]
    assert "User=ovtest" in service
    assert "Group=ovtest" in service
    assert "Group=" not in body[body.index("[Install]") :], "Group= landed in [Install]"


@pytest.mark.skipif(os.geteuid() != 0, reason="asserts real chown/chmod results, and chgrp needs root")
def test_migration_grants_the_service_account_exactly_what_it_needs(tmp_path, monkeypatch):
    install, unit, _ = _migration_env(tmp_path, monkeypatch)
    key = tmp_path / "privkey.pem"
    key.write_text("k", encoding="utf-8")
    (Path(install.install_dir) / ".env").write_text(f"SSL_KEYFILE={key}\n", encoding="utf-8")

    doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))

    env = Path(install.install_dir) / ".env"
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o640, ".env must be group-read for the service"
    assert os.stat(env).st_gid == 4242
    assert stat.S_IMODE(os.stat(install.install_dir).st_mode) == 0o750
    assert os.stat(install.install_dir).st_gid == 4242
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o640, "the TLS key follows .env's reasoning"


def test_migration_restarts_and_verifies_the_panel(tmp_path, monkeypatch):
    """A migration that leaves the panel down is worse than not migrating."""
    install, unit, calls = _migration_env(tmp_path, monkeypatch)
    doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))
    argv = [" ".join(c) for c in calls]
    assert any("daemon-reload" in a for a in argv), argv
    assert any("restart" in a for a in argv), argv


def test_migration_puts_the_unit_back_when_the_panel_does_not_return(tmp_path, monkeypatch):
    """The unit is outside the tree, so no update rollback can undo it."""
    install, unit, calls = _migration_env(tmp_path, monkeypatch)
    original = unit.read_text(encoding="utf-8")
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0, cafile=None: (False, ""))
    monkeypatch.setattr(doctor.time, "sleep", lambda s: None)
    monkeypatch.setattr(doctor.time, "monotonic", _FakeClock())

    result = doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))

    assert result.ok is False
    assert "restored" in result.detail
    assert unit.read_text(encoding="utf-8") == original, "the unit was left broken"
    assert "daemon-reload" in " ".join(" ".join(c) for c in calls[-2:])


class _FakeClock:
    """A monotonic that jumps, so the 30s wait does not take 30s."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 5.0
        return self.t


def test_migration_refuses_a_unit_it_does_not_understand(tmp_path, monkeypatch):
    """Better to say so than to guess at an unfamiliar unit."""
    install, unit, _ = _migration_env(tmp_path, monkeypatch)
    unit.write_text("[Service]\nDynamicUser=yes\nExecStart=/bin/true\n", encoding="utf-8")
    result = doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))
    assert result.ok is False
    assert "by hand" in result.detail or "nothing to change" in result.detail


def test_migration_replaces_uv_run_because_it_cannot_run_unprivileged(tmp_path, monkeypatch):
    """`uv run` rebuilds the project, which needs write access to the tree.

    As the service account it fails with "Cannot
    update time stamp of directory 'ovmanager.egg-info'", because uv re-resolves
    the project before starting it and writes into the install tree. The panel
    has therefore never actually run unprivileged before this — an earlier
    feasibility check booted `.venv/bin/python3` directly, so it never
    exercised the start command the unit actually used.
    """
    install, unit, _ = _migration_env(tmp_path, monkeypatch)
    doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))
    body = unit.read_text(encoding="utf-8")
    assert "uv run main.py" not in body, f"the unit still rebuilds the project:\n{body}"
    assert f"ExecStart={install.install_dir}/.venv/bin/python3 main.py" in body


def test_migration_leaves_a_venv_interpreter_alone(tmp_path, monkeypatch):
    """Idempotent, and it must not rewrite a start command that already works."""
    install, unit, _ = _migration_env(tmp_path, monkeypatch)
    unit.write_text(
        f"[Service]\\nUser=root\\nExecStart={install.install_dir}/.venv/bin/python3 main.py\\n",
        encoding="utf-8",
    )
    doctor.fix_service_account(install, doctor.Check("Service account", False, "x", ""))
    assert f"ExecStart={install.install_dir}/.venv/bin/python3 main.py" in unit.read_text(encoding="utf-8")


@pytest.mark.skipif(os.geteuid() != 0, reason="asserts real chgrp/chmod results, and chgrp needs root")
def test_config_perms_is_not_chmodded_back_after_the_migration(tmp_path, monkeypatch):
    """The two checks used to fight, and the panel lost.

    `fix_all` collected every check, then fixed them. Config perms ran against
    a unit that still said User=root, saw the 0640 .env the migration had just
    granted, did not recognise it, and chmod'd it back to 0600 — leaving the
    panel unable to read its own configuration as the account it had been moved
    to. The Service account fix now runs first and the rest are re-collected.
    """
    install = _install(tmp_path)
    unit = tmp_path / "ovmanager.service"
    unit.write_text("[Service]\nUser=root\nExecStart=/root/.local/bin/uv run main.py\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_default_unit_path", lambda: str(unit))
    monkeypatch.setattr(doctor, "PANEL_USER", "ovtest")
    monkeypatch.setattr(doctor, "fetch_health", lambda url, timeout=5.0, cafile=None: (True, "1.0.9"))
    monkeypatch.setattr(doctor, "_run", lambda argv, **kw: True)
    monkeypatch.setattr(doctor.pwd, "getpwnam", lambda n: _Named("ovtest", 4242, 4242))
    monkeypatch.setattr(doctor.grp, "getgrnam", lambda n: _Named("ovtest", 4242, 4242))
    # getgrgid is what _group_name uses to read the .env's group back, and gid
    # 4242 does not exist on the test machine.
    monkeypatch.setattr(doctor, "_group_name", lambda gid: "ovtest")
    monkeypatch.setattr(doctor, "service_state", lambda compose: ("native", "active"))
    env = Path(install.install_dir) / ".env"

    results = {c.name: c for c in doctor.fix_all(install, None, False)}

    assert "User=ovtest" in unit.read_text(encoding="utf-8"), "the migration did not run"
    assert results["Service account"].ok, results["Service account"].detail
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o640, (
        "Config perms undid the grant the migration had just made, so the panel could not read its own configuration"
    )
    assert results["Config perms"].ok, results["Config perms"].detail
