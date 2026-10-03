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

import inline_lib
import pytest

INSTALLER = os.path.join(os.path.dirname(__file__), "..", "install.sh")
INSTALLER_PATH = Path(INSTALLER)
INSTALL_DIR = "/opt/ovmanager"
SETSID = shutil.which("setsid")


def _installer_source() -> str:
    """install.sh's own text — which is the whole installer now.

    Content assertions scan this rather than install.sh alone only when a
    helper used to live in a separate file. Every helper is inline, so the file
    is the complete program.
    """
    return INSTALLER_PATH.read_text(encoding="utf-8")


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


def _free_port() -> int:
    """An unused TCP port on the loopback, for one sandboxed installer.

    The kernel picks it from the ephemeral range, so two concurrent tests cannot
    be handed the same one — which is what made `make test` fail at random when
    every test in this file shared 20950.

    The socket is closed before the port is used, so there is a window in which
    something else could take it. That is the same trade the previous fixed port
    made, except the window is now per-test and the pool is ~28k wide rather
    than one value.
    """
    import socket as _socket

    with _socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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
            # assertion they were written for.
            #
            # A *per-test* port, not a fixed one. 20950 was shared by all 103
            # tests here, and one of them deliberately holds it open to test the
            # busy-port path — so under `make test` (-n auto) the two collided at
            # random and the loser failed with "Port 20950 is already in use"
            # inside a test about password validation, blaming the wrong thing.
            # The OS hands out an unused ephemeral port per test instead.
            .replace("DEFAULT_PORT=2095", f"DEFAULT_PORT={_free_port()}")
        )

    # The helpers are inline, so the rewritten install.sh is the whole program
    # and there is nothing to lay down beside it. A verbatim copy would let a
    # sandboxed install reach the real /var/backups, /etc/ssl and
    # /etc/letsencrypt.
    src = rewrite(INSTALLER_PATH.read_text(encoding="utf-8"))
    for tool in ("systemctl", "ufw", "firewall-cmd", "curl", *ACCOUNT_TOOLS):
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
    # The sandbox has no network. Without this, an install that reaches the
    # release fetch waits on github.com for real — three tests used to sit there
    # until they timed out, and passed in CI only because the fetch happened to
    # fail fast there. Failing the way curl does when it cannot connect makes any
    # such test die at once, and makes the whole suite hermetic.
    #
    # Tests that genuinely need a fetch define their own `curl` shell function
    # inside their harness, and a function wins over a PATH binary, so this does
    # not interfere with them.
    "curl": """
echo "curl: (7) Failed to connect" >&2
exit 7
""",
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
    # Keyed on the shim directory existing, not on the directory being *named*
    # like a tempdir. The previous `root.name.startswith("tmp")` matched only
    # tempfile's naming, never pytest's tmp_path (`.../test_foo0`), so under
    # pytest this block never ran: every shim in _SHIMS was inert, PATH was not
    # set, and a test reaching the release fetch went to the real network and
    # timed out. The assertions that check the shim log are guarded by
    # `if log.exists()`, so they were passing without asserting anything.
    if (root / "bin").is_dir():
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
    """The floor itself: 7 rejected, 8 accepted, per the shared policy."""
    import subprocess

    lib = inline_lib.path("policy.sh")
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


def test_a_supplied_owner_password_is_accepted_and_dropped(tmp_path):
    """`-p` must not become a credential, and must say so rather than fail.

    The owner password moved to the panel database (schema v16) and is set in
    the browser. `parse_args` therefore accepts `-p/--pass` and drops it with a
    deprecation notice: honouring it would write a hash nobody reads, and
    rejecting it would break a working one-liner for no gain.

    This test used to assert the opposite — that a placeholder password is
    *rejected* — and passed for six releases without testing anything. Its
    assertion was `"placeholder" in r.stderr or "root" in r.stderr`, and the
    installer was printing a stray path to stderr on every download, in a
    directory named after the pytest tmpdir: `/tmp/pytest-of-root/...`. That
    substring matched "root", so the assertion was satisfied by a bug rather
    than by the behaviour it described. Fixing that stderr leak is what exposed
    it — the false positive had been living inside the very noise it was
    asserting against.
    """
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "-y", "-p", "my-admin12345")
    assert "-p, --pass is deprecated" in r.stderr, r.stderr
    assert "owner password is set in the browser" in r.stderr, r.stderr
    # And the supplied value is nowhere near a credential in what the installer wrote.
    assert "my-admin12345" not in r.stderr, "the supplied password was echoed back"


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


