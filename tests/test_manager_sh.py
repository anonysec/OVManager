"""Behavioral tests for manager.sh (ovmanager/ovm): day-to-day operations.

The manager runs against an installed tree ($INSTALL_DIR, overridable via
OVM_APP_DIR for hermetic tests) and sources $INSTALL_DIR/scripts/lib/*.sh.
Update/uninstall delegate to install.sh. Tests never touch the live system:
sandbox trees plus stub tools stand in for systemd/curl/docker.
"""

import os
import pty
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANAGER = os.path.join(os.path.dirname(__file__), "..", "manager.sh")
PROMPT_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "prompt.sh"
MANAGER_PATH = Path(MANAGER)
# The operator CLI owns these commands now; contract assertions about them
# belong here rather than in manager.sh.
_CLI_DIR = Path(__file__).resolve().parents[1] / "cli"
CLI_STATUS = _CLI_DIR / "status.py"
CLI_DOCTOR = _CLI_DIR / "doctor.py"
LIB_DIR = REPO / "scripts" / "lib"
SETSID = shutil.which("setsid")


def neutered_manager(tmp_path: Path) -> Path:
    """A copy of the real manager.sh with check_root disabled.

    For the tests that need OVM_APP_DIR to point at a *missing* tree, which the
    full sandbox cannot provide, but whose subject is the not-installed path
    rather than who is allowed to run the command.
    """
    out = tmp_path / "manager.sh"
    # The lib lookup falls back to the script's own directory, and these tests
    # point OVM_APP_DIR at a missing tree on purpose, so the copy has to bring
    # its own libs with it.
    (tmp_path / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    for lib in LIB_DIR.glob("*.sh"):
        shutil.copy(lib, tmp_path / "scripts" / "lib" / lib.name)
    out.write_text(_neuter_root_gate(MANAGER_PATH.read_text(encoding="utf-8")), encoding="utf-8")
    return out


def mgr_nogate(script: Path, *args: str, env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    cmd = ["bash", str(script), *args]
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


def _neuter_root_gate(src: str) -> str:
    """Disable both root gates in a copy of manager.sh.

    Two of them: the id check at the top of the file, which is what actually
    stops a non-root caller, and the check_root function the dispatch arms
    call. Neutralising only the second is not enough — the first runs first, so
    a test of the dispatch would never reach the dispatch.

    Anchored on the code, not on the comment above it: a comment is prose and
    gets reworded, and when it did, this silently stopped neutering anything and
    every dispatch test in the file failed at once.
    """
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('if [[ "$(id -u)" -ne 0 ]]'))
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    # keep the comment block that precedes it, so the neutered copy still reads
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1
    out = lines[:start] + ["# root gate neutered by the test suite"] + lines[end + 1 :]
    src = os.linesep.join(out) + os.linesep
    src = src.replace(
        'check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }',
        "check_root() { :; }  # neutered by the test suite",
        1,
    )
    assert "root gate neutered by the test suite" in src, "the id -u gate was not found"
    assert "check_root() { :; }" in src, "check_root not found"
    return src


def sandbox(tmp_path, gate_root: bool = False):
    """A fake installed tree: manager.sh runs with OVM_APP_DIR pointed here.

    Layout: <tmp>/opt/{manager.sh,install.sh-stub,scripts/lib/*.sh}.
    Returns (env, app_dir).

    The root gate is neutered by default, because almost every test here is
    about which command a verb reaches rather than about who may run it, and
    CI is deliberately non-root. Same idea as the systemctl and ufw shims: the
    sandbox should not depend on the machine's privilege. The root
    requirement is real and deliberate — every command reads .env, which holds
    the admin hash, the JWT key and the secret URL path — so it is held by
    test_every_command_requires_root, which builds its own copy of the script
    with the gate intact.
    """
    app = tmp_path / "opt"
    (app / "scripts" / "lib").mkdir(parents=True)
    src = MANAGER_PATH.read_text(encoding="utf-8")
    if not gate_root:
        src = _neuter_root_gate(src)
    (app / "manager.sh").write_text(src, encoding="utf-8")
    for lib in LIB_DIR.glob("*.sh"):
        shutil.copy(lib, app / "scripts" / "lib" / lib.name)
    (app / "install.sh").write_text('#!/bin/sh\necho "STUB-INSTALLER $@"\n', encoding="utf-8")
    (app / "install.sh").chmod(0o755)
    env = {**os.environ, "OVM_APP_DIR": str(app)}
    return env, app


def mgr_sb_tty(env, app, *args: str, answers: str):
    """Run the sandbox manager with a pty on stdin, so prompts can be answered.

    `ovm reset-password` without -p asks for the password through a hidden
    prompt that only runs when it has a terminal; a pty is the only way to
    exercise the path an operator actually uses.
    """
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            ["bash", str(app / "manager.sh"), *args],
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    finally:
        os.close(slave)
    os.write(master, answers.encode())
    try:
        out, err = proc.communicate(timeout=60)
    finally:
        os.close(master)
    return proc.returncode, out, err


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
        "status",
        "update",
        "restart",
        "logs",
        "backup",
        "tls",
        "recovery",
        "reset-password",
        "doctor",
        "rollback",
        "uninstall",
        "ovm",
        "-p",
        "--fix",
    ):
        assert token in output, f"help missing {token}"


def test_bare_run_prints_usage_and_exits_zero():
    """Bare `ovm` lists the commands. It must never wait for input.

    There is no menu any more, so a stray `ovm` in a script prints the command
    list and returns instead of blocking on a prompt.
    """
    r = mgr()
    assert r.returncode == 0
    assert "USAGE" in r.stderr
    assert "ovm status" in r.stderr


def test_unknown_option_fails():
    r = mgr("--nonsense-flag")
    assert r.returncode == 1


