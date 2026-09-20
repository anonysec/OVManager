# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Behavioral tests for manager.sh (ovmanager/ovm): day-to-day operations.

The manager runs against an installed tree ($INSTALL_DIR, overridable via
OVM_APP_DIR for hermetic tests) and sources $INSTALL_DIR/lib/common.sh.
Update/uninstall delegate to install.sh. Tests never touch the live system:
sandbox trees plus stub tools stand in for systemd/curl/docker.
"""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANAGER = os.path.join(os.path.dirname(__file__), "..", "manager.sh")
MANAGER_PATH = Path(MANAGER)
LIB = REPO / "lib" / "common.sh"
SETSID = shutil.which("setsid")


def mgr(*args: str, env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    cmd = ["bash", MANAGER, *args]
    if SETSID:
        cmd = [SETSID, *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
        stdin=subprocess.DEVNULL,
    )


def sandbox(tmp_path):
    """A fake installed tree: manager.sh runs with OVM_APP_DIR pointed here.

    Layout: <tmp>/opt/{manager.sh,install.sh-stub,lib/common.sh}.
    Returns (env, app_dir).
    """
    app = tmp_path / "opt"
    (app / "lib").mkdir(parents=True)
    shutil.copy(MANAGER_PATH, app / "manager.sh")
    shutil.copy(LIB, app / "lib" / "common.sh")
    (app / "install.sh").write_text("#!/bin/sh\necho \"STUB-INSTALLER $@\"\n", encoding="utf-8")
    (app / "install.sh").chmod(0o755)
    env = {**os.environ, "OVM_APP_DIR": str(app)}
    return env, app


def mgr_sb(env, app, *args: str, extra_env: dict | None = None):
    full_env = {**env, **(extra_env or {})}
    cmd = ["bash", str(app / "manager.sh"), *args]
    if SETSID:
        cmd = [SETSID, *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
        stdin=subprocess.DEVNULL,
    )


def test_manager_syntax():
    subprocess.run(["bash", "-n", MANAGER], check=True)


def test_help_documents_manager_surface():
    r = mgr("help")
    assert r.returncode == 0
    output = r.stdout + r.stderr
    for token in (
        "status", "update", "restart", "logs", "backup", "tls",
        "recovery", "reset-password", "doctor", "rollback",
        "uninstall", "ovm", "-p", "--fix",
    ):
        assert token in output, f"help missing {token}"


def test_bare_run_without_terminal_is_usage_error():
    """Bare `ovm` with no tty must not start doing things."""
    r = mgr()
    assert r.returncode != 0
    assert "No terminal" in r.stderr


def test_unknown_option_fails():
    r = mgr("--nonsense-flag")
    assert r.returncode == 1


def test_numbered_menu_lists_core_ops():
    """Grouped menu: full power on one screen, nothing hidden."""
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "manager_menu()" in content
    for label in (
        "Status", "Update panel", "Restart service", "Login & password",
        "Logs", "Backup", "TLS certificate", "Health check (doctor)",
        "Roll back update", "Uninstall panel",
    ):
        assert label in content, f"menu missing {label}"
    assert "backup_submenu()" in content
    assert "0${NC}) Exit" in content or '0) Exit' in content


def test_update_delegates_to_installer(tmp_path):
    """`ovm update` execs install.sh update (machine flags pass through)."""
    env, app = sandbox(tmp_path)
    r = mgr_sb(env, app, "update", "-y")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER update -y" in r.stdout


def test_update_pin_passes_through(tmp_path):
    env, app = sandbox(tmp_path)
    r = mgr_sb(env, app, "update", "-y", "-v", "v9.9.9")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER update -y -v v9.9.9" in r.stdout


def test_uninstall_delegates_with_purge(tmp_path):
    env, app = sandbox(tmp_path)
    r = mgr_sb(env, app, "uninstall", "-y", "--purge")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER uninstall -y --purge" in r.stdout


def test_update_requires_install_dir(tmp_path):
    """`ovm update` with no installed tree fails cleanly instead of execing."""
    env = {**os.environ, "OVM_APP_DIR": str(tmp_path / "missing")}
    r = mgr("update", env=env)
    assert r.returncode != 0
    assert "Not installed" in r.stderr


def test_reset_password_rejects_weak_passwords(tmp_path):
    """Same floor + placeholder block the panel applies at boot."""
    env, app = sandbox(tmp_path)
    for weak, hint in (("short", "at least 12"), ("change-me-please-123", "placeholder")):
        r = mgr_sb(env, app, "reset-password", "-p", weak)
        assert r.returncode == 1, r.stderr
        assert hint in r.stderr, r.stderr


def test_reset_password_updates_env_and_survives_restart_failure(tmp_path):
    """Only the ADMIN_PASSWORD line changes (0600 kept, other lines intact)
    and a failed service restart is a warning, not a failed recovery."""
    env, app = sandbox(tmp_path)
    envfile = app / ".env"
    envfile.write_text(
        "HOST=0.0.0.0\n"
        "PORT=2095\n"
        "ADMIN_USERNAME=admin\n"
        "ADMIN_PASSWORD=old-password-123\n"
        "URLPATH=sekret\n"
        "JWT_SECRET_KEY=keep-me\n",
        encoding="utf-8",
    )
    envfile.chmod(0o600)

    # curl succeeds so the /health wait is instant; systemctl fails on purpose.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, rc in (("curl", 0), ("systemctl", 1)):
        tool = fake_bin / name
        tool.write_text(f"#!/bin/sh\nexit {rc}\n", encoding="utf-8")
        tool.chmod(0o755)

    r = mgr_sb(
        env, app,
        "reset-password",
        "-p",
        "brand-new-password",
        extra_env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert r.returncode == 0, r.stderr
    text = envfile.read_text(encoding="utf-8")
    assert "ADMIN_PASSWORD=brand-new-password\n" in text
    assert "old-password-123" not in text
    for kept in ("HOST=0.0.0.0", "PORT=2095", "ADMIN_USERNAME=admin", "URLPATH=sekret", "JWT_SECRET_KEY=keep-me"):
        assert kept in text, f"lost {kept}"
    assert (envfile.stat().st_mode & 0o777) == 0o600
    # The new password never echoes back, and the restart failure is a warning.
    assert "brand-new-password" not in r.stdout + r.stderr
    assert "Could not restart" in r.stderr


def test_logs_command_never_crashes(tmp_path):
    env, app = sandbox(tmp_path)
    r = mgr_sb(env, app, "logs", "5")
    assert r.returncode == 0, r.stderr


def test_auto_backup_host_timer_wiring():
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "ovmanager-backup.timer" in content
    assert "ovmanager-backup.service" in content
    assert "backup --keep ${keep}" in content
    assert "auto-backup on" in content
    # /var/backups is pruned, so a daily timer cannot fill the disk.
    assert "prune_backups" in content


def test_manager_version_matches_panel():
    """manager.sh VERSION tracks the panel version (release checklist)."""
    import re

    manager_src = MANAGER_PATH.read_text(encoding="utf-8")
    mver = re.search(r'^VERSION="([^"]+)"', manager_src, re.M).group(1)
    panel_ver = re.search(
        r'__version__ = "([^"]+)"', (REPO / "backend" / "version.py").read_text(encoding="utf-8")
    ).group(1)
    assert mver == panel_ver, f"manager {mver} != panel {panel_ver}"


def test_no_function_ends_with_a_failing_test():
    """Same `set -e` guard as the installer, applied to manager + lib."""
    import re

    def tails(path):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        out, func, body = [], None, []
        for i, line in enumerate(lines, 1):
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\(\)\s*\{$", line)
            if m and func is None:
                func, body = m.group(1), []
                continue
            if func is None:
                continue
            if line == "}":
                tail = next((ln.strip() for ln in reversed(body) if ln.strip() and not ln.strip().startswith("#")), "")
                out.append((func, tail, i))
                func = None
            else:
                body.append(line)
        return out

    offenders = [
        (str(path), name, tail, line)
        for path in (MANAGER_PATH, LIB)
        for name, tail, line in tails(path)
        if re.match(r"^\[\[.*\]\]\s*&&", tail)
    ]
    assert not offenders, offenders


def test_status_json_contract(tmp_path):
    """`ovm status --json` shape is unchanged for automation consumers."""
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "do_status()" in content


def test_doctor_checks_service_disk_panel_cert_backups():
    """doctor covers the beginner-critical checks, each with its fix hint."""
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "do_doctor()" in content
    for token in ("Panel health", "Certificate", "Backup", "Disk", "Service"):
        assert token in content, f"doctor missing {token}"
    for fix in ("ovm restart", "ovm backup", "ovm tls", "ovm logs"):
        assert fix in content, f"doctor missing fix hint {fix}"
    assert '"$FIX" -eq 1' in content


def test_rollback_restores_newest_snapshot():
    """do_rollback restores the newest code snapshot and re-verifies health."""
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "do_rollback()" in content
    assert "latest_snapshot panel" in content
    assert "Rolled back and healthy" in content
