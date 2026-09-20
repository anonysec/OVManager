# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Behavioral tests for install.sh: install / update / uninstall only.

Day-to-day operations (status, logs, backup, TLS, recovery) live in
manager.sh and are covered by tests/test_manager_sh.py. These tests never
get past validation or the dry-run guard, so they cannot touch the system.
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


def test_help_documents_installer_surface():
    """install.sh only does install/update/uninstall; the rest is ovm."""
    r = sh("--help")
    assert r.returncode == 0
    output = r.stdout + r.stderr
    for token in ("update", "uninstall", "--dry-run", "--admin-pass", "--tls 1", "ovm"):
        assert token in output, f"help missing {token}"
    for token in ("reset-password", "auto-backup", "reset-urlpath"):
        assert token not in output, f"help should not document manager op {token}"


def test_bad_tls_number_fails_fast():
    r = sh("--tls", "9", "--dry-run")
    assert r.returncode == 1
    assert "--tls needs 1, 2, 3 or 4" in r.stderr


def test_short_admin_password_rejected(tmp_path):
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "--admin-pass", "short")
    assert r.returncode == 1
    assert "at least 12" in r.stderr or "root" in r.stderr
    # 8-char passwords passed the installer but 422ed at the panel; now they
    # fail fast with the same 12-char floor the API enforces.
    r = sh_sb(sb, "-y", "--admin-pass", "eight888")
    assert r.returncode == 1
    assert "at least 12" in r.stderr or "root" in r.stderr


def test_install_rejects_placeholder_password_fast(tmp_path):
    """A 13-char password containing a placeholder must fail in the
    installer — not install and then crash-loop at first boot."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "--admin-pass", "my-admin12345")
    assert r.returncode == 1
    assert "placeholder" in r.stderr or "root" in r.stderr


def test_interactive_prompts_validate_password_with_retries():
    """Express and Custom re-prompt on weak passwords instead of dying."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "prompt_validate_admin_password" in content
    assert content.count("prompt_validate_admin_password") >= 3  # def + 2 callers


def test_unknown_option_fails():
    r = sh("--nonsense-flag")
    assert r.returncode == 1


def test_manager_ops_redirect_to_ovm():
    """status/logs/etc. are no longer installer commands — point at ovm."""
    for cmd in ("status", "logs", "backup", "tls", "recovery", "reset-password", "menu", "install"):
        r = sh(cmd)
        assert r.returncode == 1, cmd
        assert "moved to the manager" in r.stderr, cmd
        assert "ovm" in r.stderr, cmd


def test_dry_run_never_touches_live_flows():
    """Every destructive/live flow must honor --dry-run (regression: an
    early version ran a real update when /opt/ovmanager existed)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "Dry run — nothing changed (re-run without --dry-run to update/uninstall)" in content
    assert "Dry run — nothing changed (would back up data, fetch ${SRC}, rebuild if needed)" in content
    assert "Dry run — nothing changed (would stop the service" in content


def test_already_installed_menu_is_installer_only():
    """The installer's already-installed menu offers update/uninstall/quit —
    day-to-day ops moved to ovm."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'tui_select "OVManager — installer"' in content
    assert 'quit      "Quit")' in content
    # Unmatched/cancelled selections return to the caller (or quit) only.
    assert "*)         return 0 ;;" in content
    assert "use ovm" in content or "Manage the panel with: ovm" in content


def test_already_installed_menu_is_safe_by_default(tmp_path):
    """With an existing install dir and no tty, the menu must refuse to act
    (exit 2) — never default into update/uninstall."""
    sb, fake_opt = sandbox(tmp_path)
    os.makedirs(fake_opt)
    r = sh_sb(sb, "-y", "--admin-pass", "long-enough-password")
    assert r.returncode == 2
    assert "Already installed" in r.stderr


def test_already_installed_dry_run_is_noop(tmp_path):
    sb, fake_opt = sandbox(tmp_path)
    os.makedirs(fake_opt)
    r = sh_sb(sb, "--dry-run", "-y", "--admin-pass", "long-enough-password")
    assert r.returncode == 0
    assert "nothing changed" in r.stderr


def test_fresh_dry_run_json_shape(tmp_path):
    """Fresh-install dry-run prints the plan as a single JSON object."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(
        sb,
        "--dry-run",
        "-y",
        "--mode",
        "native",
        "--admin-pass",
        "long-enough-password",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)  # stdout is exactly one JSON object
    assert data["ok"] is True
    assert data["user"] == "admin"
    assert data["password"] == "long-enough-password"


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


def test_plain_http_flag_is_gone():
    """--tls-self/--tls-none are gone: --tls takes numbers 1-4 now."""
    r = sh("--tls-none", "--dry-run")
    assert r.returncode != 0
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'TLS_MODE="none"' not in content
    assert "--tls-self" not in content


def test_start_menu_is_express_or_custom():
    """A bare run offers Express/Custom only; update/uninstall are commands."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    for label in ("Express", "Custom"):
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


def test_installer_deploys_the_manager():
    """install.sh puts manager.sh on PATH as ovmanager (+ ovm) — never itself."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"' in content
    assert 'CLI_NAME="ovmanager"' in content
    assert 'CLI_ALIAS="ovm"' in content
    assert 'local src="${INSTALL_DIR}/manager.sh"' in content
    # refreshed on install and update, removed on uninstall
    assert content.count("install_cli") >= 3  # definition + do_install + do_update
    assert content.count("remove_cli") >= 2  # definition + do_uninstall
    # whiptail when present, colored fallback otherwise
    assert "command -v whiptail" in content
    assert "tui_select" in content


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


def test_express_password_path_does_not_exit_early():
    """Entering a password must continue the installer, not return 1."""
    lines = Path(INSTALLER).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("panel_express_defaults()"))
    end = start
    while lines[end] != "}":
        end += 1
    source = "\n".join(lines[start : end + 1])

    def harness(password: str, expect_generated: int) -> str:
        helpers = _extract_function("admin_password_problem") + "\n" + _extract_function(
            "prompt_validate_admin_password"
        )
        return f"""set -Eeuo pipefail
    line() {{ :; }}
    step() {{ :; }}
    warn() {{ :; }}
    die() {{ echo "DIE: $1" >&2; exit 1; }}
    ask() {{ printf '%s' '{password}'; }}
    rand_path() {{ echo testpath; }}
    DEFAULT_PORT=2095; DEFAULT_USER=admin
    EXPRESS=0; MODE=""; PORT=""; PATH_SET=0; PATHPREFIX=""
    ADMIN_USER=""; TLS_MODE=""; ADMIN_PASS=""; GENERATED_PASS=0
    {helpers}
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


def test_detect_os_preserves_app_version(tmp_path):
    """Regression: sourcing /etc/os-release must not clobber the app
    VERSION (os-release defines its own VERSION=...)."""
    probe = tmp_path / "probe.sh"
    fn = subprocess.run(
        ["sed", "-n", "/^detect_os() {/,/^}/p", INSTALLER],
        capture_output=True, text=True, timeout=30,
    ).stdout
    assert fn, "detect_os not found"
    probe.write_text(
        "set -u\n"
        'VERSION="9.9.9-probe"\n'
        'die() { echo "DIE: $1" >&2; exit 1; }\n'
        + fn
        + "\ndetect_os\n"
        'echo "VERSION=$VERSION"\n',
        encoding="utf-8",
    )
    r = subprocess.run(["bash", str(probe)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "VERSION=9.9.9-probe" in r.stdout
