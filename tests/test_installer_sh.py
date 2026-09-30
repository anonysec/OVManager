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
LIB_DIR = INSTALLER_PATH.parent / "scripts" / "lib"
# install.sh sources the libs in this order (see _libs_install); a helper it
# calls now lives in one of these files rather than in install.sh itself.
LIB_FILES = tuple(sorted(LIB_DIR.glob("*.sh")))
INSTALL_DIR = "/opt/ovmanager"
SETSID = shutil.which("setsid")


def _installer_source() -> str:
    """install.sh plus the libs it sources — what the installer actually runs.

    Content assertions scan this rather than install.sh alone: a helper that
    moved into scripts/lib is still part of the installer.
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in (INSTALLER_PATH, *LIB_FILES))


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
    # /var/backups holds the code snapshots, the unit snapshots and the
    # offsite staging. Nothing redirected it before 1.0.25, but no test reached
    # a code path that wrote there; snapshot_unit does, and a test that left a
    # unit file in the real /var/backups would be a mess to clean up.
    fake_backups = tmp_path / "backups"
    shim = tmp_path / "bin"
    for d in (fake_etc / "systemd" / "system", fake_bin, shim, fake_backups):
        d.mkdir(parents=True, exist_ok=True)

    def rewrite(text: str) -> str:
        return (
            text.replace("/opt/ovmanager", str(fake_opt))
            .replace("/var/lib/ovmanager", str(fake_data))
            .replace("/etc/systemd/system", str(fake_etc / "systemd" / "system"))
            .replace("/etc/ssl", str(fake_etc / "ssl"))
            .replace("/etc/letsencrypt", str(fake_etc / "letsencrypt"))
            .replace("/var/backups", str(fake_backups))
            .replace('BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"', f'BIN_DIR="{fake_bin}"')
            # The panel's port is validated on every install path now, so a test
            # that inherited the real DEFAULT_PORT would pass or fail depending on
            # whether something happened to be listening on it. Two of these tests
            # read the developer's own panel as "port busy" and never reached the
            # assertion they were written for. Fixed port, asserted free below.
            .replace("DEFAULT_PORT=2095", "DEFAULT_PORT=20950")
        )

    src = rewrite(INSTALLER_PATH.read_text(encoding="utf-8"))
    # install.sh fetches and sources scripts/lib at startup, so the sandbox
    # brings its own — rewritten the same way. Without the copy the installer
    # would fetch over the network, and a verbatim copy would let a sandboxed
    # install reach the real /var/backups, /etc/ssl and /etc/letsencrypt.
    libdir = tmp_path / "scripts" / "lib"
    libdir.mkdir(parents=True, exist_ok=True)
    for lib in LIB_FILES:
        (libdir / lib.name).write_text(rewrite(lib.read_text(encoding="utf-8")), encoding="utf-8")
    # Fail loudly rather than silently: if 20950 is in use the suite is
    # measuring the host again.
    import socket as _socket

    probe = _socket.socket()
    try:
        probe.bind(("127.0.0.1", 20950))
    except OSError as exc:  # pragma: no cover
        raise AssertionError(f"sandbox port 20950 is in use: {exc}") from exc
    finally:
        probe.close()
    for tool in ("systemctl", "ufw", "firewall-cmd", *ACCOUNT_TOOLS):
        _write_shim(shim / tool, _SHIMS[tool])
    path = tmp_path / "install.sh"
    path.write_text(src, encoding="utf-8")
    return str(path), str(fake_opt)


def _write_shim(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


# Since 1.0.25 an install provisions a service account and hands it the files
# it needs, so the sandbox shims those too. Without this the sandboxed install
# would useradd against the real host, and as a non-root runner that failure
# aborts the install early — quietly turning a test of the full install path
# into a test of the failure path. The shims log their arguments so the tests
# can assert what the installer *asked for*.
ACCOUNT_TOOLS = ("useradd", "chown", "chgrp")

_ACCOUNT_SHIM = """
printf '%s %s\\n' "$(basename "$0")" "$*" >> "${ACCOUNT_LOG:-/dev/null}"
exit 0
"""

_SHIMS = {
    "useradd": _ACCOUNT_SHIM,
    "chown": _ACCOUNT_SHIM,
    "chgrp": _ACCOUNT_SHIM,
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


_PROTECTED_PATHS = (
    Path("/etc/systemd/system/ovmanager.service"),
    Path("/usr/local/bin/ovm"),
    Path("/usr/local/bin/ovmanager"),
)


def _snapshot(path: Path):
    """Bytes of a protected path, for the before/after comparison.

    Tolerates an unreadable file as well as an absent one. A non-root runner
    cannot read a root-owned systemd unit, and raising there turned every test
    in this file into an error. CI has no unit file at all, which is why this
    only appeared when running the suite as nobody on a machine that has a
    real install.

    The cost is honest: where the unit is unreadable this guard protects
    nothing. It never claims to have checked, and CI is in that position
    already.
    """
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except PermissionError:
        return "unreadable"


@pytest.fixture(autouse=True)
def _system_paths_untouched():
    """Assert the real system paths are untouched — and put them back if not.

    It restores before failing, not just fails. A test in this file once wrote
    a broken unit to the real /etc/systemd/system/ovmanager.service; the panel
    kept serving on its already-loaded config, so the damage was invisible until
    the next restart — and because the first corrupting run had already made the
    baseline wrong, every later run compared broken against broken and passed.
    Restoring means a mistake costs one failing test instead of the box.
    """
    before = {p: _snapshot(p) for p in _PROTECTED_PATHS}
    yield
    damaged = [p for p, snapshot in before.items() if _snapshot(p) != snapshot]
    for path in damaged:
        snapshot = before[path]
        try:
            if snapshot is None:
                path.unlink(missing_ok=True)
            elif isinstance(snapshot, bytes):
                path.write_bytes(snapshot)
        except OSError:  # a non-root runner cannot put a root file back
            pass
    assert not damaged, f"installer test modified the real {damaged}; restored"


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
    # _snapshot rather than exists()+read_text: a non-root runner can see the
    # unit but not read it, and this assertion is the one that would catch a
    # sandboxed install overwriting the real unit.
    real_body = _snapshot(real_unit)
    if isinstance(real_body, bytes):
        assert str(fake_opt).encode() not in real_body
    if log.exists():
        assert "daemon-reload" in log.read_text(encoding="utf-8")
    assert r.returncode in (0, 1)


def test_help_documents_installer_surface():
    """install.sh only does install/update/uninstall; the rest is ovm."""
    r = sh("--help")
    assert r.returncode == 0
    output = r.stdout + r.stderr
    for token in ("update", "uninstall", "Install with Docker", "ovm", "--docker", "-v"):
        assert token in output, f"help missing {token}"
    for token in (
        "reset-password",
        "auto-backup",
        "reset-urlpath",
        "--dry-run",
        "--admin-pass",
        "--from-source",
        "--json",
    ):
        assert token not in output, f"help should not document {token}"


def test_bad_tls_number_fails_fast():
    r = sh("--tls", "9")
    assert r.returncode == 1
    assert "--tls needs 1, 2, 3 or 4" in r.stderr


def test_bad_version_pin_fails_fast():
    r = sh("update", "-v", "notaversion")
    assert r.returncode == 1
    assert "Bad --version" in r.stderr


def test_version_pinning_accepts_a_suffix_and_an_optional_v():
    """A pre-release is installed by name. The tag is "v" + the version (see
    release_url), so 1.2.3-rc1 and v1.2.3-rc1 name the same release, and a bare
    semver works too. Checked against the real function rather than by running
    the installer, which would fetch over the network for every valid value."""
    accepted = [
        "1.2.3",
        "v1.2.3",
        "10.20.30",
        "v10.20.30",
        "1.2.3-rc1",
        "v1.2.3-rc1",
        "1.2.3-rc.1",
        "1.2.3+build5",
        "1.2.3-rc1+build5",
    ]
    rejected = [
        "not-a-version",
        "notaversion",
        "1.2",
        "1",
        "v",
        "1.2.3.4",
        "1.2.3-",
        "1.2.3+",
        "main",
        "1.2.3 rc1",
        "",
        "v1.2.3-rc1 ",
    ]
    script = (
        "set -u\n"
        + _extract_function("valid_release_version")
        + "\n"
        + "\n".join(f"valid_release_version '{v}' && echo ok || echo no" for v in accepted + rejected)
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.stdout.split() == ["ok"] * len(accepted) + ["no"] * len(rejected), (
        list(zip(accepted + rejected, r.stdout.split(), strict=True)),
        r.stderr,
    )


def test_short_admin_password_rejected(tmp_path):
    """The installer no longer takes an owner password, and never pretends to.

    It used to refuse a weak -p before doing any work; the credential is now
    chosen in the browser, where the panel endpoint applies the same policy
    (tests/test_owner_claim.py). What the installer must not do is accept the
    flag silently: -p is deprecated, and an operator who passed one is told the
    value is ignored rather than left believing it took effect.
    """
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "-p", "short")
    assert "-p, --pass is deprecated" in r.stderr
    assert "the owner password is set in the browser" in r.stderr
    # The password never reaches a variable, so no policy check can fire on it.
    assert "at least 8" not in r.stderr


def test_pass_environment_variables_are_reported_not_swallowed(tmp_path):
    """OVM_PASS/OVM_ADMIN_PASS are deprecated too — say so instead of ignoring."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", env={"OVM_PASS": "a-strong-password-123"})
    assert "OVM_PASS / OVM_ADMIN_PASS is deprecated" in r.stderr


