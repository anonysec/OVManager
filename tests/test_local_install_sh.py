"""Behavioral tests for install-local.sh (local dev installer only).

The frozen mains (install.sh/manager.sh) are covered by their own files;
this one never reaches a write unless it is root with a valid source tree.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "install-local.sh"
SETUID = shutil.which("setpriv")
NOBODY = (65534, 65534)


def run(args, *, as_nobody: bool = False, cwd=None):
    cmd = ["bash", str(SCRIPT), *args]
    env = {**os.environ, "HOME": "/tmp"}
    if as_nobody and os.geteuid() == 0:
        if not SETUID:
            pytest.skip("setpriv unavailable for the non-root checks")
        cmd = [SETUID, "--reuid=65534", "--regid=65534", "--clear-groups", *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
    )


def test_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_help_works_as_non_root():
    r = run(["--help"], as_nobody=True)
    assert r.returncode == 0, r.stderr
    assert "--src" in r.stdout and "--dest" in r.stdout
    assert "--uninstall" in r.stdout


def test_unknown_flag_fails_non_zero():
    r = run(["--nope"])
    assert r.returncode != 0
    assert "unknown flag" in r.stderr


def test_missing_frontend_dist_dies_with_build_hint(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("# stub\n", encoding="utf-8")
    r = run(["--src", str(src), "--dest", str(tmp_path / "dest")])
    assert r.returncode != 0
    assert "npm run build" in r.stderr
    assert not (tmp_path / "dest").exists(), "died before any write"


def test_install_path_requires_root_before_any_write(tmp_path):
    """Non-root dies on the root gate; the destination stays untouched."""
    dest = tmp_path / "dest"
    r = run(["--src", str(REPO), "--dest", str(dest)], as_nobody=True)
    if os.geteuid() != 0:
        pytest.skip("root gate only observable from a root suite")
    assert r.returncode != 0
    assert "must run as root" in r.stderr
    assert not dest.exists()


def test_no_curl_pipe_sh_or_github_urls():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "| sh" not in body and "| bash" not in body
    assert "github.com" not in body


def test_claim_key_minted_once_with_strict_perms():
    body = SCRIPT.read_text(encoding="utf-8")
    assert '[[ ! -f "$DEST/data/owner-claim.key" ]]' in body, "reruns must never invalidate the key"
    assert 'chmod 600 "$DEST/data/owner-claim.key"' in body


def test_never_copies_source_env_credentials():
    body = SCRIPT.read_text(encoding="utf-8")
    assert 'cp "$SRC/.env"' not in body, "dev .env hash would claim the panel with an unknown password"
    assert "ADMIN_PASSWORD=" not in body, "generated .env must carry no credential"