def test_every_core_operation_is_a_command(tmp_path):
    """What the menu used to list is now reachable as a command.

    The menu is gone; the guarantee it gave — full power from one place — is
    that every operation parses and dispatches, which is asserted here against
    the real argument parser rather than against menu text.
    """
    with open(MANAGER, encoding="utf-8") as fh:
        content = fh.read()
    usage = content[content.index("  USAGE") : content.index("  OPTIONS")]
    verbs = (
        "status",
        "start",
        "stop",
        "restart",
        "enable",
        "disable",
        "logs",
        "doctor",
        "tls-status",
        "https",
        "backup",
        "auto-backup",
        "recovery",
        "reset-password",
        "reset-urlpath",
        "update",
        "recover-update",
        "rollback",
        "uninstall",
    )
    for verb in verbs:
        assert verb in usage, f"usage no longer mentions {verb}"
    # ... and each reaches a case arm. Checked in the source rather than by
    # running it: `stop` and `rollback` act on the real service and on
    # /var/backups, so executing them from a test is executing them against the
    # running panel. A sandbox directory does not sandbox systemd.
    arms = re.findall(r"(?m)^\s*([\w|-]+)\)\s", content)
    labels = {label for arm in arms for label in arm.split("|")}
    for verb in verbs:
        assert verb in labels, f"{verb} is not a command case arm"

    # The read-only verbs are safe to actually run, and running them proves the
    # dispatch arms exist rather than merely the parser.
    env, app = sandbox(tmp_path)
    (app / ".env").write_text("PORT=2095\nADMIN_USERNAME=admin\n", encoding="utf-8")
    for verb in ("status", "tls-status", "recovery"):
        r = mgr_sb(env, app, verb)
        assert "Unknown option" not in r.stderr, verb

    for gone in ("manager_menu", "service_submenu", "backup_submenu", "do_tls_menu", "do_recovery_menu"):
        assert gone not in content, f"{gone} should be gone from manager.sh"


def test_service_autostart_commands_are_supported():
    content = MANAGER_PATH.read_text(encoding="utf-8")
    assert "start|stop|restart|enable|disable" in content
    assert 'systemctl "$1" "$SYSTEMD_SERVICE"' in content
    assert "docker update --restart unless-stopped" in content
    assert "docker update --restart no" in content
    # Auto-start state was a menu row; doctor reports it now.
    with open(CLI_DOCTOR, encoding="utf-8") as f:
        assert 'Check("Auto start"' in f.read()


def test_update_delegates_to_installer(tmp_path):
    """`ovm update` execs install.sh update (machine flags pass through)."""
    env, app = sandbox(tmp_path, gate_root=False)
    r = mgr_sb(env, app, "update", "-y")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER update -y" in r.stdout


def test_update_pin_passes_through(tmp_path):
    env, app = sandbox(tmp_path, gate_root=False)
    r = mgr_sb(env, app, "update", "-y", "-v", "v9.9.9")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER update -y -v v9.9.9" in r.stdout


def test_uninstall_delegates_with_purge(tmp_path):
    env, app = sandbox(tmp_path, gate_root=False)
    r = mgr_sb(env, app, "uninstall", "-y", "--purge")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER uninstall -y --purge" in r.stdout


def test_update_requires_install_dir(tmp_path):
    """`ovm update` with no installed tree fails cleanly instead of execing."""
    env = {**os.environ, "OVM_APP_DIR": str(tmp_path / "missing")}
    r = mgr_nogate(neutered_manager(tmp_path), "update", env=env)
    assert r.returncode != 0
    assert "Not installed" in r.stderr


def test_reset_password_rejects_weak_passwords(tmp_path):
    """Same floor + placeholder block the panel applies at boot."""
    env, app = sandbox(tmp_path)
    for weak, hint in (("short", "at least 8"), ("change-me-please-123", "placeholder")):
        r = mgr_sb(env, app, "reset-password", "-p", weak)
        assert r.returncode == 1, r.stderr
        assert hint in r.stderr, r.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="reset-password restarts the service (root only)")
def test_reset_password_passes_the_secret_out_of_argv(tmp_path):
    """The CLI does the rewrite, and the password never reaches argv.

    `ps` shows every process's arguments, so a password passed as
    `--admin-pass` would be readable by any user on the box. The manager hands
    it over in the environment instead.
    """
    env, app = sandbox(tmp_path)
    (app / ".env").write_text("ADMIN_PASSWORD=old-password-123\n", encoding="utf-8")
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}
    r = mgr_sb(env, app, "reset-password", "-p", "brand-new-password")
    assert r.returncode == 0, r.stderr
    calls = marker.read_text(encoding="utf-8")
    assert "reset-password" in calls, calls
    assert "brand-new-password" not in calls, "the secret must not be an argument"
    assert "brand-new-password" not in r.stdout + r.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="the root gate runs before the password prompt")
def test_reset_password_without_a_flag_never_reaches_the_cli(tmp_path):
    """No -p means there is no secret to hand over, so bash prompts instead.

    The prompt cannot be driven from a sandbox (no terminal), so this pins the
    only part that is observable: the CLI is not invoked without a password.
    """
    env, app = sandbox(tmp_path, gate_root=False)
    (app / ".env").write_text("ADMIN_PASSWORD=old-password-123\n", encoding="utf-8")
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}
    r = mgr_sb(env, app, "reset-password")
    assert "No password given" in r.stderr, r.stderr
    assert not marker.exists(), "the CLI must not be called without a password"


def test_reset_password_db_write_is_covered_by_the_cli_tests():
    """The credential is a database row since v16; the CLI tests must pin that."""
    with open(Path(__file__).resolve().parent / "test_cli_accounts.py", encoding="utf-8") as fh:
        accounts = fh.read()
    assert "_write_owner_hash" in accounts, "the CLI tests must pin the database write"
    assert 'read_text(encoding="utf-8") == before' in accounts, "and must prove .env is left untouched"


def test_logs_command_runs_the_cli_on_a_native_install(tmp_path):
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}
    r = mgr_sb(env, app, "logs", "5")
    assert r.returncode == 0, r.stderr
    assert "-m cli.main logs 5" in marker.read_text(encoding="utf-8")


def test_auto_backup_host_timer_wiring():
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "ovmanager-backup.timer" in content
    assert "ovmanager-backup.service" in content
    assert "backup --keep ${keep}" in content
    assert "auto-backup on" in content
    assert "prune_backups" in content


def test_manager_version_matches_panel():
    """manager.sh VERSION tracks the panel version (release checklist)."""
    import re

    manager_src = MANAGER_PATH.read_text(encoding="utf-8")
    mver = re.search(r'^VERSION="([^"]+)"', manager_src, re.M).group(1)
    panel_ver = re.search(r'__version__ = "([^"]+)"', (REPO / "backend" / "version.py").read_text(encoding="utf-8")).group(1)
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
        for path in (MANAGER_PATH, *sorted(LIB_DIR.glob("*.sh")))
        for name, tail, line in tails(path)
        if re.match(r"^\[\[.*\]\]\s*&&", tail)
    ]
    assert not offenders, offenders