def test_the_machine_is_summarised_before_anything_changes():
    """No --dry-run flag exists; what the install is about to do is the first
    progress step instead.

    This replaced a nine-row plan card that printed before every mutating
    action. It restated the port, the URL path, the admin name and the TLS mode
    — every value the operator had just been asked for — and added only the
    machine's own state, which nobody chose and which decides whether the run
    can succeed at all. That state is now on the preflight line.
    """
    content = _installer_source()
    assert "--dry-run)" not in content
    assert "print_plan" not in content, "the plan card came back"
    assert "preflight_summary" in content
    assert 'render_begin "preflight"' in content
    assert "$(preflight_summary)" in content


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
    assert "re-created the missing update maintenance marker" in source
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
    helpers = (
        'set -Eeuo pipefail\ndie() { echo "DIE: $1" >&2; exit 1; }\n'
        "render_ok() { :; }\nrender_note() { :; }\nrender_warn() { :; }\n"
    )
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
    assert "already_installed_menu" in content
    assert 'update    "update to v${VERSION}"' in content
    assert 'uninstall "uninstall"' in content
    assert 'quit      "quit"' in content
    assert "render_menu" in content
    # tui_select survives only as a one-line alias into render_menu; a caller
    # reaching for it is fine, a second implementation of it is not.
    prompt = inline_lib.section("prompt.sh")
    assert 'tui_select() { render_menu "$@"; }' in prompt


def test_already_installed_menu_is_safe_by_default(tmp_path):
    """With an existing install dir and no tty, the menu must refuse to act
    (exit 2) — never default into update/uninstall."""
    sb, fake_opt = sandbox(tmp_path)
    os.makedirs(fake_opt)
    r = sh_sb(sb, "-y", "-p", "long-enough-password")
    assert r.returncode == 2
    # Exit 2 with the reason on stderr, in the renderer's own wording.
    assert "already installed" in r.stderr
    assert fake_opt in r.stderr
    assert "update" in r.stderr


def test_the_menu_is_one_renderer():
    """render_menu owns the pointer, the digits and the arrow.

    A menu drawn in two places is how they disagree: whiptail on boxes that
    have it, hand-rolled printf everywhere else. The old tui_select branched on
    `command -v whiptail` and rendered two different menus with two different
    selections. There is now one renderer and one keystroke reader.
    """
    content = _installer_source()
    code = "\n".join(ln for ln in content.splitlines() if not ln.lstrip().startswith("#"))
    assert "whiptail" not in code, "the whiptail branch is back"
    assert "tui_select() { render_menu" in content
    render = inline_lib.section("render.sh")
    # The pointer and the visible number are updated together in the same case
    # arm: that is the invariant, and it is only checkable in one place.
    assert "_MENU_CUR=$(( _MENU_CUR - 1 ))" in render
    assert "_MENU_CUR=$(( _MENU_CUR + 1 ))" in render
    assert "_MENU_CUR=$(( 10#$ch - 1 ))" in render
    assert "reply=$(( _MENU_CUR + 1 )); break" in render


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
    """The front door uses beginner wording and generates secure defaults.

    The mode is asked here and nowhere else. The wizard used to ask it again as
    "Step 1/5", so the answer could be given twice and the two did not always
    agree — choosing "install with docker" on the menu and "native" in the
    wizard was a reachable state.
    """
    source = _extract_function("start_menu")
    assert "install  ·  systemd on this host" in source
    assert "install  ·  containerized" in source
    assert "Express" not in source
    assert "Custom" not in source
    assert 'MODE="native"; panel_express_defaults' in source
    assert 'MODE="docker"; panel_express_defaults' in source
    assert "render_menu" in source
    # And the wizard must not ask again. TLS_MODE is a different question and
    # appears legitimately; the install MODE must not.
    wizard = _extract_function("wizard")
    assert "Install mode" not in wizard, "the wizard must not re-ask the install mode"
    assert '"$MODE"' not in wizard


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
    assert "render_menu" in content


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
        for path in (INSTALLER_PATH,)
        for name, tail, line in _function_tails(path)
        if re.match(r"^\[\[.*\]\]\s*&&", tail)
    ]
    assert not offenders, offenders


