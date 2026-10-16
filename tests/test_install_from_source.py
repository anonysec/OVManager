"""Behavioral tests for install.sh --from-source (the dev tree install).

The dev path folds in the old install-local.sh. These tests never reach a
write: they exercise validation and scan the generated text, so they are safe
on a box that already runs a panel.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
SETUID = shutil.which("setpriv")


def _from_source() -> str:
    body = INSTALLER.read_text(encoding="utf-8")
    start = body.index("do_from_source() {")
    end = body.index("\ndo_install() {", start)
    return body[start:end]


def run(args, *, as_nobody=False, cwd=None):
    cmd = ["bash", str(INSTALLER), *args]
    env = {**os.environ, "HOME": "/tmp"}
    if as_nobody and os.geteuid() == 0:
        if not SETUID:
            pytest.skip("setpriv unavailable for the non-root checks")
        cmd = [SETUID, "--reuid=65534", "--regid=65534", "--clear-groups", *cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env, cwd=cwd, stdin=subprocess.DEVNULL)


def test_syntax():
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_help_lists_the_dev_flags():
    r = run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "--from-source" in r.stdout and "--dest" in r.stdout


def test_missing_frontend_dist_dies_with_build_hint(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("# stub\n", encoding="utf-8")
    dest = tmp_path / "dest"
    r = run(["--from-source", str(src), "--dest", str(dest)])
    assert r.returncode != 0
    assert "npm run build" in r.stderr
    assert not dest.exists(), "died before any write"


def test_source_requires_root_before_any_write(tmp_path):
    """A valid tree dies on the root gate; the destination stays untouched."""
    dest = tmp_path / "dest"
    r = run(["--from-source", str(REPO), "--dest", str(dest)], as_nobody=True)
    if os.geteuid() != 0:
        pytest.skip("root gate only observable from a root suite")
    assert r.returncode != 0
    assert "Must run as root" in r.stderr
    assert not dest.exists()


def test_default_source_is_the_current_tree():
    assert 'local src="${SRC:-$PWD}"' in INSTALLER.read_text(encoding="utf-8")


def test_path_is_isolated_from_release_docker_and_acme():
    """The dev path never touches the release, Docker or ACME machinery."""
    fs = _from_source()
    for gone in ("fetch_release", "docker", "acme", "COMPOSE_FILE", "UPDATE_STAGE"):
        assert gone not in fs, f"--from-source must not reach {gone}"


def test_unit_name_is_derived_from_dest():
    """A test --dest writes its own unit and cannot clobber the live panel."""
    fs = _from_source()
    assert 'service="$(basename "$dest").service"' in fs
    assert "install.sh --from-source dev install" in fs


def test_claim_key_is_minted_once_with_strict_perms():
    fs = _from_source()
    assert '[[ ! -f "$dest/data/owner-claim.key" ]]' in fs, "reruns must never invalidate the key"
    assert 'chmod 600 "$dest/data/owner-claim.key"' in fs, "the key must be private"


def test_never_copies_source_env_credentials():
    fs = _from_source()
    assert 'cp "$src/.env"' not in fs, "dev .env would claim the panel with an unknown password"
    assert "ADMIN_PASSWORD=" not in fs, "generated .env must carry no credential"