def test_status_has_no_machine_output_path():
    """`ovm status` is the human table, full stop.

    --json was removed from the project, so the status module must carry no
    serialiser and no flag to select one. The key set it collects is pinned
    behaviourally by tests/test_cli.py::test_status_collect_healthy, and the
    rows by test_status_is_concise_and_all_is_opt_in below.
    """
    with open(CLI_STATUS, encoding="utf-8") as f:
        content = f.read()
    assert "json" not in content.lower(), "status.py must not serialise for a machine consumer"
    assert "render_json" not in content


def test_doctor_checks_service_disk_panel_cert_backups():
    """doctor covers the beginner-critical checks, each with its fix hint.

    The checks moved to cli/doctor.py; the guarantee is unchanged, so the
    assertions follow the code that now owns it.
    """
    with open(CLI_DOCTOR, encoding="utf-8") as f:
        content = f.read()
    for token in ("Panel health", "Certificate", "Backup", "Disk", "Service"):
        assert token in content, f"doctor missing {token}"
    for fix in ("ovm restart", "ovm backup", "ovm https", "ovm logs"):
        assert fix in content, f"doctor missing fix hint {fix}"


def test_rollback_restores_newest_snapshot():
    """do_rollback restores the newest code snapshot and re-verifies health."""
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "do_rollback()" in content
    assert "latest_snapshot panel" in content
    assert "Rolled back and healthy" in content


def test_doctor_fix_reaches_the_fixer_in_either_flag_order(tmp_path):
    """`ovm doctor --fix` is the documented spelling and it fixed nothing.

    The `doctor` arm resolved ACTION the moment it saw the subcommand, which is
    before `--fix` has been parsed — so FIX was still 0, ACTION stayed "doctor",
    and the operator got the problem list with none of the fixes. Only the
    flags-first form ever reached the fixer. ACTION is now resolved after the
    loop, and both spellings are pinned here.

    `_cli_py` is the single funnel to the CLI and it execs
    $INSTALL_DIR/.venv/bin/python, so a stand-in that echoes its arguments
    shows exactly which subcommand was routed, through the real code path.
    """
    app = tmp_path / "tree"
    stub = app / ".venv" / "bin" / "python"
    stub.parent.mkdir(parents=True)
    stub.write_text('#!/bin/sh\necho "CLI:$*"\n', encoding="utf-8")
    stub.chmod(0o755)

    script = neutered_manager(tmp_path)
    env = {**os.environ, "OVM_APP_DIR": str(app)}

    for args, expected in (
        (("doctor", "--fix"), "doctor-fix"),
        (("--fix", "doctor"), "doctor-fix"),
        (("doctor",), "-m cli.main doctor"),
    ):
        r = mgr_nogate(script, *args, env=env)
        assert expected in r.stdout, (args, r.stdout, r.stderr)


def test_doctor_and_rollback_dispatch_past_parse(tmp_path):
    """Regression: every main-branch verb must exist in parse_args too
    (doctor/rollback once died as 'Unknown option' in parse)."""
    env = {**os.environ, "OVM_APP_DIR": str(tmp_path / "missing")}
    script = neutered_manager(tmp_path)
    for cmd in ("doctor", "rollback", "recover-update"):
        r = mgr_nogate(script, cmd, env=env)
        assert "Unknown option" not in r.stderr, cmd
    # doctor runs the CLI now, which reports the missing install itself;
    # rollback and recover-update stay in bash and still die in manager.sh.
    for cmd in ("rollback", "recover-update"):
        r = mgr_nogate(script, cmd, env=env)
        assert "Not installed" in r.stderr, (cmd, r.stderr)


def test_doctor_covers_backup_format_and_permissions():
    """doctor must recognize the .ovmbak format and enforce private state
    permissions (defects: backup-age ignored bundles, world-readable db)."""
    with open(CLI_DOCTOR, encoding="utf-8") as f:
        content = f.read()
    assert ".ovmbak" in content
    assert "Permissions" in content


def test_status_is_concise_and_all_is_opt_in():
    """status answers 'is it up?'; paths and mode need --all."""
    with open(CLI_STATUS, encoding="utf-8") as f:
        src = f.read()
    assert "show_all" in src, "status must gate the extra rows behind --all"
    with open(MANAGER, encoding="utf-8") as f:
        content = f.read()
    assert "-a|--all" in content
    assert '[[ "$SHOW_ALL" -eq 1 ]] && sargs+=(--all)' in content
    for row in ("'Service'", "'Health'", "'Version'", "'Open'"):
        assert row in src, row


def _stub_cli_python(app, tmp_path, exit_code=0):
    """A stub venv python that records argv and exits `exit_code`."""
    venv_bin = app / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    stub = venv_bin / "python"
    stub.write_text(f'#!/bin/sh\necho "PYCLI $@" >> "$MARKER"\nexit {exit_code}\n', encoding="utf-8")
    stub.chmod(0o755)
    marker = tmp_path / "calls.log"
    return stub, marker


def test_cli_is_the_implementation_for_read_commands(tmp_path):
    """status/doctor/tls-status run the CLI: there is no bash twin left.

    The stub venv python records its argv, so the path is proven without a
    real install.
    """
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}

    for command in ("status", "doctor", "tls-status"):
        marker.unlink(missing_ok=True)
        r = mgr_sb(env, app, command)
        assert r.returncode == 0, (command, r.stderr)
        calls = marker.read_text(encoding="utf-8")
        assert f"-m cli.main {command}" in calls, (command, calls)
        assert "--in-container" not in calls, "a native install needs no container flag"


def test_cli_py_propagates_failure_without_double_running(tmp_path):
    """A non-zero twin exit is the answer, not a reason to re-run in bash.

    `ovm status` on an unhealthy panel exits 1 through the twin; the bash
    fallback must not print a second, conflicting report."""
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path, exit_code=1)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}

    r = mgr_sb(env, app, "status")
    assert r.returncode == 1, r.stderr
    assert marker.read_text(encoding="utf-8").count("PYCLI") == 1
    assert "Service" not in r.stdout, "bash twin must not run after the twin answered"


