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

import pytest

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
    assert "at least 12" in r.stderr or "root" in r.stderr
    # 8-char passwords passed the installer but 422ed at the panel; now they
    # fail fast with the same 12-char floor the API enforces.
    r = sh_sb(sb, "install", "-y", "--admin-pass", "eight888")
    assert r.returncode == 1
    assert "at least 12" in r.stderr or "root" in r.stderr


def test_unknown_option_fails():
    r = sh("--nonsense-flag")
    assert r.returncode == 1


def test_help_documents_reset_password():
    r = sh("--help")
    assert r.returncode == 0
    assert "reset-password" in r.stdout or "reset-password" in r.stderr


def test_reset_password_rejects_weak_passwords(tmp_path):
    """Same floor + placeholder block the panel applies at boot."""
    sb, _ = sandbox(tmp_path)
    for weak, hint in (("short", "at least 12"), ("change-me-please-123", "placeholder")):
        r = sh_sb(sb, "reset-password", "--admin-pass", weak)
        assert r.returncode == 1, r.stderr
        assert hint in r.stderr or "root" in r.stderr, r.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="reset-password itself requires root")
def test_reset_password_updates_env_and_survives_restart_failure(tmp_path):
    """Only the ADMIN_PASSWORD line changes (0600 kept, other lines intact)
    and a failed service restart is a warning, not a failed recovery."""
    sb, fake_opt = sandbox(tmp_path)
    install = Path(fake_opt)
    install.mkdir(parents=True)
    env = install / ".env"
    env.write_text(
        "HOST=0.0.0.0\n"
        "PORT=2095\n"
        "ADMIN_USERNAME=admin\n"
        "ADMIN_PASSWORD=old-password-123\n"
        "URLPATH=sekret\n"
        "JWT_SECRET_KEY=keep-me\n",
        encoding="utf-8",
    )
    env.chmod(0o600)

    # curl succeeds so the /health wait is instant; systemctl fails on purpose.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, rc in (("curl", 0), ("systemctl", 1)):
        tool = fake_bin / name
        tool.write_text(f"#!/bin/sh\nexit {rc}\n", encoding="utf-8")
        tool.chmod(0o755)

    r = sh_sb(
        sb,
        "reset-password",
        "--admin-pass",
        "brand-new-password",
        env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert r.returncode == 0, r.stderr
    text = env.read_text(encoding="utf-8")
    assert "ADMIN_PASSWORD=brand-new-password\n" in text
    assert "old-password-123" not in text
    for kept in ("HOST=0.0.0.0", "PORT=2095", "ADMIN_USERNAME=admin", "URLPATH=sekret", "JWT_SECRET_KEY=keep-me"):
        assert kept in text, f"lost {kept}"
    assert (env.stat().st_mode & 0o777) == 0o600
    # The new password never echoes back, and the restart failure is a warning.
    assert "brand-new-password" not in r.stdout + r.stderr
    assert "Could not restart" in r.stderr


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
    assert "Dry run — nothing changed (re-run without --dry-run to update/uninstall)" in content
    assert "Dry run — nothing changed (would back up data, fetch ${SRC}, rebuild if needed)" in content
    assert "Dry run — nothing changed (would stop the service" in content


def test_already_installed_menu_never_auto_runs_destructive_actions():
    """Enter/EOF/cancel must not start update or uninstall by default."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'tui_select "OVManager — panel"' in content
    assert 'quit      "Quit")' in content
    # Unmatched/cancelled selections return to the caller (or quit) only.
    assert "*)         return 0 ;;" in content


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
    # Keys stay private (600, owned by the container uid); only the cert is 644.
    assert "secure_tls_files" in content
    assert "chmod 600" in content
    assert "chmod 644 /etc/ssl/self-signed/privkey.pem" not in content
    assert ">/dev/stderr" in content  # build output must not pollute --json stdout


def test_repo_override_for_forks():
    """OVM_REPO redirects source downloads/update pulls to a fork."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'REPO="${OVM_REPO:-anonysec/OVManager}"' in content


def test_plain_http_flag_is_rejected():
    """--tls-none must fail fast: plain HTTP is no longer offered."""
    r = sh("--tls-none", "--dry-run")
    assert r.returncode != 0
    assert "Plain HTTP is not allowed" in r.stderr
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'TLS_MODE="none"' not in content


def test_start_menu_and_express_defaults():
    """A bare run offers Express/Custom/Update/Uninstall; Express asks only
    for the admin password and picks TLS self-signed."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    for label in ("Express", "Custom", "Update", "Uninstall"):
        assert label in content
    assert "panel_express_defaults()" in content
    assert 'tls="$(ask "TLS" "1")"' in content
    assert "None — HTTP only" not in content
    assert ': "${TLS_MODE:=self}"' in content


def test_same_server_node_offer_auto_registers():
    """End of install offers a same-server node; Express auto-registers it,
    Custom asks first; the OVNode repo can be overridden for forks."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "offer_same_server_node" in content
    assert "not recommended" in content.lower()
    assert "OVNODE_REPO:-anonysec/OVNode" in content
    assert "register_node_in_panel" in content
    assert 'confirm "Add it to the panel automatically now?"' in content
    # Node install runs the separate project's installer, never a bundled copy.
    assert "install.sh" in content and "install --json" in content


def test_terminal_command_and_tui_are_installed():
    """The installer copies itself to /usr/local/bin as ovmanager (+ ovm)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"' in content
    assert 'CLI_NAME="ovmanager"' in content
    assert 'CLI_ALIAS="ovm"' in content
    # copied on install and update, removed on uninstall
    assert content.count("install_cli") >= 3  # definition + do_install + do_update
    assert content.count("remove_cli") >= 2  # definition + do_uninstall
    # whiptail when present, colored fallback otherwise
    assert "command -v whiptail" in content
    assert "tui_select" in content


def test_tui_subcommands_documented():
    r = sh("help")
    assert r.returncode == 0
    output = r.stdout + r.stderr
    for token in (
        "start | stop | restart",
        "logs [N|-f]",
        "backup",
        "tls",
        "recovery",
        "reset-urlpath",
        "menu",
        "ovmanager (alias: ovm)",
    ):
        assert token in output, token


def test_menu_without_terminal_is_usage_error():
    """`menu` must not fall back to defaults and start installing."""
    r = sh("menu")
    assert r.returncode == 2
    assert "No terminal available" in r.stderr


def test_logs_command_never_crashes():
    r = sh("logs", "5")
    assert r.returncode == 0


def _function_tails(path):
    """[(name, last_line, closing_line)] for every multi-line function."""
    import re

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    out = []
    func = None
    body = []
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


def test_no_function_ends_with_a_failing_test():
    """`set -e` trap: a function whose last statement is `[[ ... ]] && ...`
    returns 1 when the test is false, which exits the whole installer. This
    was the Express admin-password bug (typing a password exited silently)."""
    import re

    offenders = [
        (name, tail, line)
        for name, tail, line in _function_tails(INSTALLER)
        if re.match(r"^\[\[.*\]\]\s*&&", tail)
    ]
    assert not offenders, offenders


def test_express_password_path_does_not_exit_early():
    """Entering a password must continue the installer, not return 1."""
    lines = Path(INSTALLER).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("panel_express_defaults()"))
    end = start
    while lines[end] != "}":
        end += 1
    source = "\n".join(lines[start : end + 1])

    def harness(password: str, expect_generated: int) -> str:
        return f"""set -Eeuo pipefail
    line() {{ :; }}
    step() {{ :; }}
    ask() {{ printf '%s' '{password}'; }}
    rand_path() {{ echo testpath; }}
    DEFAULT_PORT=2095; DEFAULT_USER=admin
    EXPRESS=0; MODE=""; PORT=""; PATH_SET=0; PATHPREFIX=""
    ADMIN_USER=""; TLS_MODE=""; ADMIN_PASS=""; GENERATED_PASS=0
    {source}
    panel_express_defaults
    [[ "$ADMIN_PASS" == '{password}' ]]
    [[ "$GENERATED_PASS" -eq {expect_generated} ]]
    """

    typed = subprocess.run(["bash", "-c", harness("long-enough-password", 0)], capture_output=True, text=True, timeout=30)
    assert typed.returncode == 0, typed.stderr
    blank = subprocess.run(["bash", "-c", harness("", 1)], capture_output=True, text=True, timeout=30)
    assert blank.returncode == 0, blank.stderr




def _extract_function(name: str) -> str:
    lines = Path(INSTALLER).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}()"))
    end = start
    while lines[end] != "}":
        end += 1
    return "\n".join(lines[start : end + 1])


def test_masked_password_echoes_stars_and_handles_backspace():
    source = _extract_function("_masked_read")
    harness = f"set -Eeuo pipefail\n{source}\n_masked_read\n"
    r = subprocess.run(
        ["bash", "-c", harness],
        input="ab\x7fc\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "ac"
    assert r.stderr.count("*") == 3  # a, b, c each echoed as a star
    assert "\b \b" in r.stderr  # backspace erased one star


def test_confirm_no_is_safe_by_default():
    source = _extract_function("confirm_no")
    template = (
        "set -Eeuo pipefail\nGR=''; NC=''\n"
        "can_prompt() {{ return {prompt}; }}\nYES={yes}\n"
        "_read_reply() {{ printf '%s' '{reply}'; }}\n{fn}\nconfirm_no 'Delete data?'\n"
    )
    fn = source
    cases = [("0", "0", "y", 0), ("0", "0", "Y", 0), ("0", "0", "", 1), ("0", "0", "n", 1), ("1", "0", "y", 1)]
    for prompt, yes, reply, expected in cases:
        r = subprocess.run(
            ["bash", "-c", template.format(prompt=prompt, yes=yes, reply=reply, fn=fn)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == expected, (prompt, yes, reply, r.returncode, r.stderr)


def test_uninstall_asks_about_data():
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'confirm_no "Also delete data and backups?" && PURGE=1' in content


def test_auto_backup_host_timer_wiring():
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "ovmanager-backup.timer" in content
    assert "ovmanager-backup.service" in content
    assert "backup --keep ${keep}" in content
    assert "auto-backup on|off|status" in content
    assert 'auto-backup) check_root; detect_os; auto_backup_cli "$AUTO_BACKUP_ACTION"' in content
    # /var/backups is pruned, so a daily timer cannot fill the disk.
    assert "prune_backups" in content


def test_default_node_name_is_ovnode():
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert ': "${NODE_NAME:=ovnode}"' in content
    assert 'node_name="$(ask "Node name" "ovnode")"' in content
    assert "default node-1" not in content


def test_same_server_node_offer_defaults_to_no():
    """A bare Enter must not install a VPN node (explicit yes required)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'confirm_no "Install a VPN node on this same server too?"' in content
    assert 'confirm "Install a VPN node on this same server too?" "n"' not in content


def test_same_server_offer_adopts_existing_node():
    """If OVNode is already installed, the offer registers that node instead
    of failing on 'already installed'."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'elif [[ "$rc" -eq 3 && -f /opt/ovnode/.env ]]' in content
    assert "env_get /opt/ovnode/.env API_KEY" in content
    assert 'register_node_in_panel "$node_name" "$node_key" "$node_port" "$node_tls"' in content
    assert 'node_tls="0"' in content
