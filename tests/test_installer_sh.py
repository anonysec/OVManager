# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Behavioral tests for install.sh: install / update / uninstall only.

Day-to-day operations (status, logs, backup, TLS, recovery) live in
manager.sh and are covered by tests/test_manager_sh.py. These tests never
get past validation or the dry-run guard, so they cannot touch the system.
"""

import json
import os
import re
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

    Every system location the installer writes is redirected — a full install
    also writes the systemd unit and the CLI symlink, and calling the real
    systemctl against them overwrites a live panel on this VPS. systemctl and
    the firewall tools are shimmed for the same reason.
    """
    fake_opt = tmp_path / "opt"
    fake_data = tmp_path / "data"
    fake_etc = tmp_path / "etc"
    fake_bin = tmp_path / "usr" / "local" / "bin"
    shim = tmp_path / "bin"
    # fake_opt / fake_data are left for the installer (and the tests) to create.
    for d in (fake_etc / "systemd" / "system", fake_bin, shim):
        d.mkdir(parents=True, exist_ok=True)
    src = INSTALLER_PATH.read_text(encoding="utf-8")
    src = (
        src.replace("/opt/ovmanager", str(fake_opt))
        .replace("/var/lib/ovmanager", str(fake_data))
        .replace("/etc/systemd/system", str(fake_etc / "systemd" / "system"))
        .replace("/etc/ssl", str(fake_etc / "ssl"))
        .replace("/etc/letsencrypt", str(fake_etc / "letsencrypt"))
        .replace('BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"', f'BIN_DIR="{fake_bin}"')
    )
    for tool in ("systemctl", "ufw", "firewall-cmd"):
        _write_shim(shim / tool, _SHIMS[tool])
    path = tmp_path / "install.sh"
    path.write_text(src, encoding="utf-8")
    return str(path), str(fake_opt)