@pytest.mark.skipif(os.geteuid() != 0, reason="recovery is root-gated")
def test_cli_py_unsupported_command_uses_bash(tmp_path):
    """Unported commands never touch the twin, even with a venv present."""
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}
    (app / ".env").write_text("PORT=2095\nURLPATH=sekret\nADMIN_USERNAME=admin\n", encoding="utf-8")
    r = mgr_sb(env, app, "recovery")
    assert "URL" in r.stderr and "admin" in r.stderr
    assert not marker.exists(), "recovery stays host-side"


def test_dispatch_shape_matches_the_documented_split():
    """Root-free check of which commands reach the CLI and which stay host-side.

    In a container there is no docker CLI and no host .env, so logs and
    reset-urlpath cannot run there; everything else can, and is handed the
    host's view of the service. Pinned as source because the behavioural docker
    test needs a real container.
    """
    with open(MANAGER, encoding="utf-8") as fh:
        content = fh.read()

    cli_block = content[content.index("_cli_py() {") : content.index("# One wrapper per command")]
    assert "docker exec " in cli_block and "ovmanager /app/.venv/bin/python -m cli.main" in cli_block
    assert "--install-dir /app" in cli_block and "--data-dir /app/data" in cli_block
    assert "--in-container" in cli_block and "--service-state" in cli_block
    assert "Panel virtualenv missing" in cli_block, "a broken venv must say what to do"

    for fn in ("cmd_logs()", "cmd_doctor_fix()"):
        body = content[content.index(fn) : content.index("\n}\n", content.index(fn))]
        assert "is_docker_mode" in body, f"{fn} must branch on the install mode"
    assert "if is_docker_mode; then reset_urlpath_now" in content
    # reset-password has one path for every install: bash prompts, the CLI (in
    # the container when there is one) writes the row.
    assert "_cli_py reset-password" in content, "the CLI is the only writer"
    dispatch = content[content.rindex("reset-password)") : content.rindex("reset-urlpath)")]
    assert "do_reset_password" in dispatch, "the dispatch must reach the one reset path"
    assert "is_docker_mode" not in dispatch and "cli.main" not in dispatch, (
        "the docker branch lives in _cli_py now; the dispatch must not fork again"
    )

    # SHOW_ALL is forwarded numerically, not by ${VAR:+--all}: a set-but-zero
    # variable still expands, which is how a flag reached the twin unasked.
    assert '[[ "$SHOW_ALL" -eq 1 ]] && sargs+=(--all)' in content
    assert 'backup ${BACKUP_KEEP:+--keep "$BACKUP_KEEP"}' in content, "retention must be forwarded"

    # Nothing may call a deleted bash twin or the removed fallback machinery.
    for gone in ("do_status", "do_doctor", "backup_now", "do_tls_status", "_cli_or_bash", "_cli_supported", "OVM_CLI_PY"):
        assert gone not in content, f"{gone} should be gone from manager.sh"
    for gone in ("JSON", "--json", "-j)"):
        assert gone not in content, f"{gone} is a removed machine-output leftover"


def test_tls_status_runs_the_cli_and_never_falls_back(tmp_path):
    """`ovm tls-status` is a CLI command; the bash copy is gone."""
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}

    r = mgr_sb(env, app, "tls-status")
    assert r.returncode == 0, r.stderr
    assert "tls-status" in marker.read_text(encoding="utf-8")


def test_cli_py_runs_inside_the_container_on_docker_installs(tmp_path):
    """A docker install runs the same CLI, in the container, with host facts."""
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "ovmanager-compose.yml").write_text("services: {}\n", encoding="utf-8")
    calls = tmp_path / "docker.log"
    docker_bin = tmp_path / "bin"
    docker_bin.mkdir()
    # Only `docker ps` answers here; `docker exec` needs a live container, which
    # is verified by hand against a real install rather than in the sandbox.
    (docker_bin / "docker").write_text(
        '#!/bin/sh\nprintf "docker %s\\n" "$*" >> "$DOCKER_LOG"\ncase "${1:-}" in ps) echo ovmanager ;; esac\nexit 0\n',
        encoding="utf-8",
    )
    (docker_bin / "docker").chmod(0o755)
    env = {
        **env,
        "MARKER": str(tmp_path / "calls.log"),
        "DOCKER_LOG": str(calls),
        "OVM_DATA_DIR": str(data),
        "PATH": f"{docker_bin}:{env['PATH']}",
    }
    r = mgr_sb(env, app, "status")
    assert r.returncode == 0, r.stderr
    seen = calls.read_text(encoding="utf-8")
    assert "docker exec ovmanager /app/.venv/bin/python -m cli.main" in seen, seen
    assert "--install-dir /app" in seen and "--data-dir /app/data" in seen, seen
    assert "--in-container" in seen and "--service-state running" in seen, seen
    # The host has no venv, so nothing may have run it directly.
    assert not (tmp_path / "calls.log").exists(), "a docker install has no host venv"


@pytest.mark.skipif(os.geteuid() != 0, reason="backup is root-gated")
def test_cli_py_forwards_backup_keep(tmp_path):
    """`ovm backup --keep 30` must reach the twin; retention is not cosmetic."""
    env, app = sandbox(tmp_path)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}
    r = mgr_sb(env, app, "backup", "--keep", "30")
    assert r.returncode == 0, r.stderr
    assert "backup --keep 30" in marker.read_text(encoding="utf-8")


@pytest.mark.skipif(os.geteuid() != 0, reason="reset-password restarts the service (root only)")
def test_cli_py_restarts_panel_after_reset(tmp_path):
    """The bash twin restarts the panel itself; a delegated reset must too.

    systemctl is stubbed on PATH so the assertion is about what manager.sh
    asks the system to do, not about this machine's init."""
    env, app = sandbox(tmp_path)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    (app / ".env").write_text("ADMIN_PASSWORD=placeholder\n", encoding="utf-8")
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    systemctl = stub_bin / "systemctl"
    systemctl.write_text('#!/bin/sh\necho "SYSTEMCTL $@" >> "$MARKER"\nexit 0\n', encoding="utf-8")
    systemctl.chmod(0o755)
    env = {**env, "MARKER": str(marker), "PATH": f"{stub_bin}:{env['PATH']}"}
    r = mgr_sb(env, app, "reset-password", "-p", "long-enough-password")
    assert r.returncode == 0, r.stderr
    calls = marker.read_text(encoding="utf-8")
    assert "reset-password" in calls
    assert "long-enough-password" not in calls, "the secret must travel in the environment"
    assert "SYSTEMCTL restart ovmanager.service" in calls, calls