def _extract_function_sh(name: str, path: Path) -> str:
    """_extract_function for a file the installer does not define the name in.

    Brace-aware, because a body may contain a `{ … }` on a single line (a case
    arm, an awk program). Stopping at the first `}` there truncates the function
    and the harness then fails to parse — which reads as a broken helper rather
    than a broken extractor.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(f"{name}()")), None)
    if start is None:
        raise AssertionError(f"{name}() is not in {path.name}")
    depth = 0
    started = False
    out = []
    for line in lines[start:]:
        out.append(line)
        opens, closes = line.count("{"), line.count("}")
        if not started and opens:
            started = True
        depth += opens - closes
        if started and depth == 0:
            break
    return "\n".join(out)


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

    The helpers are inline now, so a helper defined in this file has exactly one
    definition and the search is a straight lookup.
    """
    for path in (INSTALLER_PATH,):
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


def _confirm_harness(fn: str, call: str) -> str:
    """A bash script that has just the prompt helpers, the real function, and
    the named call — no installer, no libs, no terminal."""
    return (
        "set -Eeuo pipefail\n"
        "GR=''; NC=''; B=''; GY=''\n"
        "render_ask() { :; }\n"
        # A return code, not a boolean: can_prompt SUCCEEDS when a terminal is
        # reachable, so "promptable" is rc 0 and "no terminal" is rc 1.
        'can_prompt() { return "$CAN_PROMPT_RC"; }\n'
        'YES="$YES"\n'
        "_read_reply() { printf '%s' \"$REPLY\"; }\n"
        f"{fn}\n"
        f"{call}\n"
    )


def _run_confirm(fn: str, call: str, *, can_prompt_rc: int, yes: int, reply: str):
    script = _confirm_harness(fn, call)
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "CAN_PROMPT_RC": str(can_prompt_rc), "YES": str(yes), "REPLY": reply},
    )


def test_confirm_no_is_safe_by_default():
    """confirm_no answers no unless a human typed y or Y."""
    source = _extract_function_sh("confirm_no", inline_lib.path("prompt.sh"))
    cases = [
        (0, 0, "y", 0),
        (0, 0, "Y", 0),
        (0, 0, "", 1),  # Enter keeps the default, which is no
        (0, 0, "n", 1),
        (0, 1, "y", 1),  # --yes means "never ask", and this helper says no
        (1, 0, "y", 1),  # no terminal: nothing was typed, nothing is confirmed
    ]
    for can_prompt_rc, yes, reply, expected in cases:
        r = _run_confirm(source, "confirm_no 'Delete data?'", can_prompt_rc=can_prompt_rc, yes=yes, reply=reply)
        assert r.returncode == expected, (reply, yes, can_prompt_rc, r.returncode, r.stderr)


def test_confirm_word_makes_the_destructive_answer_the_typed_one():
    """`purge` has to be spelled out; Enter must keep the data.

    A y/N prompt put "yes, delete the database" one keystroke from the default.
    confirm_word answers no to everything except the exact word, and answers no
    outright when there is no terminal — a script can never purge by accident.
    """
    source = _extract_function_sh("confirm_word", inline_lib.path("prompt.sh"))
    cases = [
        (0, 0, "purge", 0),  # the word purges
        (0, 0, "", 1),  # Enter keeps it
        (0, 0, "y", 1),  # y does not
        (0, 0, "yes", 1),  # and neither does yes
        (0, 0, "PURGE", 1),  # case matters
        (0, 0, "purg", 1),  # nor a prefix
        (0, 1, "purge", 0),  # --yes is an explicit request to purge
        (1, 0, "purge", 1),  # no terminal: nothing can be typed, nothing purges
    ]
    for can_prompt_rc, yes, reply, expected in cases:
        r = _run_confirm(source, "confirm_word 'delete the data?' purge", can_prompt_rc=can_prompt_rc, yes=yes, reply=reply)
        assert r.returncode == expected, (reply, can_prompt_rc, yes, r.returncode, r.stderr)


