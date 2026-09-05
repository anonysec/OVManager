# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Behavioral tests for install.sh's beginner-facing contract (no root side-effects).

These exercise the paths newcomers and automation rely on: help text,
validation errors, and dry-run safety. They never get past validation or
the dry-run guard, so they cannot touch the system — with one exception
(marked): the JSON dry-run shape test, which runs only on machines where
OVManager is NOT installed.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

INSTALLER = os.path.join(os.path.dirname(__file__), "..", "install.sh")
INSTALLER_PATH = Path(INSTALLER)
INSTALL_DIR = "/opt/ovmanager"
SETSID = shutil.which("setsid")


def sh(*args: str, env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    cmd = ["bash", INSTALLER, *args]
    if SETSID:  # detach controlling terminal: no /dev/tty prompts, fully deterministic
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
    """A rewritten installer copy pointing at throwaway dirs.

    Makes validation/menu tests hermetic: they behave the same whether or
    not /opt/ovmanager exists on the test machine.
    """
    fake_opt = tmp_path / "opt"
    fake_data = tmp_path / "data"
    src = INSTALLER_PATH.read_text(encoding="utf-8")
    src = src.replace("/opt/ovmanager", str(fake_opt)).replace("/var/lib/ovmanager", str(fake_data))
    path = tmp_path / "install.sh"
    path.write_text(src, encoding="utf-8")
    return str(path), str(fake_opt)


def sh_sb(sandbox_installer, *args: str, env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    cmd = ["bash", sandbox_installer, *args]
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


def test_installer_syntax():
    subprocess.run(["bash", "-n", INSTALLER], check=True)


def test_help_documents_beginner_paths():
    r = sh("--help")
    assert r.returncode == 0
    for token in ("status", "--with-node", "--dry-run", "OVM_WITH_NODE", "update", "uninstall", "--tls-self"):
        assert token in r.stdout or token in r.stderr, f"help missing {token}"


def test_invalid_port_fails_before_any_change(tmp_path):
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "install", "-y", "--port", "abc", "--admin-pass", "long-enough-password")
    assert r.returncode == 1
    assert "Invalid port" in r.stderr or "root" in r.stderr  # non-root CI dies at check_root first


def test_short_admin_password_rejected(tmp_path):
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "install", "-y", "--admin-pass", "short")
    assert r.returncode == 1
    assert "at least 8" in r.stderr or "root" in r.stderr


def test_unknown_option_fails():
    r = sh("--nonsense-flag")
    assert r.returncode == 1


def test_bad_node_name_rejected(tmp_path):
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "install", "-y", "--admin-pass", "long-enough-password", "--with-node", "bad name!")
    assert r.returncode == 1
    assert "Node name" in r.stderr or "root" in r.stderr


def test_dry_run_never_touches_live_flows():
    """Every destructive/live flow must honor --dry-run (regression: an
    early version ran a real update when /opt/ovmanager existed)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'Dry run — nothing changed (re-run without --dry-run to update/uninstall)' in content
    assert 'Dry run — nothing changed (would back up data, pull, rebuild)' in content
    assert 'Dry run — nothing changed (would stop the service' in content


def test_already_installed_menu_defaults_to_quit():
    """On EOF/Enter the menu must quit, never auto-start update/uninstall."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'choice="$(ask "Select" "3")"' in content
    assert 'case "${choice:-3}"' in content


def test_already_installed_menu_is_safe_by_default(tmp_path):
    """With an existing install dir and no tty, the menu must refuse to act
    (exit 2) — never default into update/uninstall."""
    sb, fake_opt = sandbox(tmp_path)
    os.makedirs(fake_opt)
    r = sh_sb(sb, "install", "-y", "--admin-pass", "long-enough-password")
    assert r.returncode == 2
    assert "Already installed" in r.stderr


def test_already_installed_dry_run_is_noop(tmp_path):
    sb, fake_opt = sandbox(tmp_path)
    os.makedirs(fake_opt)
    r = sh_sb(sb, "install", "--dry-run", "-y", "--admin-pass", "long-enough-password")
    assert r.returncode == 0
    assert "nothing changed" in r.stderr


def test_fresh_dry_run_json_shape(tmp_path):
    """Fresh-install dry-run prints the plan as a single JSON object."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(
        sb,
        "install",
        "--dry-run",
        "-y",
        "--mode",
        "native",
        "--admin-pass",
        "long-enough-password",
        "--with-node",
        "mynode",
        "--json",
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)  # stdout is exactly one JSON object
    assert data["ok"] is True
    assert data["user"] == "admin"
    assert data["password"] == "long-enough-password"
    assert data["node"]["name"] == "mynode"
    assert len(data["node"]["api_key"]) >= 32
    assert data["node"]["same_server"] is True


def test_docker_data_dir_and_perms_are_container_safe():
    """Fresh Docker installs crash-looped twice: .env carried the HOST data
    path into the container (appuser mkdir → PermissionError), then the
    root-owned host dir masked /app/data, then unreadable TLS keys.
    Pin the three guards: container DATA_DIR, host chown, readable certs."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert '[[ "$MODE" == "docker" ]] && data_dir="/app/data"' in content
    assert 'chown -R 1000:1000 "$DATA_DIR"' in content
    assert "chmod 644 /etc/ssl/self-signed/privkey.pem /etc/ssl/self-signed/fullchain.pem" in content
    assert '>/dev/stderr' in content  # build output must not pollute --json stdout