@pytest.mark.skipif(os.geteuid() != 0, reason="reset-password is root-gated")
def test_reset_password_without_flag_never_passes_secret_in_argv(tmp_path):
    """No -p means the password is prompted for in bash, never echoed to argv."""
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    (app / ".env").write_text("ADMIN_PASSWORD=placeholder\n", encoding="utf-8")
    env = {**env, "MARKER": str(marker)}
    r = mgr_sb(env, app, "reset-password")
    assert "No password given" in r.stderr, r.stderr
    assert not marker.exists(), "the twin must not be called without a password"


def test_cli_py_status_passes_only_the_requested_flags(tmp_path):
    """`ovm status` hands the twin exactly what the operator asked for.

    A set-but-zero variable still expands under `${VAR:+...}`, which is how a
    plain `ovm status` once passed a flag nobody asked for. Only visible with a
    twin present, so the stub stands in.
    """
    env, app = sandbox(tmp_path, gate_root=False)
    _stub_cli_python(app, tmp_path)
    out = tmp_path / "twin.out"
    (app / ".venv" / "bin" / "python").write_text(
        f'#!/bin/sh\necho "PYCLI $@" >> "$MARKER"\nprintf \'{{"health": "ok"}}\\n\' > {out}\nexit 0\n',
        encoding="utf-8",
    )
    (app / ".venv" / "bin" / "python").chmod(0o755)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}

    r = mgr_sb(env, app, "status")
    assert r.returncode == 0, r.stderr
    assert out.read_text(encoding="utf-8").strip(), "twin should have run"
    assert "-m cli.main status\n" in marker.read_text(encoding="utf-8"), "no extra flags by default"
    assert r.stdout.strip() == "", "the twin wrote the report; the shell must not add any"

    r = mgr_sb(env, app, "status", "--all")
    assert "-m cli.main status --all\n" in marker.read_text(encoding="utf-8"), "--all must reach the twin"

    # The machine-output flag is gone everywhere, so it is rejected here.
    marker.unlink()
    r = mgr_sb(env, app, "status", "--json")
    assert r.returncode == 1, r.stdout
    assert "Unknown option: --json" in r.stderr
    assert not marker.exists(), "a rejected flag must never reach the twin"


# ── confirm() unattended behaviour ───────────────────────────────────────
#
# Sourced directly rather than driven through `ovm rollback` on purpose: that
# command stops the service and extracts a snapshot from /var/backups, so a
# test of it is a test that can stop the running panel. The function is the
# whole policy, so the function is what gets tested.
_CONFIRM_HARNESS = """
set -u
source "{lib}" >/dev/null 2>&1 || {{ echo "SOURCE-FAILED"; exit 9; }}
confirm "Proceed?" {default} >/dev/null 2>&1 && echo YES || echo NO
"""


def _confirm(yes: int, default: str) -> str:
    """Ask confirm() with no terminal, the way a cron job or CI step would."""
    script = _CONFIRM_HARNESS.format(lib=PROMPT_LIB, default=default)
    cmd = ["bash", "-c", script]
    if SETSID:  # drop the controlling tty: this is the unattended case
        cmd = [SETSID, *cmd]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=20,
        stdin=subprocess.DEVNULL,
        env={"PATH": os.environ["PATH"], "YES": str(yes), "HOME": os.environ.get("HOME", "/root")},
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_confirm_answers_yes_unattended_by_default():
    """A non-destructive confirmation keeps the documented 'default answer'."""
    assert _confirm(yes=0, default="y") == "YES"


def test_confirm_fails_closed_when_asked_to_default_to_no():
    """A destructive confirmation must not proceed just because nobody is there.

    This is the whole point of the second argument. `ovm rollback` and
    `ovm uninstall` pass n, so running them from a pipeline with no terminal
    declines instead of replacing the running install with a snapshot.
    """
    assert _confirm(yes=0, default="n") == "NO"


def test_yes_flag_overrides_either_default():
    """-y still means yes: an operator who asked for it gets it."""
    assert _confirm(yes=1, default="n") == "YES"


def test_destructive_call_sites_pass_a_default_of_no():
    """Guards against a future call site forgetting the second argument."""
    rollback = MANAGER_PATH.read_text(encoding="utf-8")
    assert 'confirm "Restore the pre-update tree and restart?" n' in rollback
    installer = (MANAGER_PATH.parent / "install.sh").read_text(encoding="utf-8")
    assert 'confirm "Remove OVManager and stop the service?" n' in installer


# ── the root requirement ──────────────────────────────────────────────────

# Every ovm command reads .env, which holds ADMIN_PASSWORD_HASH,
# JWT_SECRET_KEY and the secret URL path that is the panel's only defence
# against scanners. So all of them require root, the read-only ones included.
ROOT_GATED_VERBS = (
    "status",
    "status --all",
    "logs",
    "logs -f",
    "doctor",
    "doctor-fix",
    "tls-status",
    "recovery",
    "owner-claim",
    "completion",
    "version-script",
    "script-version",
    "start",
    "stop",
    "restart",
    "enable",
    "disable",
    "backup",
    "https --self",
    "reset-password -p longenoughpassword",
    "reset-urlpath",
    "update",
    "rollback",
    "uninstall",
)


def _make_traversable(path: Path) -> None:
    """Let another uid read the sandbox, up to but not including /tmp.

    pytest's tmp_path is 0700 and owned by whoever runs the suite, so a
    dropped-privilege caller cannot even reach manager.sh — it would fail with
    "Permission denied" and the test would pass for the wrong reason.
    """
    for parent in [path, *path.parents]:
        if parent == Path("/tmp") or parent == parent.parent:
            break
        try:
            parent.chmod(parent.stat().st_mode | 0o055)
        except OSError:  # pragma: no cover
            pass
    for item in path.rglob("*"):
        try:
            item.chmod(item.stat().st_mode | 0o055)
        except OSError:  # pragma: no cover
            pass