def test_uninstall_asks_about_data():
    """The list of what goes comes before the question, and the question is
    not yes/no."""
    uninstall = _extract_function("do_uninstall")
    assert 'confirm_word "delete the data as well? type purge" "purge" && PURGE=1' in uninstall
    # The sizes have to be printed: "84 MB" and "210 MB" make the purge decision
    # differently, and an operator choosing whether to keep data needs the
    # number in front of them.
    assert "dir_size" in uninstall
    assert uninstall.index("dir_size") < uninstall.index("confirm_word")
    # And the app itself still takes a plain confirmation, so a non-destructive
    # install can be removed without typing anything.
    assert 'confirm "remove the app and stop the service?"' in uninstall


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
    """The front door offers two installs and an exit, and says what each is.

    The labels are lowercase verbs with the mode after a separator, because the
    menu is drawn by render_menu and there is no "Setup" heading to attach a
    capital to any more — the banner already says what is running.
    """
    content = _installer_source()
    source = _extract_function("start_menu")
    assert "install  ·  systemd on this host" in source
    assert "install  ·  containerized" in source
    assert 'quit    "exit"' in source
    assert "How do you want to install?" not in source
    for retired in ("Setup${NC}", "1.${NC} Install", "0.${NC} Exit", "Ready — claim your panel"):
        assert retired not in content, f"retired wording back: {retired}"
    # Cancelling says what did not happen, not "Cancelled." with a full stop.
    assert "nothing was changed" in source


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
        'render_warn() { echo "WARN: $1" >&2; }\nrender_ok() { :; }\nrender_note() { :; }\n'
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
    helpers = 'die() { echo "DIE: $1" >&2; exit 1; }\nrender_warn() { :; }\nrender_ok() { :; }\nrender_note() { :; }\n'
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
        'die() { echo "DIE: $1" >&2; exit 1; }\nrender_ok() { :; }\nrender_note() { :; }\n'
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
        "render_menu",
        "render_banner",
        "render_card",
        "install  ·  systemd on this host",
        "install  ·  containerized",
        "1 self-signed · 2 lets encrypt · 3 custom",
        "render_ok",
        "render_warn",
        "render_fail",
        "render_next",
    ):
        assert token in content, f"design drift: {token}"
    for retired in (
        "Setup${NC}",
        "1.${NC} Install",
        "How do you want to install?",
        "Choose every option yourself",
        "Step 1/4",
        "Ready — claim your panel",
        "Let's Encrypt (domain)",
    ):
        assert retired not in content, f"retired wording back: {retired}"


def test_the_output_vocabulary_is_shared_not_repeated():
    """Both repos must carry the same render.sh under the same names.

    This is the failure the old layout invited: the panel's Ready card and the
    node's were two copies of one idea, and they drifted. The names below are
    the contract. If one repo gains a helper the other lacks, that is the drift
    starting again.
    """
    node_lib = INSTALLER_PATH.parent.parent / "OVNode" / "scripts" / "lib"
    if not node_lib.is_dir():
        pytest.skip("OVNode checkout not beside this repo")
    assert (node_lib / "render.sh").is_file()

    def helpers(src: str) -> set[str]:
        return set(re.findall(r"^(render_[a-z_]+)\(\)", src, re.M))

    p, n = helpers(inline_lib.section("render.sh")), helpers((node_lib / "render.sh").read_text(encoding="utf-8"))
    assert p == n, f"render.sh differs between repos: panel-only {p - n}, node-only {n - p}"


def test_no_command_substitution_in_unit_heredoc():
    """Regression: an unquoted heredoc executes backticks in its body. A
    comment with `ovm stop` inside the UNIT heredoc ran the manager on
    every fresh install (command not found). No unescaped backticks in
    any unquoted heredoc body."""
    import re

    for path in (INSTALLER_PATH, INSTALLER_PATH.parent / "manager.sh"):
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


def test_the_banner_is_one_line_and_a_rule():
    """Name, version, repo — then a rule. No tagline.

    The old banner had a second line whose only job was to advertise a fresh
    install, and it had to be suppressed on update/uninstall because a
    "up and running in a few minutes" line over an update reads as a lie. One
    line has no context to get wrong.
    """
    source = _extract_function("banner")
    assert 'render_banner "OVManager" "v${VERSION}"' in source
    assert "subtitle" not in source
    content = _installer_source()
    assert "up and running in a few minutes" not in content
    assert "Secure VPN panel —" not in content