def _write_shim(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


# A machine that has systemd but no OVManager service: is-active/is-enabled
# report "not installed" so the installer takes its normal fresh-install path,
# and every mutating call is recorded instead of executed.
_SHIMS = {
    "systemctl": """
printf 'systemctl %s\\n' "$*" >> "${SYSTEMCTL_LOG:-/dev/null}"
case "${1:-}" in
  is-active|is-enabled|is-failed) exit 3 ;;
  show) exit 0 ;;
  status) exit 3 ;;
  *) exit 0 ;;
esac
""",
    "ufw": """
printf 'ufw %s\\n' "$*" >> "${SYSTEMCTL_LOG:-/dev/null}"
[[ "${1:-}" == "status" ]] && echo "Status: inactive" && exit 0
exit 0
""",
    "firewall-cmd": """
printf 'firewall-cmd %s\\n' "$*" >> "${SYSTEMCTL_LOG:-/dev/null}"
exit 1
""",
}


def sh_sb(sandbox_installer, *args: str, env: dict | None = None):
    sandbox_env = {}
    root = Path(sandbox_installer).parent
    if root.name.startswith("tmp"):
        # Hermetic mode: no systemctl, no /usr/local/bin, no firewall changes.
        sandbox_env = {
            "OVM_BIN_DIR": str(root / "usr" / "local" / "bin"),
            "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        }
    full_env = {**os.environ, **sandbox_env, **(env or {})}
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


# Real system locations a full install would rewrite. Snapshotting them around
# every installer test turns "the test suite broke the live panel" into a loud,
# immediate failure instead of a service that starts from a tmp dir.
_PROTECTED_PATHS = (
    Path("/etc/systemd/system/ovmanager.service"),
    Path("/usr/local/bin/ovm"),
    Path("/usr/local/bin/ovmanager"),
)


@pytest.fixture(autouse=True)
def _system_paths_untouched():
    before = {p: (p.read_bytes() if p.exists() else None) for p in _PROTECTED_PATHS}
    yield
    for path, snapshot in before.items():
        current = path.read_bytes() if path.exists() else None
        assert current == snapshot, f"installer test modified the real {path}"


def test_installer_syntax():
    subprocess.run(["bash", "-n", INSTALLER], check=True)


def test_sandbox_install_never_touches_the_real_system(tmp_path):
    """Full-install path, hermetic: sandboxed unit + shimmed systemctl."""
    sb, fake_opt = sandbox(tmp_path)
    log = tmp_path / "systemctl.log"
    r = sh_sb(
        sb,
        "-y",
        "-p",
        "eight888",
        env={"SYSTEMCTL_LOG": str(log), "OVM_TLS": "none"},
    )
    unit = tmp_path / "etc" / "systemd" / "system" / "ovmanager.service"
    if unit.exists():
        body = unit.read_text(encoding="utf-8")
        assert str(fake_opt) in body
        assert str(tmp_path / "data") in body
        assert "/opt/ovmanager" not in body
    real_unit = Path("/etc/systemd/system/ovmanager.service")
    if real_unit.exists():
        assert str(fake_opt) not in real_unit.read_text(encoding="utf-8")
    if log.exists():
        assert "daemon-reload" in log.read_text(encoding="utf-8")
    assert r.returncode in (0, 1)


def test_help_documents_installer_surface():
    """install.sh only does install/update/uninstall; the rest is ovm."""
    r = sh("--help")
    assert r.returncode == 0
    output = r.stdout + r.stderr
    for token in ("update", "uninstall", "Install with Docker", "ovm", "--docker", "-v", "--json"):
        assert token in output, f"help missing {token}"
    for token in ("reset-password", "auto-backup", "reset-urlpath", "--dry-run", "--admin-pass", "--from-source"):
        assert token not in output, f"help should not document {token}"


def test_bad_tls_number_fails_fast():
    r = sh("--tls", "9")
    assert r.returncode == 1
    assert "--tls needs 1, 2, 3 or 4" in r.stderr


def test_bad_version_pin_fails_fast():
    r = sh("update", "-v", "notaversion")
    assert r.returncode == 1
    assert "Bad --version" in r.stderr


def test_short_admin_password_rejected(tmp_path):
    """Policy floor is 8 characters: below it fails, at it passes."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "-p", "short")
    assert r.returncode == 1
    assert "at least 8" in r.stderr or "root" in r.stderr
    r = sh_sb(sb, "-y", "-p", "seven77")
    assert r.returncode == 1
    assert "at least 8" in r.stderr or "root" in r.stderr
    # Exactly 8 characters satisfies the policy (fails later, on root/already-installed).
    r = sh_sb(sb, "-y", "-p", "eight888")
    assert "at least 8" not in r.stderr


def test_install_rejects_placeholder_password_fast(tmp_path):
    """A 13-char password containing a placeholder must fail in the
    installer — not install and then crash-loop at first boot."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "-p", "my-admin12345")
    assert r.returncode == 1
    assert "placeholder" in r.stderr or "root" in r.stderr


def test_default_install_generates_credentials_without_prompting():
    """The recommended flow always generates the password and URL path."""
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    source = _extract_function("panel_express_defaults")
    assert 'ADMIN_PASS="$(rand_pass)"' in source
    assert 'PATHPREFIX="$(rand_path)"' in source
    assert "ask " not in source
    assert "GENERATED_PASS=1" in source
    assert "prompt_validate_admin_password" in content  # retained for recovery/legacy validation


def test_unknown_option_fails():
    r = sh("--nonsense-flag")
    assert r.returncode == 1


def test_manager_ops_redirect_to_ovm():
    """status/logs/etc. are no longer installer commands — point at ovm."""
    for cmd in ("status", "logs", "backup", "tls", "recovery", "reset-password", "menu"):
        r = sh(cmd)
        assert r.returncode == 1, cmd
        assert "moved to the manager" in r.stderr, cmd
        assert "ovm" in r.stderr, cmd
    r = sh("install")
    assert r.returncode == 1
    assert "is the default" in r.stderr


def test_plan_prints_by_default():
    """No --dry-run flag exists anymore — the plan card prints on every
    mutating action instead."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "--dry-run)" not in content
    assert "print_plan()" in content
    # install, update and uninstall all show the plan first.
    assert content.count("print_plan") >= 3  # def + install/update callers (+ inline uninstall card)


def test_installer_uses_release_artifacts_and_published_docker_image_only():
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    compose = _extract_function("write_compose")
    assert "git clone" not in content
    assert "--from-source" not in content
    assert "npm run build" not in content
    assert "image: ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" in compose
    assert "build:" not in compose
    assert "docker compose -f \"$COMPOSE_FILE\" pull" in content
    assert "Release checksum file is missing" in content


def test_update_fails_over_on_health_failure():
    """Updates stage first, block writes, and restore code plus verified data."""
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    assert "snapshot_code" in content
    assert "update_safety_backup" in content
    assert "UPDATE_STAGE" in content and "UPDATE_PREVIOUS" in content
    assert "Update verification in progress" in (Path(INSTALLER).parent / "backend/app.py").read_text()
    assert "failing over" in content
    assert "restore_update_database" in content
    assert "failed_over" in content
    assert "recovery_required" in content


def test_recovery_handles_every_persisted_update_phase():
    source = _extract_function("do_recover_update")
    for phase in (
        "preflight",
        "staging",
        "activating",
        "verifying",
        "failing_over",
        "recovery_required",
        "failed_over",
        "committed",
    ):
        assert phase in source
    assert "Re-created the missing update maintenance marker" in source
    assert '"$reported" == "$target"' in source
    assert '"$reported" == "$from"' in source


def test_update_database_restore_verifies_bundle_and_preserves_mode(tmp_path):
    import hashlib
    import io
    import tarfile

    database = tmp_path / "ovmanager.db"
    database.write_bytes(b"new candidate data")
    database.chmod(0o640)
    old_data = b"safe pre-update database"
    digest = hashlib.sha256(old_data).hexdigest()
    bundle = tmp_path / "safety.ovmbak"
    members = {
        "panel.db": old_data,
        "manifest.json": json.dumps({"database_sha256": digest}).encode(),
        "checksums.sha256": f"{digest}  panel.db\n".encode(),
    }
    with tarfile.open(bundle, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    harness = _extract_function("restore_update_database") + f'\nrestore_update_database "{bundle}" "{database}"\n'
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert database.read_bytes() == old_data
    assert database.stat().st_mode & 0o777 == 0o640

    # Tampering with either checksum source must make restoration fail.
    bad_bundle = tmp_path / "bad.ovmbak"
    members["checksums.sha256"] = b"0" * 64 + b"  panel.db\n"
    with tarfile.open(bad_bundle, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    bad = subprocess.run(
        ["bash", "-c", _extract_function("restore_update_database") + f'\nrestore_update_database "{bad_bundle}" "{database}"\n'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert bad.returncode != 0


def test_update_journal_is_private_and_atomic(tmp_path):
    source = _extract_function("update_state")
    state = tmp_path / "update-state.json"
    harness = (
        "set -Eeuo pipefail\n"
        f'UPDATE_STATE="{state}"; DATA_DIR="{tmp_path}"; VERSION=2.0.0\n'
        + source
        + '\nupdate_state verifying 1.2.7 2.0.0 /safe/pre-update.ovmbak\n'
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    data = json.loads(state.read_text())
    assert data["phase"] == "verifying"
    assert data["from_version"] == "1.2.7"
    assert data["to_version"] == "2.0.0"
    assert data["safety_backup"] == "/safe/pre-update.ovmbak"
    assert state.stat().st_mode & 0o777 == 0o600


def test_snapshot_rotation_keeps_two(tmp_path):
    """snapshot_code keeps the newest 2 code snapshots, pruning older ones."""
    src = _extract_function("snapshot_code")
    helpers = (
        "set -Eeuo pipefail\n"
        "die() { echo \"DIE: $1\" >&2; exit 1; }\n"
        "step() { :; }\ninfo() { :; }\nwarn() { :; }\n"
    )
    harness = (
        helpers + src.replace("/var/backups", str(tmp_path))
        + f'\nmkdir -p {tmp_path}/app\n'
        + f'\nsnapshot_code {tmp_path}/app panel 2 >/dev/null\nsleep 1.1\n'
        + f'snapshot_code {tmp_path}/app panel 2 >/dev/null\nsleep 1.1\n'
        + f'snapshot_code {tmp_path}/app panel 2 >/dev/null\n'
        + f'ls {tmp_path}/panel-code-*.tar.gz | wc -l\n'
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2", r.stdout


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
    r = sh_sb(sb, "-y", "-p", "long-enough-password")
    assert r.returncode == 2
    assert "Already installed" in r.stderr


def test_update_without_install_dir_fails(tmp_path):
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "update", "-y")
    assert r.returncode != 0


def test_emit_json_shape():
    """emit_json prints the install result as a single JSON object."""
    import re

    ver = re.search(r'^VERSION="([^"]+)"', Path(INSTALLER).read_text(encoding="utf-8"), re.M).group(1)
    helpers = (
        "set -Eeuo pipefail\n"
        "die() { echo \"DIE: $1\" >&2; exit 1; }\n"
        "panel_url() { printf 'https://127.0.0.1:2095/abc/'; }\n"
    )
    harness = (
        helpers + _extract_function("emit_json") + "\n"
        'MODE=native ADMIN_USER=admin ADMIN_PASS=long-enough-password '
        'INSTALL_DIR=/opt/ovmanager DATA_DIR=/var/lib/ovmanager TLS_MODE=self '
        f'PORT=2095 PATHPREFIX=abc GENERATED_PASS=0 VERSION={ver} BACKUP_ENCRYPT_KEY=backup-key JSON=1 emit_json 1\n'
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)  # stdout is exactly one JSON object
    assert data["ok"] is True
    assert data["user"] == "admin"
    assert data["password"] == "long-enough-password"
    assert data["version"] == ver
    assert data["backup_recovery_key"] == "backup-key"


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
    r = sh("--tls-none")
    assert r.returncode != 0
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "--tls-self" not in content


def test_start_menu_is_install_or_docker():
    """The front door uses beginner wording and generates secure defaults."""
    source = _extract_function("start_menu")
    assert "Install              " in source
    assert "Install with Docker" in source
    assert "Express" not in source
    assert "Custom" not in source
    assert 'MODE="native"; panel_express_defaults' in source
    assert 'MODE="docker"; panel_express_defaults' in source
    assert "0.${NC} Exit" in source


def test_no_bundled_node_offer():
    """The installer ships no same-server node flow — nodes are added from
    the panel or docs (keeps the installer small)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "offer_same_server_node" not in content
    assert "WANT_NODE" not in content


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


def _extract_function(name: str) -> str:
    """Extract a shell function body, including heredocs."""
    lines = Path(INSTALLER).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}()"))
    end = start
    heredoc = None
    while True:
        end += 1
        line = lines[end]
        if heredoc is None:
            match = re.search(r"<<-?\s*['\"]?([A-Za-z_0-9]+)['\"]?", line)
            if match:
                heredoc = match.group(1)
            elif line == "}":
                break
        elif line == heredoc:
            heredoc = None
    return "\n".join(lines[start : end + 1])


def test_recommended_defaults_generate_password_and_path():
    """Recommended installation never asks for credentials or path."""
    source = _extract_function("panel_express_defaults")
    harness = f"""set -Eeuo pipefail
    rand_path() {{ echo generatedpath; }}
    rand_pass() {{ echo generated-password-123; }}
    DEFAULT_PORT=2095; DEFAULT_USER=admin
    EXPRESS=0; MODE=""; PORT=""; PATH_SET=0; PATHPREFIX=""
    ADMIN_USER=""; TLS_MODE=""; ADMIN_PASS=""; GENERATED_PASS=0
    {source}
    panel_express_defaults
    [[ "$ADMIN_PASS" == generated-password-123 ]]
    [[ "$PATHPREFIX" == generatedpath ]]
    [[ "$ADMIN_USER" == admin ]]
    [[ "$GENERATED_PASS" -eq 1 ]]
    [[ "$PATH_SET" -eq 1 ]]
    """
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


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


def test_interactive_verb_runs_wizard():
    """`interactive` forces the numbered wizard (Enter = default)."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert 'interactive)   ACTION="interactive"; shift ;;' in content
    assert "run_wizard_install()" in content


def test_release_downloads_follow_redirects():
    """github.com/download answers 302 to release-assets — curl needs -L,
    or every release install/update breaks."""
    with open(INSTALLER, encoding="utf-8") as f:
        content = f.read()
    assert "curl -fsSL -o" in content
    assert "curl -fsSLo" not in content


def test_entry_points_are_executable():
    """install.sh/manager.sh must carry +x in git — tarballs preserve it,
    and the manager execs $INSTALL_DIR/install.sh for update/uninstall."""
    for name in ("install.sh", "manager.sh"):
        path = INSTALLER_PATH.parent / name
        assert os.access(path, os.X_OK), f"{name} lost its executable bit"


def test_no_pages_url():
    """The installer is bootstrapped from raw.githubusercontent.com — the
    anonysec.github.io Pages URL is retired (it served stale scripts)."""
    repo = INSTALLER_PATH.parent
    for rel in ("README.md", "install.sh", "manager.sh"):
        assert "github.io" not in (repo / rel).read_text(encoding="utf-8"), rel
    for doc in (repo / "docs").glob("*.md"):
        assert "github.io" not in doc.read_text(encoding="utf-8"), doc.name


def test_release_stub_is_rejected_before_checksum(tmp_path):
    """A redirect stub saved as the tarball must fail as 'not a release
    archive' — never as a checksum mismatch (the v1.2.3 failure mode)."""
    stub = tmp_path / "stub.tar.gz"
    stub.write_text("<html>302 Found</html>", encoding="utf-8")
    real = tmp_path / "real.tar.gz"
    subprocess.run(["tar", "-czf", str(real), "-C", str(tmp_path), "stub.tar.gz"], check=True)
    harness = (
        _extract_function("is_release_archive") + "\n"
        f'is_release_archive "{stub}" && echo STUB-OK || echo STUB-BAD\n'
        f'is_release_archive "{real}" && echo REAL-OK || echo REAL-BAD\n'
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "STUB-BAD" in r.stdout and "REAL-OK" in r.stdout


def test_installer_menu_copy_uses_new_tui():
    """The front door has one numbered dialect and beginner-facing labels."""
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    source = _extract_function("start_menu")
    assert "OVManager Setup" in source
    assert "1.${NC} Install" in source
    assert "2.${NC} Install with Docker" in source
    assert "0.${NC} Exit" in source
    assert "How do you want to install?" not in source
    assert "Ready — save this login" in content


def test_safety_backup_falls_back_without_maintenance_module(tmp_path):
    """Updates from releases predating backend.routers.maintenance must
    still produce a verified .ovmbak (defect: Step 1/6 died on old trees)."""
    import sqlite3

    fake_install = tmp_path / "install"
    fake_install.mkdir()
    fake_data = tmp_path / "data"
    fake_data.mkdir()
    db = fake_data / "ovmanager.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("PRAGMA user_version=10")
    con.commit()
    con.close()
    harness = (
        "die() { echo \"DIE: $1\" >&2; exit 1; }\n"
        "warn() { echo \"WARN: $1\" >&2; }\nstep() { :; }\ninfo() { :; }\n"
        + _extract_function("update_safety_backup")
        + "\n" + _extract_function("legacy_safety_bundle")
        + f'\nMODE=native INSTALL_DIR="{fake_install}" DATA_DIR="{fake_data}"\n'
        + 'update_safety_backup 1.2.6\n'
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    bundles = sorted((fake_data / "backups").glob("ovmanager-pre-update-*.ovmbak"))
    assert len(bundles) == 1, r.stdout
    assert bundles[0].stat().st_mode & 0o777 == 0o600
    # The fallback bundle must restore through the same verified path.
    out_db = tmp_path / "restored.db"
    restore = (
        _extract_function("restore_update_database")
        + f'\nDATA_DIR="{fake_data}"\nrestore_update_database "{bundles[0]}" "{out_db}"\n'
    )
    r2 = subprocess.run(["bash", "-c", restore], capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stderr
    con = sqlite3.connect(out_db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        con.close()


def test_db_restore_needed_skips_untouched_database(tmp_path):
    """Failover restores the database only when the candidate migrated it
    (defect: unconditional restore rewrote a healthy database every time)."""
    import sqlite3

    fake_data = tmp_path / "data"
    fake_data.mkdir()
    db = fake_data / "ovmanager.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA user_version=11")
    con.commit()
    con.close()
    helpers = (
        "die() { echo \"DIE: $1\" >&2; exit 1; }\n"
        "warn() { :; }\nstep() { :; }\ninfo() { :; }\n"
    )
    mk = (
        helpers + _extract_function("legacy_safety_bundle")
        + f'\nMODE=native DATA_DIR="{fake_data}"\nlegacy_safety_bundle 1.2.7 >/dev/null\n'
    )
    r = subprocess.run(["bash", "-c", mk], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    (bundle,) = sorted((fake_data / "backups").glob("*.ovmbak"))
    check = (
        _extract_function("db_restore_needed")
        + f'\nDATA_DIR="{fake_data}"\nif db_restore_needed "{bundle}"; then echo NEEDS; else echo SKIP; fi\n'
    )
    r2 = subprocess.run(["bash", "-c", check], capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, r2.stderr
    assert "SKIP" in r2.stdout
    con = sqlite3.connect(db)
    con.execute("PRAGMA user_version=12")
    con.commit()
    con.close()
    r3 = subprocess.run(["bash", "-c", check], capture_output=True, text=True, timeout=30)
    assert r3.returncode == 0, r3.stderr
    assert "NEEDS" in r3.stdout


def test_write_env_skips_branch_only_keys_on_old_trees(tmp_path):
    """Fresh installs of older releases must not get .env keys their
    backend rejects (defect: BACKUP_ENCRYPT_KEY crash-looped v1.2.7)."""
    fake_install = tmp_path / "install"
    (fake_install / "backend").mkdir(parents=True)
    (fake_install / "backend" / "config.py").write_text("class Setting: pass\n", encoding="utf-8")
    harness = (
        "die() { echo \"DIE: $1\" >&2; exit 1; }\nstep() { :; }\ninfo() { :; }\n"
        + _extract_function("write_env") + "\n" + _extract_function("fernet_key")
        + '\nMODE=native PORT=2095 PATHPREFIX=abc ADMIN_USER=admin ADMIN_PASS=long-enough-password\n'
        + f'PUBLIC_URL="" TLS_KEY="" TLS_CERT="" DATA_DIR="{tmp_path}" INSTALL_DIR="{fake_install}"\n'
        + "write_env >/dev/null\n"
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    env = (fake_install / ".env").read_text(encoding="utf-8")
    assert "BACKUP_ENCRYPT_KEY" not in env
    (fake_install / "backend" / "config.py").write_text("BACKUP_ENCRYPT_KEY = None\n", encoding="utf-8")
    r2 = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, r2.stderr
    env2 = (fake_install / ".env").read_text(encoding="utf-8")
    assert "BACKUP_ENCRYPT_KEY=" in env2


def test_recover_update_restarts_never_activated_tree():
    """A kill before the activation rename must restart the intact tree,
    not die for a missing previous directory (defect, verified live)."""
    source = _extract_function("do_recover_update")
    assert "never activated" in source
    assert '[[ -d "$UPDATE_PREVIOUS" ]] || {' in source


def test_systemd_unit_reports_clean_stop():
    """uv exits 143 on SIGTERM: the unit must map it to inactive, not
    failed, so status and doctor report stopped panels truthfully."""
    source = _extract_function("write_systemd_unit")
    assert "SuccessExitStatus=143" in source


def test_candidate_version_reads_inside_container_for_docker():
    """Host-side /health never discloses a version to Docker callers
    (loopback-only), so every Docker update failed verification (defect:
    Step 5/6 always failed over in docker mode)."""
    source = _extract_function("candidate_version")
    assert "docker exec ovmanager" in source
    assert "backend.version" in source


def test_installer_design_language_matches_node():
    """Anti-divergence: the panel installer shares the node's menu/card
    language. The node suite pins the same list — update both together."""
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    for token in (
        "Setup${NC}",
        "1.${NC} Install",
        "2.${NC} Install with Docker",
        "0.${NC} Exit",
        "Cancelled. No changes were made.",
        "installer${NC}",
        "up and running in a few minutes",
        "Step 1/4",
        "verified release",
        "Ready — save this login",
    ):
        assert token in content, f"design drift: {token}"
    for retired in (
        "How do you want to install?",
        "Choose every option yourself",
    ):
        assert retired not in content, f"retired wording back: {retired}"


def test_no_command_substitution_in_unit_heredoc():
    """Regression: an unquoted heredoc executes backticks in its body. A
    comment with `ovm stop` inside the UNIT heredoc ran the manager on
    every fresh install (command not found). No unescaped backticks in
    any unquoted heredoc body."""
    import re

    for path in (INSTALLER_PATH, INSTALLER_PATH.parent / "manager.sh", INSTALLER_PATH.parent / "lib" / "common.sh"):
        lines = path.read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            m = re.search(r"<<-?\s*([A-Z_][A-Z0-9_]*)\s*$", lines[i])
            if m and not re.search(r"<<-?\s*'", lines[i]):
                delim = m.group(1)
                j = i + 1
                while j < len(lines) and lines[j].strip() != delim:
                    line = lines[j]
                    assert not re.search(r"(?<!\\)`", line), (
                        f"{path.name}:{j + 1} unescaped backtick in {delim} heredoc: {line.strip()}"
                    )
                    j += 1
                i = j
            i += 1


def test_native_unit_creates_private_files_by_default():
    """Regression: a fresh native install started with a world-readable
    database (0644) until `ovm doctor --fix` corrected it. The unit must
    set a restrictive umask so data is private from the first byte."""
    source = _extract_function("write_systemd_unit")
    assert "UMask=0077" in source
    # The data dir is still created private for native installs.
    assert 'chmod 700 "$DATA_DIR"' in _extract_function("do_install")


def test_banner_tagline_only_for_fresh_install():
    """The tagline advertises a fresh install; on update/uninstall it reads
    as if work were about to start."""
    source = _extract_function("banner")
    assert 'install) subtitle="Secure VPN panel — up and running in a few minutes"' in source
    assert '*)      subtitle="Secure VPN panel"' in source


def test_generated_password_is_twelve_characters():
    """Generated passwords are 12 characters: short enough to retype, well
    above the 8-character policy minimum."""
    src = _extract_function("rand_pass")
    assert "head -c 12" in src
    assert "head -c 20" not in src


def test_password_policy_minimum_is_eight():
    """Owner password policy is >= 8 characters across installer, lib,
    manager and the config message."""
    for path in (INSTALLER_PATH, INSTALLER_PATH.parent / "lib" / "common.sh"):
        content = path.read_text(encoding="utf-8")
        assert '[[ ${#pass} -ge 8 ]]' in content, path.name
        assert "at least 8 characters" in content, path.name
    cfg = (INSTALLER_PATH.parent / "backend" / "config.py").read_text(encoding="utf-8")
    assert ">=8 chars" in cfg


def test_backup_key_not_printed_at_install():
    """The recovery key is install noise; it belongs in Settings -> Backups
    when the encrypted remote copy is switched on."""
    content = INSTALLER_PATH.read_text(encoding="utf-8")
    card = content.split("success_card()")[1].split("\n}")[0]
    assert "Backup key" not in card