def _run_as_non_root(env, _app, script, *args):
    """Run a manager.sh as a user who is definitely not root.

    When the suite is already non-root (CI is, deliberately) that is simply the
    current process. When it is root, drop to nobody — which is also the only
    way to exercise the gate from a root developer box.
    """
    cmd = ["bash", script, *args]
    if SETSID:
        cmd = [SETSID, *cmd]
    if os.geteuid() == 0:
        if not shutil.which("setpriv"):
            pytest.skip("needs root to drop privileges, or setpriv to do it")
        cmd = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env={**env, "HOME": "/tmp"},
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize("args", [("help",), ("-h",), ("--help",), ()])
def test_help_needs_no_root(tmp_path, args):
    """`ovm help` and a bare `ovm` are the exceptions, and they really work.

    They print usage before anything is sourced, because the libraries live
    inside the install tree — 0700 and root-owned — so a non-root caller could
    never load them. Pointed at the real tree, which is where
    /usr/local/bin/ovmanager lives with no sibling scripts/lib.
    """
    app = tmp_path / "installed"
    app.mkdir(parents=True, exist_ok=True)
    script = app / "ovmanager"
    script.write_text(MANAGER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    if os.geteuid() == 0:
        _make_traversable(tmp_path)
    env = {**os.environ, "OVM_APP_DIR": "/opt/ovmanager"}
    r = _run_as_non_root(env, app, str(script), *args)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"`ovm {' '.join(args)}` exited {r.returncode}:\n{out[-300:]}"
    assert "USAGE" in out, out[-300:]
    assert "scripts/lib not found" not in out


@pytest.mark.parametrize("verb", ROOT_GATED_VERBS)
def test_every_command_requires_root(tmp_path, verb):
    """A non-root caller gets the root message, not something cryptic.

    This was previously accidental: the install tree is mode 0700 and owned by
    uid 1001, so a non-root `ovm status` failed deep inside the script with
    "scripts/lib not found", which says nothing about why. The packaging that
    caused it is fixed, so the requirement has to be stated instead.
    """
    # The real manager.sh, alone in an empty directory — that is where it
    # really lives (/usr/local/bin/ovmanager), with no sibling scripts/lib. The
    # full sandbox cannot model this, because it carries its own readable libs
    # and the lookup falls back to them, which is precisely why the first
    # version of this change passed its tests and then failed in production.
    app = tmp_path / "installed"
    app.mkdir(parents=True, exist_ok=True)
    script = app / "ovmanager"
    script.write_text(MANAGER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    if os.geteuid() == 0:
        _make_traversable(tmp_path)
    env = {**os.environ, "OVM_APP_DIR": "/opt/ovmanager"}
    r = _run_as_non_root(env, script.parent, str(script), *verb.split())
    out = r.stdout + r.stderr
    assert "Must run as root" in out, f"`ovm {verb}` did not require root:\n{out[-400:]}"
    assert "scripts/lib not found" not in out, "failed for the wrong reason: the gate runs after the lib sourcing"


# ── restore ────────────────────────────────────────────────────────────
# `ovm restore` replaces the live database, so these tests pin its guard rails
# — list, refuse, never prompt — and stub the CLI through the real
# _cli_py funnel. A restore that actually ran would run against this box's
# panel; the transaction itself is covered hermetically in
# tests/test_cli_backup.py, which proves the safety copy is taken first.


def test_restore_without_a_name_lists_and_never_prompts(tmp_path):
    """A bare `ovm restore` is the listing: no prompt, no service change."""
    env, app = sandbox(tmp_path)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    env = {**env, "MARKER": str(marker)}

    r = mgr_sb(env, app, "restore")
    assert r.returncode == 0, r.stderr
    calls = marker.read_text(encoding="utf-8")
    assert calls.count("PYCLI") == 1, calls
    assert "-m cli.main restore" in calls, "the listing is the CLI's, not a bash twin"
    assert "Cancelled" not in r.stderr
    assert "cancel" not in r.stderr.lower()


@pytest.mark.skipif(
    os.geteuid() != 0,
    reason="restore checks root before it prompts, so an unprivileged run never reaches the confirmation",
)
def test_restore_refuses_without_confirmation(tmp_path):
    """No terminal and no -y is a NO, and the CLI is never reached."""
    env, app = sandbox(tmp_path)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    backup = data / "backups" / "ovmanager-backup-20260101_000000-v1.ovmbak"
    backup.write_bytes(b"x")
    env = {**env, "MARKER": str(marker), "OVM_DATA_DIR": str(data)}

    r = mgr_sb(env, app, "restore", backup.name)
    assert r.returncode != 0, r.stderr
    assert "Cancelled" in r.stderr
    assert not marker.exists(), "an unconfirmed restore must not reach the CLI"
    assert backup.read_bytes() == b"x"


def test_restore_rejects_an_unknown_name_before_it_prompts(tmp_path):
    """A typo must read as a typo, not as a cancelled prompt."""
    env, app = sandbox(tmp_path)
    _stub_cli_python(app, tmp_path)
    marker = tmp_path / "calls.log"
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    env = {**env, "MARKER": str(marker), "OVM_DATA_DIR": str(data)}

    for bad in ("nope.ovmbak", "../ovmanager.db"):
        r = mgr_sb(env, app, "restore", bad)
        assert r.returncode != 0, (bad, r.stderr)
        assert "Cancelled" not in r.stderr, bad
        assert r.stderr.strip(), bad
    assert not marker.exists()


def test_restore_is_documented_and_dispatched():
    """`ovm restore` is in the usage, in parse_args and in the dispatch, and
    its confirmation defaults to NO — the convention `uninstall` follows here."""
    content = MANAGER_PATH.read_text(encoding="utf-8")
    usage = content[content.index("  USAGE") : content.index("  OPTIONS")]
    assert "ovm restore [NAME]          List data backups, or restore one by name" in usage
    assert re.search(r"(?m)^\s*restore\)\s", content), "no parse_args or dispatch arm"
    assert "do_restore()" in content
    assert 'confirm "Replace the live database with this backup?" n' in content


# ── owner-claim / completion / version-script (new commands) ───────────


def test_owner_claim_prints_a_fresh_key_into_the_data_dir(tmp_path):
    """The claim key is regenerable *because* it is not the credential.

    Minting twice is the point of the command, so this asserts both writes
    land and that they differ — a fixed key would be a static credential.
    """
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    env = {**env, "OVM_DATA_DIR": str(data)}

    first = mgr_sb(env, app, "owner-claim")
    assert first.returncode == 0, first.stderr
    key_file = data / "owner-claim.key"
    assert key_file.is_file()
    assert key_file.stat().st_mode & 0o777 == 0o600, "the key must not be world-readable"
    written = key_file.read_text(encoding="utf-8").strip()
    assert written in first.stdout + first.stderr, "the key must be printed"
    assert len(written) == 32 and all(c in "0123456789abcdef" for c in written)

    second = mgr_sb(env, app, "owner-claim")
    assert second.returncode == 0, second.stderr
    assert key_file.read_text(encoding="utf-8").strip() != written, "a reprint must be a new key"


def test_owner_claim_refuses_when_not_installed(tmp_path):
    env, app = sandbox(tmp_path)
    env = {**env, "OVM_APP_DIR": str(tmp_path / "missing"), "OVM_DATA_DIR": str(tmp_path / "data")}
    r = mgr_sb(env, app, "owner-claim")
    assert r.returncode != 0
    assert "Not installed" in r.stderr


def test_completion_writes_a_sourced_file_and_prints_the_source_line(tmp_path):
    """Bash completion for the subcommands and flags, plus how to activate it."""
    env, app = sandbox(tmp_path)
    etc = tmp_path / "etc"
    env = {**env, "OVM_COMPLETION_DIR": str(etc)}

    r = mgr_sb(env, app, "completion")
    assert r.returncode == 0, r.stderr
    path = etc / "ovm"
    assert path.is_file()
    assert f"source {path}" in r.stderr, r.stderr

    body = path.read_text(encoding="utf-8")
    for token in ("complete -F _ovm ovm ovmanager", "owner-claim", "reset-password", "--purge"):
        assert token in body, token
    subprocess.run(["bash", "-n", str(path)], check=True)

    # The function completes the real surface, not a stub list.
    harness = f"source {path}; COMP_WORDS=(ovm ow); COMP_CWORD=1; _ovm; printf '%s\\n' \"${{COMPREPLY[@]}}\""
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "owner-claim" in r.stdout, r.stdout


def test_completion_lists_every_dispatched_subcommand(tmp_path):
    """Drift guard: a subcommand the parser accepts must complete.

    The list is hand-kept in two places (parse_args and OVM_SUBCOMMANDS), so
    this is what keeps a new command from being invisible to completion.
    """
    content = MANAGER_PATH.read_text(encoding="utf-8")
    words = re.search(r"OVM_SUBCOMMANDS=\"([^\"]+)\"", content).group(1).split()
    for arm in re.findall(r"(?m)^\s*([a-z][a-z-]+)\)\s+ACTION=", content):
        assert arm in words, f"{arm} is dispatched but not completed"


def test_version_script_delegates_to_the_installer(tmp_path):
    """`ovm version-script` answers with the installer's own version/commit.

    The stub stands in for the installed install.sh so the assertion is about
    the delegation, not about a checkout that may or may not have git.
    """
    env, app = sandbox(tmp_path)
    r = mgr_sb(env, app, "version-script")
    assert r.returncode == 0, r.stderr
    assert "STUB-INSTALLER version-script" in r.stdout + r.stderr
    r = mgr_sb(env, app, "script-version")
    assert "STUB-INSTALLER version-script" in r.stdout + r.stderr


def test_the_three_new_commands_are_documented(tmp_path):
    """usage(), parse_args and the dispatch all know them."""
    content = MANAGER_PATH.read_text(encoding="utf-8")
    usage = content[content.index("  USAGE") : content.index("  OPTIONS")]
    for line in ("ovm owner-claim", "ovm completion", "ovm version-script"):
        assert line in usage, line
    for action in ("owner-claim", "completion"):
        assert re.search(rf"(?m)^\s*{re.escape(action)}\)\s", content), action
    assert re.search(r"(?m)^\s*version-script\|script-version\)\s", content), "version-script alias"


def test_no_reset_path_writes_a_credential_to_env(tmp_path):
    """.env receives no password and no hash — the credential is a row.

    The reset used to rewrite ADMIN_PASSWORD_HASH in .env (and, on its older
    fallback, ADMIN_PASSWORD in plaintext). backend/config.py ignores both and
    seeds.py imports the hash once, on the fresh-install path, so the command
    reported success while the old password kept working.
    """
    content = MANAGER_PATH.read_text(encoding="utf-8")
    assert 'pass_line="ADMIN_PASSWORD=' not in content
    assert "printf 'ADMIN_PASSWORD=" not in content
    assert "ADMIN_PASSWORD_HASH=" not in content, "the hash must not be written either"
    # Every remaining mention is a comment explaining why .env holds none.
    offenders = [line.strip() for line in content.splitlines() if "ADMIN_PASSWORD" in line and not line.strip().startswith("#")]
    assert not offenders, offenders

    # Docker mode whose container cannot answer: nothing may reach .env, and
    # the command must fail loudly rather than report a change it did not make.
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "ovmanager-compose.yml").write_text("services: {}\n", encoding="utf-8")
    before = "PORT=2095\nADMIN_USERNAME=admin\n"
    (app / ".env").write_text(before, encoding="utf-8")
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "docker").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (stub_bin / "docker").chmod(0o755)
    env = {**env, "OVM_DATA_DIR": str(data), "PATH": f"{stub_bin}:{env['PATH']}"}

    r = mgr_sb(env, app, "reset-password", "-p", "long-enough-password")
    body = (app / ".env").read_text(encoding="utf-8")
    assert body == before, "no reset path may write .env"
    assert r.returncode != 0, "a docker exec that fails must fail the command"
    assert "not changed" in r.stderr, r.stderr