def test_generated_password_is_twelve_characters():
    """Generated passwords are 12 characters: short enough to retype, well
    above the 8-character policy minimum."""
    src = _extract_function("rand_pass")
    assert "head -c 12" in src
    assert "head -c 20" not in src


def test_password_policy_minimum_is_eight():
    """Owner password policy is >= 8 characters in install.sh's helper block
    (which reset-password uses), the shared validator, and the CLI."""
    lib_policy = inline_lib.section("policy.sh")
    for name, content in (
        ("install.sh policy section", lib_policy),
        ("install.sh", _installer_source()),
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
    # Its own port, held open for the duration. It used to be the sandbox's
    # fixed 20950, so every other test in this file was racing it — and under
    # -n auto the loser failed here, or in a password test, at random.
    busy = _free_port()
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


def test_the_download_progress_loop_stays_quiet_before_the_file_exists(tmp_path):
    """`fetch_to_file` must not print the shell's redirect error while polling.

    The loop measures the growing file every 0.4s to drive the progress bar, and
    on the first poll curl has not created it yet. The old form read

        have="$(wc -c < "$out" 2>/dev/null || printf 0)"

    and `2>/dev/null` never helped: bash applies redirections left to right, so
    the input redirect failed first and printed to the real stderr, leaving a
    bare path in the middle of a download that was working fine:

        line 472: /tmp/tmp.XXXX/ovmanager-1.0.4.tar.gz: No such file or directory

    The count itself was always right — the `|| printf 0` fallback caught it —
    which is what made the noise worth removing rather than debugging.

    Runs the real function with a curl that never creates its output file, which
    is exactly the window the first poll lands in, and asserts stderr is empty.
    """
    out = tmp_path / "never-written.tar.gz"
    body = _extract_function_sh("fetch_to_file", INSTALLER_PATH)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "set -Eeuo pipefail\n"
        # The three helpers the loop calls, stubbed: only stderr matters here,
        # and each one has its own dependency the probe does not need.
        "_render_now() { date +%s%N; }\n"
        "_render_bytes() { :; }\n"
        "curl() { sleep 1; }\n"
        f"{body}\n"
        f'fetch_to_file https://example.invalid/payload "{out}"\n',
        encoding="utf-8",
    )
    r = subprocess.run(["bash", str(probe)], capture_output=True, text=True, timeout=60)
    assert "No such file or directory" not in r.stderr, f"the poll leaked a shell error:\n{r.stderr}"
    assert str(out) not in r.stderr, f"the poll leaked the download path:\n{r.stderr}"