def test_password_policy_floor_is_eight_characters():
    """The floor itself: 7 rejected, 8 accepted, per the shared policy lib."""
    import subprocess

    lib = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "policy.sh"
    out = subprocess.run(
        ["bash", "-c", 'source "$1"; admin_password_problem "$2"', "_", str(lib), "seven77"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "at least 8" in out.stdout
    out = subprocess.run(
        ["bash", "-c", 'source "$1"; admin_password_problem "$2"', "_", str(lib), "eight888"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.stdout == "", out.stdout


def test_install_rejects_placeholder_password_fast(tmp_path):
    """A 13-char password containing a placeholder must fail in the
    installer — not install and then crash-loop at first boot."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "-p", "my-admin12345")
    assert r.returncode == 1
    assert "placeholder" in r.stderr or "root" in r.stderr


def test_default_install_generates_the_panel_path_and_no_credential():
    """The recommended flow generates the private URL path, and nothing else.

    There is no owner password to generate any more: the install prints a
    one-time claim key and the browser turns it into the credential (design
    decision 4). A generated password here would be a credential with no owner.
    """
    source = _extract_function("panel_express_defaults")
    assert 'PATHPREFIX="$(rand_path)"' in source
    assert "ask " not in source
    assert "ADMIN_PASS" not in source
    assert "GENERATED_PASS" not in _installer_source(), "no install-time password survives"
    assert "prompt_validate_admin_password" in _installer_source()  # reset-password still validates


def test_unknown_option_fails():
    r = sh("--nonsense-flag")
    assert r.returncode == 1


# ── The three-flag surface, as a deprecation release ───────────────────
# Decision 3 keeps -y/--yes, --docker, -h/--help. Everything else still works
# for now, and each says one line naming what replaces it. The flags are cut in
# a later release; until then "it still works" has to be asserted, not assumed.
CUT_FLAGS = {
    ("-p", "hunter2hunter2"): ("-p, --pass", "claim key"),
    ("--mode", "native"): ("--mode", "OVM_MODE"),
    ("--tls", "2"): ("--tls", "OVM_TLS"),
    ("--tls-domain", "example.com"): ("--tls-domain", "OVM_TLS_DOMAIN"),
    ("--tls-key", "/tmp/key.pem"): ("--tls-key", "OVM_TLS_KEY"),
    ("--tls-cert", "/tmp/cert.pem"): ("--tls-cert", "OVM_TLS_CERT"),
    ("-i",): ("-i", "'interactive'"),
}


def _parse_args(stmt: str) -> subprocess.CompletedProcess:
    """Run one parse_args call in-process, the way install.sh sources it.

    Sourcing defines the functions without running main, so a flag can be
    exercised without an install — and a die() (which exits) is visible as a
    non-zero return code rather than as a sandbox that never starts.
    """
    return subprocess.run(
        ["bash", "-c", f'set -Eeuo pipefail; source "{INSTALLER}" >/dev/null; {stmt}'],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize("flags", sorted(CUT_FLAGS, key=lambda f: f[0]))
def test_cut_flags_warn_and_still_work(flags):
    expected, replacement = CUT_FLAGS[flags]
    r = _parse_args("parse_args " + " ".join(f"'{f}'" for f in flags))
    assert r.returncode == 0, (flags, r.stderr)
    assert f"{expected} is deprecated" in r.stderr, (flags, r.stderr)
    assert replacement in r.stderr, (flags, r.stderr)
    assert r.stdout == "", "warnings belong on stderr, never in the piped output"


def test_the_deprecated_mode_flag_still_sets_the_mode():
    """`--mode docker` must still choose Docker, not merely print a warning."""
    r = _parse_args("parse_args --mode docker; printf '%s\\n' \"$MODE\"")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "docker", r.stdout


def test_the_deprecated_tls_flag_still_sets_the_mode():
    r = _parse_args("parse_args --tls 3; printf '%s\\n' \"$TLS_MODE\"")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "le-ip", r.stdout


def test_the_deprecated_pass_flag_does_not_set_a_credential():
    """It works in the sense that it is accepted — and changes nothing.

    Honouring a password here would keep a credential in argv and in the
    operator's scrollback, which is exactly what decision 4 removes.
    """
    r = _parse_args("parse_args -p hunter2hunter2; printf '[%s]\\n' \"${ADMIN_PASS:-unset}\"")
    assert r.returncode == 0, r.stderr
    assert "[unset]" in r.stdout


@pytest.mark.parametrize("flags", [("-y",), ("--docker",), ("--purge",), ("-v", "v1.0.1")])
def test_kept_flags_do_not_warn(flags):
    """-y/--docker are the surface; --purge and -v belong to uninstall/update."""
    r = _parse_args("parse_args " + " ".join(f"'{f}'" for f in flags))
    assert r.returncode == 0, (flags, r.stderr)
    assert "deprecated" not in r.stderr, (flags, r.stderr)


def test_help_leads_with_the_three_flags_and_marks_the_rest_deprecated():
    r = sh("--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    options = out.split("OPTIONS", 1)[1].split("DEPRECATED", 1)[0]
    for kept in ("-y, --yes", "--docker", "-h, --help"):
        assert kept in options, f"help must lead with {kept}"
    deprecated = out.split("DEPRECATED", 1)[1]
    for cut in ("-p, --pass", "--mode", "--tls-domain", "-i"):
        assert cut in deprecated, f"{cut} must be listed as deprecated"
        # Anchored at a line start: "-i" is also a substring of "le-ip".
        assert f"\n  {cut}" not in options, f"{cut} is not part of the three-flag surface"


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
    content = _installer_source()
    assert "--dry-run)" not in content
    assert "print_plan()" in content
    assert content.count("print_plan") >= 3  # def + install/update callers (+ inline uninstall card)


def test_installer_uses_release_artifacts_and_published_docker_image_only():
    content = _installer_source()
    compose = _extract_function("write_compose")
    assert "git clone" not in content
    assert "--from-source" not in content
    assert "npm run build" not in content
    assert "image: ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" in compose
    assert "build:" not in compose
    assert 'docker compose -f "$COMPOSE_FILE" pull' in content
    assert "Release checksum file is missing" in content


def test_update_fails_over_on_health_failure():
    """Updates stage first, block writes, and restore code plus verified data."""
    content = _installer_source()
    assert "snapshot_code" in content
    assert "update_safety_backup" in content
    assert "UPDATE_STAGE" in content and "UPDATE_PREVIOUS" in content
    assert "Update verification in progress" in (Path(INSTALLER).parent / "backend/middlewares.py").read_text()
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
        + "\nupdate_state verifying 1.2.7 2.0.0 /safe/pre-update.ovmbak\n"
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
    helpers = 'set -Eeuo pipefail\ndie() { echo "DIE: $1" >&2; exit 1; }\nstep() { :; }\ninfo() { :; }\nwarn() { :; }\n'
    harness = (
        helpers
        + src.replace("/var/backups", str(tmp_path))
        + f"\nmkdir -p {tmp_path}/app\n"
        + f"\nsnapshot_code {tmp_path}/app panel 2 >/dev/null\nsleep 1.1\n"
        + f"snapshot_code {tmp_path}/app panel 2 >/dev/null\nsleep 1.1\n"
        + f"snapshot_code {tmp_path}/app panel 2 >/dev/null\n"
        + f"ls {tmp_path}/panel-code-*.tar.gz | wc -l\n"
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2", r.stdout


def test_already_installed_menu_is_installer_only():
    """The installer's already-installed menu offers update/uninstall/quit —
    day-to-day ops moved to ovm."""
    content = _installer_source()
    assert 'tui_select "OVManager — installer"' in content
    assert 'quit      "Quit")' in content
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


def test_docker_data_dir_and_perms_are_container_safe():
    """Fresh Docker installs crash-looped twice: .env carried the HOST data
    path into the container (appuser mkdir → PermissionError), then the
    root-owned host dir masked /app/data, then unreadable TLS keys.
    Pin the three guards: container DATA_DIR, host chown, readable certs."""
    content = _installer_source()
    assert '[[ "$MODE" == "docker" ]] && data_dir="/app/data"' in content
    assert 'chown -R 1000:1000 "$DATA_DIR"' in content
    assert "secure_tls_files" in content
    assert "chmod 600" in content
    # The paths became locals, so pinning a literal path only passed because
    # the literal was gone: the key must never be loosened to 644 (world
    # readable, and the panel's service account is not its owner), while the
    # certificate is public and must stay so.
    assert 'chmod 644 "$key"' not in content
    assert 'chmod 644 "$cert"' in content


def test_repo_override_for_forks():
    """OVM_REPO redirects source downloads/update pulls to a fork."""
    content = _installer_source()
    assert 'REPO="${OVM_REPO:-anonysec/OVManager}"' in content


def test_plain_http_flag_is_gone():
    """--tls-self/--tls-none are gone: --tls takes numbers 1-4 now."""
    r = sh("--tls-none")
    assert r.returncode != 0
    content = _installer_source()
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
    content = _installer_source()
    assert "offer_same_server_node" not in content
    assert "WANT_NODE" not in content


def test_installer_deploys_the_manager():
    """install.sh puts manager.sh on PATH as ovmanager (+ ovm) — never itself."""
    content = _installer_source()
    assert 'BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"' in content
    assert 'CLI_NAME="ovmanager"' in content
    assert 'CLI_ALIAS="ovm"' in content
    assert 'local src="${INSTALL_DIR}/manager.sh"' in content
    assert content.count("install_cli") >= 3  # definition + do_install + do_update
    assert content.count("remove_cli") >= 2  # definition + do_uninstall
    assert "command -v whiptail" in content
    assert "tui_select" in content


def test_no_function_ends_with_a_failing_test():
    """`set -e` trap: a function whose last statement is `[[ ... ]] && ...`
    returns 1 when the test is false, which exits the whole installer. This
    was the Express admin-password bug (typing a password exited silently).

    install.sh plus the libs it sources: a helper that moved into scripts/lib
    still runs under that trap.
    """
    import re

    offenders = [
        (path.name, name, tail, line)
        for path in (INSTALLER_PATH, *LIB_FILES)
        for name, tail, line in _function_tails(path)
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
    """Extract a shell function body, including heredocs.

    install.sh fetches and sources scripts/lib at startup, so a helper has
    exactly one definition in one of two places: search the installer first,
    then the libs.
    """
    for path in (INSTALLER_PATH, *LIB_FILES):
        lines = path.read_text(encoding="utf-8").splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith(f"{name}()")), None)
        if start is None:
            continue
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
    raise AssertionError(f"{name}() is defined in neither install.sh nor scripts/lib")


def test_recommended_defaults_never_touch_a_password():
    """Recommended installation asks for nothing and mints no credential."""
    source = _extract_function("panel_express_defaults")
    harness = f"""set -Eeuo pipefail
    rand_path() {{ echo generatedpath; }}
    rand_pass() {{ echo generated-password-123; }}
    DEFAULT_PORT=2095; DEFAULT_USER=admin
    EXPRESS=0; MODE=""; PORT=""; PATH_SET=0; PATHPREFIX=""
    ADMIN_USER=""; TLS_MODE=""; ADMIN_PASS=""; GENERATED_PASS=0
    {source}
    panel_express_defaults
    [[ -z "$ADMIN_PASS" ]]
    [[ "$GENERATED_PASS" -eq 0 ]]
    [[ "$PATHPREFIX" == generatedpath ]]
    [[ "$ADMIN_USER" == admin ]]
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
    content = _installer_source()
    assert 'confirm_no "Also delete data and backups?" && PURGE=1' in content


def test_detect_os_preserves_app_version(tmp_path):
    """Regression: sourcing /etc/os-release must not clobber the app
    VERSION (os-release defines its own VERSION=...)."""
    probe = tmp_path / "probe.sh"
    fn = subprocess.run(
        ["sed", "-n", "/^detect_os() {/,/^}/p", INSTALLER],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert fn, "detect_os not found"
    probe.write_text(
        'set -u\nVERSION="9.9.9-probe"\ndie() { echo "DIE: $1" >&2; exit 1; }\n' + fn + '\ndetect_os\necho "VERSION=$VERSION"\n',
        encoding="utf-8",
    )
    r = subprocess.run(["bash", str(probe)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "VERSION=9.9.9-probe" in r.stdout


def test_interactive_verb_runs_wizard():
    """`interactive` forces the numbered wizard (Enter = default)."""
    content = _installer_source()
    assert 'interactive)   ACTION="interactive"; shift ;;' in content
    assert "run_wizard_install()" in content


def test_release_downloads_follow_redirects():
    """github.com/download answers 302 to release-assets — curl needs -L,
    or every release install/update breaks."""
    content = _installer_source()
    assert "curl -fsSL -o" in content
    assert "curl -fsSLo" not in content


def test_entry_points_are_executable():
    """install.sh/manager.sh must carry +x in git — tarballs preserve it,
    and the manager execs $INSTALL_DIR/install.sh for update/uninstall."""
    for name in ("install.sh", "manager.sh"):
        path = INSTALLER_PATH.parent / name
        assert os.access(path, os.X_OK), f"{name} lost its executable bit"


def test_no_pages_url():
    """Pages serves the documentation, never the installer.

    The installer is bootstrapped from raw.githubusercontent.com because the
    anonysec.github.io host once served stale scripts, so install.sh and
    manager.sh must not point at it at all. README.md may link the published
    guides — and only the guides: never a script, an archive or a checksum.
    """
    repo = INSTALLER_PATH.parent
    for rel in ("install.sh", "manager.sh"):
        assert "github.io" not in (repo / rel).read_text(encoding="utf-8"), rel

    readme = (repo / "README.md").read_text(encoding="utf-8")
    for url in re.findall(r"https://[\w./-]*github\.io[\w./-]*", readme):
        assert url.startswith("https://anonysec.github.io/OVManager/"), (
            f"README links a Pages host that is not the docs site: {url}"
        )
        assert not url.endswith((".sh", ".txt", ".tar.gz", ".json")), (
            f"README points at Pages for an artifact, not a guide: {url}"
        )
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
    content = _installer_source()
    source = _extract_function("start_menu")
    assert "OVManager Setup" in source
    assert "1.${NC} Install" in source
    assert "2.${NC} Install with Docker" in source
    assert "0.${NC} Exit" in source
    assert "How do you want to install?" not in source
    assert "Ready — claim your panel" in content


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
        'die() { echo "DIE: $1" >&2; exit 1; }\n'
        'warn() { echo "WARN: $1" >&2; }\nstep() { :; }\ninfo() { :; }\n'
        + _extract_function("update_safety_backup")
        + "\n"
        + _extract_function("legacy_safety_bundle")
        + f'\nMODE=native INSTALL_DIR="{fake_install}" DATA_DIR="{fake_data}"\n'
        + "update_safety_backup 1.2.6\n"
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    bundles = sorted((fake_data / "backups").glob("ovmanager-pre-update-*.ovmbak"))
    assert len(bundles) == 1, r.stdout
    assert bundles[0].stat().st_mode & 0o777 == 0o600
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
    helpers = 'die() { echo "DIE: $1" >&2; exit 1; }\nwarn() { :; }\nstep() { :; }\ninfo() { :; }\n'
    mk = (
        helpers
        + _extract_function("legacy_safety_bundle")
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


def test_write_env_never_writes_a_backup_key(tmp_path):
    """Retired secrets stay out of fresh installs: no BACKUP_ENCRYPT_KEY in
    .env, and the staged update copy is scrubbed so the new backend (which
    rejects unknown keys) boots cleanly on the first try."""
    fake_install = tmp_path / "install"
    (fake_install / "backend").mkdir(parents=True)
    (fake_install / "backend" / "config.py").write_text("class Setting: pass\n", encoding="utf-8")
    harness = (
        'die() { echo "DIE: $1" >&2; exit 1; }\nstep() { :; }\ninfo() { :; }\n'
        + _extract_function("write_env")
        + "\nMODE=native PORT=2095 PATHPREFIX=abc ADMIN_USER=admin ADMIN_PASS=long-enough-password\n"
        + f'PUBLIC_URL="" TLS_KEY="" TLS_CERT="" DATA_DIR="{tmp_path}" INSTALL_DIR="{fake_install}"\n'
        + "write_env >/dev/null\n"
    )
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    env = (fake_install / ".env").read_text(encoding="utf-8")
    assert "BACKUP_ENCRYPT_KEY" not in env
    assert "BOT_ENCRYPT_KEY" not in env
    assert "NODE_ENCRYPT_KEY" not in env
    assert "JWT_SECRET_KEY=" in env


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
    content = _installer_source()
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
        "Ready — claim your panel",
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

    for path in (INSTALLER_PATH, INSTALLER_PATH.parent / "manager.sh", *(INSTALLER_PATH.parent / "scripts" / "lib").glob("*.sh")):
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
    """Owner password policy is >= 8 characters in the lib (which install.sh
    sources and reset-password uses), the shared validator, and the CLI."""
    lib_policy = INSTALLER_PATH.parent / "scripts" / "lib" / "policy.sh"
    for name, content in (
        ("scripts/lib/policy.sh", lib_policy.read_text(encoding="utf-8")),
        ("install.sh + libs", _installer_source()),
    ):
        assert "[[ ${#pass} -ge 8 ]]" in content, name
        assert "at least 8 characters" in content, name
    # The rule itself lives with the other shared validators now: the browser
    # claim (the new place an owner password is chosen) and the CLI both read
    # it from there.
    shared = (INSTALLER_PATH.parent / "backend" / "validation.py").read_text(encoding="utf-8")
    assert "at least {PASSWORD_MIN_LENGTH} characters" in shared
    cli_policy = (INSTALLER_PATH.parent / "cli" / "password.py").read_text(encoding="utf-8")
    assert "password_problem" in cli_policy


def test_backup_key_not_printed_at_install():
    """The recovery key is install noise; it belongs in Settings -> Backups
    when the encrypted remote copy is switched on."""
    content = _installer_source()
    card = content.split("success_card()")[1].split("\n}")[0]
    assert "Backup key" not in card


def test_update_staging_scrubs_retired_backup_key():
    """Upgrades from key-era installs must boot first try: the staged .env
    copy is scrubbed of BACKUP_ENCRYPT_KEY, which the new backend rejects."""
    source = _extract_function("do_update")
    anchor = 'cp -p "$INSTALL_DIR/.env" "$UPDATE_STAGE/.env"'
    assert anchor in source
    after = source.split(anchor, 1)[1]
    assert "BACKUP_ENCRYPT_KEY" in after.split("Step 3/6", 1)[0]


def test_compose_never_passes_the_env_through_env_file(tmp_path):
    """compose expands $NAME inside env_file values; a bcrypt hash dies.

    The panel's .env carries ADMIN_PASSWORD_HASH, and `$2b$12$<salt>...` has a
    `$` followed by a valid variable name as soon as the salt starts with a
    letter or dot — 83% of the time in practice. So the file is bind-mounted
    read-only and read from disk instead.
    """
    content = _installer_source()
    compose = content[content.index('cat > "$COMPOSE_FILE" << COMPOSE') :]
    compose = compose[: compose.index("\nCOMPOSE\n")]
    # Comments explain the hazard by naming it; assert on the config itself.
    code = "\n".join(x for x in compose.splitlines() if not x.lstrip().startswith("#"))
    assert "env_file" not in code, "env_file truncates the password hash"
    assert "${INSTALL_DIR}/.env:/app/.env:ro" in compose, "the .env must be mounted read-only"


def test_env_is_group_readable_for_the_container_in_docker_mode(tmp_path):
    """0640 root:<the image's ovpanel gid> in docker mode, 0600 native.

    0600 would put the panel's own config out of reach inside the container;
    chowning to uid 1000 would hand the admin hash and the JWT secret to the
    first human user on the host.
    """
    content = _installer_source()
    assert 'chown "root:$gid" "$envfile"' in content
    assert 'chmod 640 "$envfile"' in content
    assert '[[ "$MODE" == "docker" ]] || chmod 600 "$INSTALL_DIR/.env"' in content

    # The gid is read from the image rather than hardcoded: 997 is taken by
    # dhcpcd on this very host, so a constant would abort real installs.
    assert "--entrypoint getent" in content and "group ovpanel" in content
    assert "CFG_GID" not in content, "no constant to keep in step with the Dockerfile"
    dockerfile = INSTALLER_PATH.parent / "Dockerfile"
    with open(dockerfile, encoding="utf-8") as f:
        image = f.read()
    assert "groupadd -g 997 ovpanel" in image, "the image defines the group the host must chgrp to"


def test_env_is_shared_with_the_container_before_it_starts(tmp_path):
    """Ownership is applied after the image is local, not at write time."""
    content = _installer_source()
    up = content[content.index("compose_up() {") : content.index("# ──", content.index("compose_up() {"))]
    assert up.index("pull") < up.index("share_env_with_container") < up.index("up -d"), (
        "the gid can only be read once the image is present, and the config must be shared before the container starts"
    )


def test_config_is_never_shared_with_a_populated_host_group():
    """Group-sharing must not widen access to the admin hash or JWT secret."""
    content = _installer_source()
    assert 'if [[ -n "$members" ]]; then' in content
    assert 'die "GID $gid belongs to group' in content
    # An unused gid is created rather than treated as an error.
    assert '[[ -n "$existing" ]] || groupadd -g "$gid" ovpanel' in content


def test_generated_compose_keeps_the_dollar_sign_in_its_comment(tmp_path):
    """The compose heredoc is unquoted, so `$NAME` in a comment gets expanded.

    It shipped for one release: the generated file said "compose expands
    Ubuntu inside env_file values", because $NAME expanded to Ubuntu on the
    machine that ran the installer.
    """
    sb, _ = sandbox(tmp_path)
    with open(sb, encoding="utf-8") as f:
        content = f.read()
    heredoc = content[content.index('cat > "$COMPOSE_FILE" << COMPOSE') :]
    heredoc = heredoc[: heredoc.index("\nCOMPOSE\n")]
    assert "\\$NAME" in heredoc, "the comment must escape the dollar sign"
    assert re.search(r"(?<!\\)\$NAME", heredoc) is None, "an unescaped $NAME would be expanded"


def test_port_available_or_die_rejects_a_busy_port():
    """The helper both install paths now call, exercised without root.

    Root-independent on purpose: install.sh refuses to run as non-root before
    it ever validates the port, so testing the helper directly is what keeps
    this covered on CI. Also pins the first version's bug, where the helper
    was written as `port_in_use ... && die` and therefore returned 1 on a
    *free* port — which aborted every --yes install under set -e.
    """
    import re
    import socket
    import subprocess

    src = _installer_source()
    fns = "\n".join(
        re.search(rf"^{name}\(\) \{{.*?^\}}", src, re.M | re.S).group(0) for name in ("port_in_use", "port_available_or_die")
    )
    script = 'die() { echo "DIE: $1"; exit 3; }\n' + fns + "\n"

    busy = socket.socket()
    busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    busy.bind(("127.0.0.1", 20952))
    busy.listen(1)
    try:
        r = subprocess.run(
            ["bash", "-c", script + 'port_available_or_die 20952\necho "rc=$?"\n'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        free = subprocess.run(
            ["bash", "-c", script + 'port_available_or_die 20953\necho "rc=$?"\n'],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        busy.close()

    assert r.returncode == 3, f"a busy port must be refused: {r.stdout!r}"
    assert "DIE: Port 20952 is already in use" in r.stdout
    # The regression: a free port must return 0, not 1.
    assert free.returncode == 0, f"a free port was refused: {free.stdout!r}"
    assert free.stdout.strip().endswith("rc=0"), free.stdout


def test_port_in_use_actually_detects_a_busy_port():
    """Regression: the guard never fired, because of how awk reports exit.

    `ss | awk '$4 ~ p { exit 0 } END { exit 1 }'` always returns 1: awk runs
    END even after `exit 0` in a rule, so `exit 1` there always won. Every
    "port already in use" check in the installer was therefore dead — the
    install port and the port 80 check before Let's Encrypt.
    """
    import re
    import socket
    import subprocess

    src = _installer_source()
    body = re.search(r"^port_in_use\(\) \{.*?^\}", src, re.M | re.S).group(0)

    busy = socket.socket()
    busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    busy.bind(("127.0.0.1", 20952))
    busy.listen(1)
    try:
        script = f"{body}\nport_in_use 20952 && echo BUSY || echo FREE\nport_in_use 20953 && echo BUSY || echo FREE\n"
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    finally:
        busy.close()

    assert r.stdout.split() == ["BUSY", "FREE"], f"got {r.stdout!r}"


# The installer refuses to run as non-root before it reaches the port check, so
# this one cannot run on CI, which is deliberately non-root. The two tests above
# cover the same fix root-independently and do run there; this covers the
# wiring end to end, on a developer box or a root runner.
@pytest.mark.skipif(os.geteuid() != 0, reason="install.sh requires root before it validates the port")
def test_noninteractive_install_rejects_a_busy_port(tmp_path):
    """`--yes` must validate the port, not discover it from a Docker daemon.

    The port was defaulted *after* preflight_install had already run, and the
    only availability check lived in the interactive wizard. So the documented
    one-liner — curl ... | bash -s -- --docker --yes — installed happily and
    then failed much later with a raw "address already in use" from the daemon,
    after the download and the compose file had been written.

    Fails during preflight, before the download, so this stays fast.
    """
    import socket
    import subprocess

    sb, _ = sandbox(tmp_path)
    busy = 20950  # the sandbox's own default, so it is the one being validated
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", busy))
    listener.listen(1)
    try:
        r = subprocess.run(
            ["/usr/bin/setsid", "bash", sb, "--yes"],
            env={**os.environ, "OVM_PORT": str(busy)},
            capture_output=True,
            text=True,
            timeout=90,
            stdin=subprocess.DEVNULL,
        )
    finally:
        listener.close()

    out = r.stdout + r.stderr
    assert "already in use" in out, f"expected a clear port error, got:\n{out[-800:]}"
    assert "address already in use" not in out, "must not fall through to the Docker daemon error"
    assert "Step 1" not in out, "must fail in preflight, before downloading anything"


# ── the service account ───────────────────────────────────────────────────
#
# 1.0.25 stopped running the panel as root: it is reachable from the network
# and parses untrusted input, so a compromise of the web app should not be a
# compromise of the host. 1.0.26 moves existing installs onto it too.


_REAL_SYSTEM_PATHS = ("/etc/systemd/system", "/var/backups", "/etc/ssl", "/etc/letsencrypt", "/usr/local/bin")


def _source_and_call(sandbox_installer: str, snippet: str, env: dict | None = None):
    """Source the sandboxed installer and call one of its functions.

    install.sh guards its dispatch, so sourcing it defines everything without
    installing anything. That is what makes migrate_to_service_account and
    restore_unit testable behaviourally rather than by grepping the file.

    The snippet is raw bash that the sandbox rewrite never sees, which makes it
    the one place a real system path can slip through. That is not
    hypothetical: a version of this helper wrote "[Service]\\nUser=broken"
    straight to the real /etc/systemd/system/ovmanager.service and took the
    live unit with it. The panel kept serving on its already-loaded config, so
    nothing looked wrong until the next restart. Hence the refusal below.
    """
    for real in _REAL_SYSTEM_PATHS:
        # Not a substring test: the sandbox path itself *contains*
        # /etc/systemd/system. What must not appear is the real path used as an
        # absolute reference, i.e. not preceded by more of a path. A legitimate
        # sandbox reference is .../etc/systemd/system/..., so it is preceded by
        # a slash; a real one is preceded by a quote, a space or a redirect.
        assert not re.search(r"(?<![/\w])" + re.escape(real), snippet), (
            f"the snippet references the real {real} in absolute; use the sandbox path"
        )
    root = Path(sandbox_installer).parent
    full_env = {
        **os.environ,
        "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", "-c", f'source "{sandbox_installer}"\n{snippet}\n'],
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
        stdin=subprocess.DEVNULL,
    )


def _account_calls(tmp_path: Path) -> str:
    """What the installer asked the account tools to do, as logged by the shims."""
    log = tmp_path / "account.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_install_wires_the_service_account_into_the_fresh_install_path(tmp_path):
    """A fresh install must provision the account and grant it access.

    Asserted on the source, not on a run: the sandboxed full install cannot
    reach step 3 without a network, so a run-based assertion here would either
    be skipped or be asserting a download. The behaviour itself is covered by
    the two migration tests below, which drive the functions directly.
    """
    content = _installer_source()
    install_body = content[content.index("do_install()") : content.index("run_wizard_install()")]
    assert "ensure_panel_user" in install_body, "a fresh install never creates the account"
    assert "grant_panel_access" in install_body, "a fresh install never grants it access"
    # The grant has to land after the .env and the certificate exist, and
    # before the service is started -- otherwise the panel starts and cannot
    # read its own configuration.
    order = [install_body.index(x) for x in ("write_env", "grant_panel_access", "write_systemd_unit")]
    assert order == sorted(order), f"the grant is out of order: {order}"


def test_the_unit_template_runs_the_panel_as_the_service_account():
    """The unit is the thing that actually makes the panel unprivileged."""
    content = _installer_source()
    # Scoped to the template, not the whole file: migrate_to_service_account
    # has to mention User=root -- that is how it recognises an install that
    # still needs moving.
    start = content.index("write_systemd_unit()")
    template = content[start : content.index("\n}", start)]
    assert "User=${PANEL_USER}" in template, "the unit hard-codes an account or leaves it root"
    assert "Group=${PANEL_USER}" in template
    assert "User=root" not in template, "the template still starts the panel as root"


def test_systemctl_bounded_does_not_turn_other_verbs_into_a_restart(tmp_path):
    """A regression that cost a box its panel, so it is pinned here.

    `systemctl_bounded` used to treat every action that was not `stop` as
    `restart`. So `systemctl_bounded daemon-reload` silently *restarted the
    service* and reloaded nothing. When a 1.0.27 update failed verification, the
    failover put the old unit back on disk and called this to reload it —
    systemd carried on running the migrated unit, and the box would not start
    until someone ran daemon-reload by hand.

    The shim logs what it was asked to do, so this asserts the verb, not the
    fact that something ran.
    """
    sb, _ = sandbox(tmp_path)
    log = tmp_path / "systemctl.log"
    r = _source_and_call(
        sb,
        "MODE=native\n"
        "systemctl_bounded daemon-reload || echo daemon-reload-failed\n"
        "systemctl_bounded enable || true\n"
        "systemctl_bounded restart || true\n",
        env={"SYSTEMCTL_LOG": str(log)},
    )
    assert r.returncode == 0, r.stderr
    asked = log.read_text(encoding="utf-8")
    assert "systemctl daemon-reload ovmanager.service" in asked, asked
    assert "systemctl enable ovmanager.service" in asked, asked
    assert "systemctl restart ovmanager.service" in asked, asked
    # The bug: a reload turned into a restart, and there were two of them.
    assert asked.count("systemctl restart ovmanager.service") == 1, f"a non-restart verb became a restart:\n{asked}"
    assert "daemon-reload-failed" not in r.stdout, r.stdout


def test_update_does_not_touch_the_service_account(tmp_path):
    """Updates must not migrate the panel off root, and this pins why.

    1.0.26 and 1.0.28 both called the migration from `do_update`, before the
    candidate was verified. The migration rewrote
    the unit to `User=ovmanager`, the candidate then failed verification for an
    unrelated reason, and the failover could not undo it — the unit said
    `ovmanager`, the freshly extracted tree was root-owned `700`, and the panel
    sat in a `CHDIR: Permission denied` restart loop. Both times it needed a
    manual `systemctl daemon-reload` and a manual recover.

    A release upgrade and a privilege change are separate operations. Only
    `ovm doctor --fix` performs the second, because it verifies the panel comes
    back and restores the unit if it does not.
    """
    content = _installer_source()
    start = content.index("do_update()")
    body = content[start : content.index("\nrun_wizard_install()")]
    for gone in ("migrate_to_service_account", "snapshot_unit", "restore_unit"):
        assert gone not in body, f"do_update calls {gone} again"


def test_the_service_account_migration_is_only_in_doctor():
    """One home for it: the CLI fix path, which verifies and rolls back."""
    content = _installer_source()
    assert "migrate_to_service_account" not in content, "the installer grew a second migration path"
    doctor_src = (INSTALLER_PATH.parent / "cli" / "doctor.py").read_text(encoding="utf-8")
    assert "def fix_service_account" in doctor_src, "doctor no longer performs the migration"


def test_update_regrants_access_for_an_already_unprivileged_install(tmp_path):
    """A migrated box must still be able to update.

    The update replaces the whole tree, so on a box where the panel already runs
    as a service account the new tree is root-owned again and the service cannot
    even chdir into it. 1.0.30 -> 1.0.31 failed verification with
    `CHDIR: Permission denied`, so every update on a migrated box would break.

    The grant has to be re-applied — without ever changing the account, which is
    what `ovm doctor --fix` is for.
    """
    content = _installer_source()
    start = content.index("do_update()")
    body = content[start : content.index("\nrun_wizard_install()")]
    lines = body.splitlines()
    # The call itself, not the prose about it -- the comment above it names the
    # function too, so a substring search finds the wrong line first.
    calls = [i for i, line in enumerate(lines) if line.strip() == "grant_panel_access"]
    assert calls, "the update does not re-grant access to the new tree"
    # ...and it must be gated on the unit already being unprivileged, so a root
    # install is left alone rather than having its data directory handed over.
    gate = lines[calls[0] - 1]
    assert "User=root" in gate, f"the re-grant is not gated on the panel already being unprivileged: {gate.strip()}"
    assert "migrate_to_service_account" not in body, "the update changed the account again"


def _executable_lines(*paths: Path) -> list[str]:
    """The installer's lines with shells' comments and usage/help text removed.

    Comment banners and the help screen legitimately *mention* `curl | bash`
    (that is the documented one-liner), so scanning raw lines reports the docs
    as offenders. What matters is only what the script would execute — which
    includes the libs install.sh sources.
    """
    out, in_block = [], None
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if in_block is not None:
                if stripped == in_block:
                    in_block = None
                continue
            heredoc = re.search(r"<<-?\s*['\"]?([A-Za-z_0-9]+)['\"]?", line)
            if heredoc and re.match(r"(cat|usage|help|printf)\b", stripped):
                in_block = heredoc.group(1)
                continue
            if stripped.startswith("#"):
                continue
            out.append(line)
    return out


def test_no_installer_pipes_a_remote_script_into_a_root_shell():
    """install.sh runs as root; a piped `curl | sh` executes whatever answered.

    Third-party installers (uv, acme.sh) must be downloaded to a file, checked
    for a plausible payload, and only then executed.
    """
    offenders = [
        line
        for line in _executable_lines(INSTALLER_PATH, *LIB_FILES)
        if re.search(r"curl\b[^|]*\|\s*(sudo\s+)?(sh|bash)\b", line)
    ]
    assert offenders == [], f"piped remote script found: {offenders}"
    assert "fetch_and_run_installer" in _installer_source()


def test_third_party_installers_are_version_pinned():
    body = _installer_source()
    assert re.search(r'UV_INSTALL_VERSION="\d+\.\d+\.\d+"', body)
    assert re.search(r'ACME_INSTALL_VERSION="\d+\.\d+\.\d+"', body)
    assert "https://get.acme.sh" not in body, "the unpinned moving endpoint must be gone"


def test_fetch_and_run_installer_rejects_a_non_script_payload(tmp_path):
    """A redirect stub must be rejected, not executed as root."""
    helper = _extract_function("fetch_and_run_installer")
    stub = tmp_path / "stub.sh"
    stub.write_text("<html>302 Found</html>")
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/bin/bash\n"
        f"{helper}\n"
        f'curl() {{ cp "{stub}" "$5"; }}\n'
        'fetch_and_run_installer "https://example.invalid/x" "#!/bin/sh" "probe"\n'
        'echo "rc=$?"\n'
    )
    out = subprocess.run(["bash", str(harness)], capture_output=True, text=True, timeout=20)
    assert "rc=1" in out.stdout, f"a non-script payload must fail the check: {out.stdout} {out.stderr}"


def test_fetch_and_run_installer_runs_a_valid_payload(tmp_path):
    helper = _extract_function("fetch_and_run_installer")
    script = tmp_path / "real.sh"
    script.write_text('#!/bin/sh\necho ran > "$MARKER"\n')
    marker = tmp_path / "marker.txt"
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/bin/bash\n"
        f"{helper}\n"
        f'curl() {{ cp "{script}" "$5"; }}\n'
        'fetch_and_run_installer "https://example.invalid/x" "#!/bin/sh" "probe"\n'
        'echo "rc=$?"\n'
    )
    out = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "MARKER": str(marker)},
    )
    assert "rc=0" in out.stdout, f"{out.stdout} {out.stderr}"
    assert marker.read_text().strip() == "ran"
    assert not list(tmp_path.glob("probe*")), "the downloaded script must be cleaned up"


def test_secret_bearing_paths_are_owner_only():
    """A stolen .db or backup bundle yields the bot token and node API keys.

    At-rest encryption was retired deliberately (the host is the trust
    boundary), which makes these modes load-bearing: they are the only thing
    between those credentials and any local user.
    """
    body = _installer_source()
    assert re.search(r'chmod 700 "\$DATA_DIR"', body), "the data directory must be 0700"
    assert re.search(r'chmod 700 "\$backup_dir"', body), "backups must be 0700"
    # The installed .env has no credential anymore, but it still carries the
    # URLPATH secret and TLS paths, so it stays group-only at worst.
    assert re.search(r'chmod 640 "\$INSTALL_DIR/\.env"', body)
    assert re.search(r'chmod 600 "\$INSTALL_DIR/\.env"', body)


def test_no_credential_is_written_to_env():
    """The owner is a database row (v16) — .env must not carry a credential.

    install.sh used to write ADMIN_PASSWORD in plaintext, which the panel then
    hashed into ADMIN_PASSWORD_HASH on first boot. Since v16 nothing reads
    either field. The installer now also stops minting a password at all: it
    writes a one-time claim key outside .env, and the browser creates the row.
    """
    body = _installer_source()
    assert "printf 'ADMIN_PASSWORD=" not in body, "the installer still writes a credential to .env"
    assert "set_owner_password" not in body, "install must not write the owner credential"
    assert "issue_claim_key" in body, "the installer must hand out the claim key itself"


def test_no_install_path_builds_an_owner_password():
    """No code path in install.sh or the libs builds an owner credential.

    The claim key is the only credential-shaped thing the install writes, and
    mint_claim_key is the only thing that writes it — into the data dir, never
    into .env (checked above).
    """
    body = _installer_source()
    assert "ADMIN_PASSWORD_HASH=" not in body, "the installer has no owner hash to write"
    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    # A comment may name ADMIN_PASSWORD (it explains why .env holds none); an
    # assignment or expansion would mean the installer still handles one.
    assert "ADMIN_PASS=" not in installer, "install.sh must not build an owner credential"
    assert "${ADMIN_PASS" not in installer, "install.sh must not read an owner credential"
    assert "rand_pass" not in installer, "a generated password would be a credential with no owner"
    # The lib keeps the reset-password prompt (`ovm reset-password` uses it) —
    # install.sh no longer reaches it.
    lib_policy = (INSTALLER_PATH.parent / "scripts" / "lib" / "policy.sh").read_text(encoding="utf-8")
    assert "prompt_validate_admin_password" in lib_policy


def test_the_claim_key_is_issued_after_the_runtime_exists():
    """It lands in the data dir the panel user owns, so it comes last."""
    body = _installer_source()
    call = body.index("issue_claim_key\n")
    assert call > body.index("write_env\n"), "issue_claim_key must run after the .env is written"
    assert "Step 4/4" in body[:call], "and after the runtime is up (Step 4)"


def test_install_prints_the_claim_url_and_never_a_password():
    """The Ready card points at the browser claim, and prints no credential."""
    source = _extract_function("success_card")
    assert 'kv "Claim key"' in source
    assert "Password" not in source
    assert "claim${NC}" in source, "the card opens the claim page, not the login page"


def test_umask_is_scoped_to_the_env_write():
    """An unscoped `umask 077` broke every fresh native install.

    It leaked into `uv sync`, which then created .venv 0700 root:root. The
    panel user could not traverse into it and the service died with
    status=203/EXEC — while an *upgrade* over an older tree kept working,
    which is how it survived.
    """
    body = _installer_source()
    lines = [line.strip() for line in body.splitlines()]
    umask_lines = [i for i, line in enumerate(lines) if line == "umask 077"]
    assert umask_lines, "expected the .env write to set a restrictive umask"
    for i in umask_lines:
        # The umask must sit INSIDE a subshell, so it cannot leak into the
        # rest of the installer.
        assert lines[i - 1] == "(", f"umask 077 at line {i + 1} is not scoped to a subshell"


def test_panel_user_can_traverse_the_venv():
    """grant_panel_access must fix a venv the service cannot read."""
    body = _installer_source()
    start = body.index("grant_panel_access() {")
    end = body.index("\n}\n", start)
    grant = body[start:end]
    assert ".venv" in grant, "grant_panel_access does not touch .venv"
    assert "chmod -R g+rX" in grant, "the venv must become group-readable/traversable"


# ── The claim key and version-script ───────────────────────────────────


def test_mint_claim_key_writes_a_0600_key_and_reprints_a_new_one(tmp_path):
    """The key is regenerable because it is not the credential.

    Minting twice must produce two different keys — a stable one would be a
    static credential sitting in the data dir.
    """
    data = tmp_path / "data"
    libs = "\n".join(f'source "{p}"' for p in (LIB_DIR / "common.sh", LIB_DIR / "policy.sh"))
    harness = f"""
    set -Eeuo pipefail
    DATA_DIR="{data}"
    MODE=native
    PANEL_USER="$(id -un)"
    {libs}
    first="$(mint_claim_key)"
    second="$(mint_claim_key)"
    printf '%s\\n%s\\n' "$first" "$second"
    """
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    first, second = r.stdout.split()
    assert first != second, "a reprint must be a new key"
    for key in (first, second):
        assert len(key) == 32, key
        assert all(c in "0123456789abcdef" for c in key), key
    key_file = data / "owner-claim.key"
    assert key_file.stat().st_mode & 0o777 == 0o600, oct(key_file.stat().st_mode)
    assert key_file.read_text(encoding="utf-8").strip() == second, "the file holds the newest key"


def test_the_installer_reads_the_claim_key_from_the_panel_data_dir(tmp_path):
    """One path, shared with the panel: DATA_DIR/owner-claim.key.

    backend/routers/owner_claim.py reads the same file name from the same dir,
    so this is the contract between the two halves of the flow.
    """
    assert _extract_function("claim_key_path").count("owner-claim.key") == 1
    backend = INSTALLER_PATH.parent / "backend" / "routers" / "owner_claim.py"
    assert 'CLAIM_KEY_FILE = "owner-claim.key"' in backend.read_text(encoding="utf-8")


def test_version_script_reports_unknown_without_a_checkout(tmp_path):
    """A downloaded installer has no commit, and must say so.

    Run from a copy with no .git anywhere above it, which is also what keeps
    git out of the test suite: script_commit only invokes it when a checkout is
    actually there.
    """
    stage = tmp_path / "stage"
    (stage / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(INSTALLER_PATH, stage / "install.sh")
    for lib in LIB_FILES:
        shutil.copy(lib, stage / "scripts" / "lib" / lib.name)

    for verb in ("version-script", "script-version"):
        r = subprocess.run(
            ["bash", str(stage / "install.sh"), verb],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert r.returncode == 0, r.stderr
        assert "installer  v" in r.stdout, r.stdout
        assert "commit     unknown" in r.stdout, r.stdout
        assert "NOT-A-COMMIT" not in r.stdout


def test_script_commit_only_shells_out_when_a_checkout_exists():
    """The git call is gated on a .git entry, so a tarball install never runs it."""
    source = _extract_function("script_commit")
    assert ".git" in source
    assert "git -C" in source
    assert source.index('.git"') < source.index("git -C"), "the .git check must come first"