def test_the_docker_reset_runs_the_cli_where_the_database_is(tmp_path):
    """Docker has no host venv, so the row is written from inside the container.

    The command has to reach /app/data — the mounted volume holding
    ovmanager.db — and the secret has to travel by environment. `-e NAME` with
    no value is the one form that keeps it out of `ps` on the host: docker
    reads it from its own environment.
    """
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "ovmanager-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (app / ".env").write_text("PORT=2095\nADMIN_USERNAME=admin\n", encoding="utf-8")

    marker = tmp_path / "docker.log"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "docker").write_text(
        '#!/bin/sh\necho "DOCKER $*" >> "$MARKER"\n[ "$1" = ps ] && exit 1\nexit 0\n', encoding="utf-8"
    )
    (stub_bin / "docker").chmod(0o755)
    stub_curl = stub_bin / "curl"
    stub_curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub_curl.chmod(0o755)
    systemctl = stub_bin / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)
    env = {**env, "OVM_DATA_DIR": str(data), "MARKER": str(marker), "PATH": f"{stub_bin}:{env['PATH']}"}

    r = mgr_sb(env, app, "reset-password", "-p", "long-enough-password")
    assert r.returncode == 0, r.stderr
    calls = marker.read_text(encoding="utf-8")
    exec_line = next(line for line in calls.splitlines() if line.startswith("DOCKER exec"))
    assert "-e OVM_ADMIN_PASS" in exec_line, exec_line
    assert "OVM_ADMIN_PASS=" not in exec_line, f"the secret must not be an argument: {exec_line}"
    assert "ovmanager /app/.venv/bin/python -m cli.main" in exec_line, exec_line
    assert "--install-dir /app --data-dir /app/data" in exec_line, exec_line
    assert exec_line.endswith(" reset-password"), exec_line
    assert "long-enough-password" not in calls, "the secret reached the docker command line"
    assert "long-enough-password" not in r.stdout + r.stderr


