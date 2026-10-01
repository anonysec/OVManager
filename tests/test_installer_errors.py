"""install.sh failure paths: the exit code and the message on stderr.

The installer has four documented exit codes — 0 ok, 1 error, 2 already
installed/cancelled, 130 interrupted (see the EXIT section of `--help`) — and
scripts branch on them. Failures report on stderr; stdout carries the ready
card and nothing else, so a caller that captures stdout never has to strip a
diagnostic out of it.

These paths all exit before check_root(), so nothing on the host is touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
SETSID = shutil.which("setsid")


def run_installer(*args, env=None, installer=None):
    """Run install.sh as a subprocess with no controlling terminal."""
    cmd = ["bash", str(installer or INSTALLER), *args]
    if SETSID:
        cmd = [SETSID, *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env={**os.environ, **(env or {})},
    )


DIE_CASES = [
    ("--tls", "9"),
    ("--tls",),
    ("--mode",),
    ("-p",),
    ("--version", "not-a-version"),
    ("--bogus-flag",),
    ("install",),
    ("status",),
]


@pytest.mark.parametrize("args", DIE_CASES, ids=lambda a: " ".join(a))
def test_die_paths_exit_one_with_the_reason_on_stderr(args):
    r = run_installer(*args)
    assert r.returncode == 1, r.stderr
    assert r.stderr.strip(), args
    assert r.stdout == "", f"a failure must not write to stdout: {r.stdout!r}"


def test_failure_keeps_the_human_framing_on_stderr():
    """The diagnostic names the cause and the run, and never leaks to stdout."""
    r = run_installer("--bogus-flag")
    assert "Unknown option: --bogus-flag" in r.stderr
    assert "Error:" in r.stderr
    assert "Run ID:" in r.stderr
    assert "\033[" not in r.stdout
    assert r.stdout == ""


def test_removed_json_flag_is_rejected():
    """The machine-output flag was removed: it must fail, not parse."""
    r = run_installer("--json")
    assert r.returncode == 1
    assert "Unknown option: --json" in r.stderr


def _guard_sandbox(tmp_path):
    """A copy whose INSTALL_DIR already exists, so the guard is reachable.

    The guard is only entered when $INSTALL_DIR is a directory, which a clean
    CI box never has. The copy also poisons do_install: if the guard ever
    stopped firing, this test would fail loudly instead of starting a real
    install on the runner.
    """
    fake_opt = tmp_path / "opt" / "ovmanager"
    fake_opt.mkdir(parents=True)
    src = INSTALLER.read_text(encoding="utf-8")
    src = src.replace(
        'INSTALL_DIR="/opt/ovmanager"',
        f'INSTALL_DIR="{fake_opt}"',
    ).replace(
        'DATA_DIR="/var/lib/ovmanager"',
        f'DATA_DIR="{tmp_path}/data"',
    )
    src = src.replace(
        "do_install() {\n",
        'do_install() {\n    die "TEST SAFETY: the already-installed guard did not fire"\n',
        1,
    )
    path = tmp_path / "install.sh"
    path.write_text(src, encoding="utf-8")
    # install.sh sources scripts/lib at startup; without a copy beside it the
    # installer would leave the sandbox and fetch them over the network.
    # Rewritten like the installer's own copy, so nothing here can reach the
    # real /var/backups, /etc/ssl or /etc/letsencrypt.
    libdir = tmp_path / "scripts" / "lib"
    libdir.mkdir(parents=True)
    for lib in (INSTALLER.parent / "scripts" / "lib").glob("*.sh"):
        text = lib.read_text(encoding="utf-8").replace("/var/lib/ovmanager", f"{tmp_path}/data")
        (libdir / lib.name).write_text(text, encoding="utf-8")
    return path


def test_already_installed_guard_exits_two_with_a_clear_message(tmp_path):
    """A non-interactive run on an installed host names the way forward.

    Exit 2, not 1: this is a state the caller asked about, so a provisioning
    script can tell it apart from a real failure. The reason goes to stderr in
    the renderer's wording, and stdout stays empty.
    """
    r = run_installer("-y", installer=_guard_sandbox(tmp_path))
    assert r.returncode == 2, r.stderr
    assert "already installed" in r.stderr
    assert "update" in r.stderr
    assert r.stdout == ""