def _probe_fetch(tmp_path, curl_body: str, out_name: str) -> list[str]:
    """Run the real fetch_to_file, recording every (have, total, rate) it reports.

    `_render_bytes` is stubbed to echo its three arguments one poll per line, so
    the numbers the progress bar is actually driven by are inspectable rather
    than inferred. The stub is what makes this test about the counter: silence
    on stderr is a separate assertion, and a change that quiets the loop by
    breaking the count would pass that one alone.
    """
    out = tmp_path / out_name
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "set -Eeuo pipefail\n"
        "_render_now() { date +%s%N; }\n"
        '_render_bytes() { printf "%s|%s|%s\\n" "$1" "${2:-}" "${3:-}" >&2; }\n'
        f"curl() {{\n{curl_body}\n}}\n"
        f"{_extract_function_sh('fetch_to_file', INSTALLER_PATH)}\n"
        f'fetch_to_file https://example.invalid/payload "{out}"\n',
        encoding="utf-8",
    )
    r = subprocess.run(["bash", str(probe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    polls = []
    for line in r.stderr.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[0].isdigit():
            polls.append(parts)
    assert polls, f"no poll was recorded; stderr was:\n{r.stderr}"
    return polls


def test_the_download_counter_reads_a_real_byte_count(tmp_path):
    """A file that exists is measured, not assumed to be zero.

    The `-f` guard that stopped the stderr leak also gates the measurement, so
    "quiet on a missing file" and "counts a real one" have to be asserted
    together: a guard that returned early, or a fallback that always printed 0,
    would satisfy the silence test and leave the progress bar frozen at zero for
    the whole download.
    """
    payload = tmp_path / "out.bin"
    payload.write_bytes(b"x" * 5000)

    # curl never runs here: the file is already in place, so every poll measures
    # the same 5000 bytes. The count must be that number on every poll.
    polls = _probe_fetch(tmp_path, "return 0", "out.bin")

    for have, _total, _rate in polls:
        assert have == "5000", f"counter reported {have} bytes for a 5000-byte file; polls={polls}"


def test_the_download_counter_starts_at_zero_when_the_file_is_absent(tmp_path):
    """A file curl has not created yet counts zero, and stays an integer.

    This is the window the `-f` guard exists for. Zero is the honest reading —
    the download has produced nothing so far — and the value must reach
    `_render_bytes` as a bare integer, because the caller divides by it:
    `rate=$(( have / elapsed / 1024 ))` would abort on anything else.
    """
    polls = _probe_fetch(tmp_path, "sleep 1", "never-written.bin")
    for have, _total, _rate in polls:
        assert have == "0", f"expected 0 bytes before the file exists, got {have}; polls={polls}"


def test_no_installer_pipes_a_remote_script_into_a_root_shell():
    """install.sh runs as root; a piped `curl | sh` executes whatever answered.

    Third-party installers (uv, acme.sh) must be downloaded to a file, checked
    for a plausible payload, and only then executed.
    """
    offenders = [line for line in _executable_lines(INSTALLER_PATH) if re.search(r"curl\b[^|]*\|\s*(sudo\s+)?(sh|bash)\b", line)]
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


def _calls(text: str, name: str) -> list[str]:
    """Every line that calls `name`, ignoring its own definition."""
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        if re.search(rf"^\s*(?:function\s+)?{re.escape(name)}\b", stripped):
            continue
        if re.search(rf"[^a-zA-Z0-9_]{re.escape(name)}\s+[\"'$]", stripped):
            out.append(line.strip())
    return out


def test_no_install_path_builds_an_owner_password():
    """No code path in install.sh builds an owner credential.

    The claim key is the only credential-shaped thing the install writes, and
    mint_claim_key is the only thing that writes it — into the data dir, never
    into .env (checked above).

    The helpers that would build a password — `rand_pass`,
    `prompt_validate_admin_password` — are defined in the inline block the
    installer carries, because that block is kept byte-identical to the
    manager's and to the node's renderer. None of them is called. What has to
    hold is that nothing reaches one, so this checks call sites rather than the
    presence of a definition that cannot run.
    """
    body = _installer_source()
    assert "ADMIN_PASSWORD_HASH=" not in body, "the installer has no owner hash to write"
    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    # A comment may name ADMIN_PASSWORD (it explains why .env holds none); an
    # assignment or expansion in live code would mean the installer still
    # handles one.
    for helper in ("rand_pass", "prompt_validate_admin_password"):
        calls = _calls(installer, helper)
        assert not calls, f"install.sh must not reach {helper}(): {calls}"
    # The assignment only ever exists inside the never-called prompt helper.
    for lineno, line in enumerate(installer.splitlines(), 1):
        if "ADMIN_PASS=" in line and "prompt_validate_admin_password" not in "".join(
            installer.splitlines()[max(0, lineno - 12) : lineno]
        ):
            raise AssertionError(f"install.sh:{lineno} builds an owner credential: {line.strip()}")
    assert "prompt_validate_admin_password" in inline_lib.section("policy.sh")


def test_the_claim_key_is_issued_after_the_runtime_exists():
    """It lands in the data dir the panel user owns, so it comes last."""
    body = _installer_source()
    call = body.index("issue_claim_key\n")
    assert call > body.index("write_env\n"), "issue_claim_key must run after the .env is written"
    runtime = body.index('render_done "active"')
    assert runtime < call, "and after the runtime is up"


def test_the_setup_key_is_the_second_line_of_the_card():
    """Key first, explanation after.

    An operator who interrupts the card mid-fade must already have the one thing
    they cannot get back. render_card takes the secret as its second argument
    for exactly this, and prints it before any row.
    """
    render = inline_lib.section("render.sh")
    card = render[render.index("render_card() {") :]
    assert '[[ -n "$secret_label" ]] && render_key' in card
    assert card.index("render_key") < card.index('for row in "$@"')
    source = _extract_function("success_card")
    assert 'render_card "ready" "setup key" "$key"' in source


def test_install_prints_the_setup_url_and_never_a_password():
    """The card points at the browser setup page, and prints no credential."""
    source = _extract_function("success_card")
    assert "setup key" in source
    assert "Password" not in source
    assert "/setup" in source, "the card opens the setup page, not the login page"
    # The URL the operator must open is a url row, not plain text: it is the
    # thing they copy.
    assert '"panel|$url/setup"' in source


def test_the_card_says_how_to_remove_the_install():
    """The uninstall command is spelled out in full, every time.

    An operator who wants it later is reading a log or a scrollback, not this
    script, so a short form would not be runnable from either.
    """
    source = _extract_function("success_card")
    assert "installer_uninstall_command" in source
    cmd = _extract_function("installer_uninstall_command")
    assert "raw.githubusercontent.com" in cmd
    assert "uninstall --purge -y" in cmd


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
    libs = "\n".join(f'source "{inline_lib.path(n)}"' for n in ("common.sh", "policy.sh"))
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
    # Self-contained: the helpers are inline, so install.sh is the whole
    # installer and a version-script invocation must not reach for a lib tree.
    stage = tmp_path / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALLER_PATH, stage / "install.sh")

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


# ── The recovery journal, run rather than grepped ─────────────────────────
#
# A corrupt update journal is the state an operator reaches after a power loss
# mid-update, and it is the one state where the wrong answer is unrecoverable:
# writes are blocked until recovery resolves it. The behaviour was only ever
# checked by reading the source, which is how a raw python traceback came to
# be printed above the sentence explaining it.


def _journal(install, phase, **extra):
    import json

    data = {"phase": phase, "from_version": "1.0.0", "to_version": "1.0.1", "safety_backup": ""}
    data.update(extra)
    path = Path(install).parent / "data" / "update-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    marker = path.parent / "update-maintenance"
    marker.touch()
    return path, marker


def test_a_corrupt_journal_reports_one_clean_line(tmp_path):
    """No traceback, no trap warning — just what is wrong.

    Both leaked before. A process substitution runs in its own process, so the
    JSONDecodeError went to the terminal while `read` returned non-zero, and
    the ERR trap added a second line. The operator saw two stack traces and
    then the explanation.
    """
    sb, _ = sandbox(tmp_path)
    data = Path(sb).parent / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "update-state.json").write_text("not json{", encoding="utf-8")
    (data / "update-maintenance").touch()

    r = sh_sb(sb, "recover-update", "-y")
    out = r.stdout + r.stderr
    assert "Update state journal is unreadable" in out, out[-500:]
    for noise in ("Traceback", "JSONDecodeError", "Command failed near line"):
        assert noise not in out, f"{noise} leaked above the explanation:\n{out[-500:]}"


def test_an_unknown_phase_refuses_rather_than_guessing(tmp_path):
    """Writes stay blocked. Guessing could activate the wrong tree."""
    sb, _ = sandbox(tmp_path)
    _journal(sb, "wibble")
    r = sh_sb(sb, "recover-update", "-y")
    out = r.stdout + r.stderr
    assert "unknown phase" in out and "writes remain blocked" in out, out[-500:]


@pytest.mark.skipif(os.geteuid() != 0, reason="recover-update is root-gated")
def test_a_preactivation_journal_is_cleared_and_says_so(tmp_path):
    """Nothing was activated, so there is nothing to restore — say which.

    Root-gated, and the skip is the point: CI runs this suite as a non-root
    user, where the installer correctly refused before it did anything. The test
    passed on a root box and failed everywhere else, which is the same failure
    as the source-grep tests — a test that cannot fail where it was written.
    """
    sb, _ = sandbox(tmp_path)
    journal, marker = _journal(sb, "preflight")
    r = sh_sb(sb, "recover-update", "-y")
    out = r.stdout + r.stderr
    assert "pre-activation" in out, out[-500:]
    assert not marker.exists(), "the maintenance marker must be cleared"
    import json

    assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "failed_over"


def test_a_clean_box_says_there_is_nothing_to_do(tmp_path):
    """The common case, and it must not look like a failure."""
    sb, _ = sandbox(tmp_path)
    r = sh_sb(sb, "recover-update", "-y")
    out = r.stdout + r.stderr
    assert "no interrupted update needs recovery" in out, out[-500:]
    assert "Error" not in out, out[-500:]