def _sandbox_cli(app, data):
    """An installed tree whose .venv runs the real CLI out of this repo.

    The CLI resolves its own imports (cli/, backend/) from the checkout, and
    the install tree supplies .env, the data dir and the venv path manager.sh
    insists on. Only the interpreter path is faked.
    """
    (app / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    wrapper = app / ".venv" / "bin" / "python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    db = data / "ovmanager.db"
    return db, {"PYTHONPATH": str(REPO)}


def _seed_owner(db_path, username, password):
    from sqlalchemy import create_engine

    from backend.auth.hash import hash_password
    from backend.db.models import Admin

    engine = create_engine(f"sqlite:///{db_path}")
    Admin.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(Admin.__table__.insert().values(username=username, password=hash_password(password), disabled=False))
    engine.dispose()


def _authenticates(db_path, username, password):
    """The panel's own authentication against the row on disk."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.auth.auth import authenticate_user

    engine = create_engine(f"sqlite:///{db_path}")
    db = sessionmaker(bind=engine)()
    try:
        return authenticate_user(db, username, password) is not None
    finally:
        db.close()
        engine.dispose()


def test_reset_password_interactive_path_changes_the_row(tmp_path):
    """The prompting path must change the credential, not merely exit 0.

    This is the assertion whose absence let the bug ship: the prompt used to
    hash into ADMIN_PASSWORD_HASH in .env, which nothing reads on an installed
    panel, so `ovm reset-password` printed "updated" and the old password kept
    working. Driven through a pty because the prompt needs a terminal, and then
    authenticated against the real row — old password out, new password in.
    """
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    db, extra = _sandbox_cli(app, data)
    _seed_owner(db, "admin", "old-owner-password-123")
    before = f"PORT=2095\nADMIN_USERNAME=admin\nDATA_DIR={data}\n"
    (app / ".env").write_text(before, encoding="utf-8")

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    for name, body in (("curl", "#!/bin/sh\nexit 0\n"), ("systemctl", "#!/bin/sh\nexit 0\n")):
        stub = stub_bin / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    env = {**env, **extra, "PATH": f"{stub_bin}:{env['PATH']}"}

    rc, out, err = mgr_sb_tty(env, app, "reset-password", answers="new-owner-password-123\nnew-owner-password-123\n")
    assert rc == 0, err or out
    assert _authenticates(db, "admin", "new-owner-password-123"), "the new password must work"
    assert not _authenticates(db, "admin", "old-owner-password-123"), "the old password must be dead"
    assert (app / ".env").read_text(encoding="utf-8") == before, ".env is not part of the credential path"


def test_reset_password_interactive_mismatch_leaves_the_row_alone(tmp_path):
    """A mistyped confirmation changes nothing — and says so."""
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    db, extra = _sandbox_cli(app, data)
    _seed_owner(db, "admin", "old-owner-password-123")
    (app / ".env").write_text(f"PORT=2095\nADMIN_USERNAME=admin\nDATA_DIR={data}\n", encoding="utf-8")
    env = {**env, **extra}

    rc, _, err = mgr_sb_tty(env, app, "reset-password", answers="new-owner-password-123\ntypo-owner-123\n")
    assert rc != 0
    assert "do not match" in err, err
    assert _authenticates(db, "admin", "old-owner-password-123"), "a mismatch must not touch the row"


def test_owner_claim_warns_when_the_panel_already_has_an_owner(tmp_path):
    """A key nobody can claim is a dead end, so say so before printing it.

    The panel is asked first (its GET is public). A stub curl answers as a
    claimed panel would; the key is still printed, because the file is
    harmless and the operator may be mid-recovery.
    """
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("#!/bin/sh\nprintf '{\"claimable\": false}\\n'\nexit 0\n", encoding="utf-8")
    (stub_bin / "curl").chmod(0o755)
    env = {**env, "OVM_DATA_DIR": str(data), "PATH": f"{stub_bin}:{env['PATH']}"}

    r = mgr_sb(env, app, "owner-claim")
    assert r.returncode == 0, r.stderr
    assert "already has an owner" in r.stderr, r.stderr
    assert "reset-password" in r.stderr
    assert (data / "owner-claim.key").is_file(), "the key is still written"


def test_owner_claim_is_quiet_when_the_panel_cannot_answer(tmp_path):
    """No panel listening (the usual case on a fresh box) is not an error."""
    env, app = sandbox(tmp_path)
    data = tmp_path / "data"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "curl").write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    (stub_bin / "curl").chmod(0o755)
    env = {**env, "OVM_DATA_DIR": str(data), "PATH": f"{stub_bin}:{env['PATH']}"}

    r = mgr_sb(env, app, "owner-claim")
    assert r.returncode == 0, r.stderr
    assert "already has an owner" not in r.stderr, r.stderr
    assert (data / "owner-claim.key").is_file()
