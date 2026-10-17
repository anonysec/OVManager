"""Behavioral tests for install.sh, the Go binary bootstrap.

The default path fetches the checksummed release tarball (the Go binary plus
the prebuilt frontend/dist) and verifies /health reports the release version;
--from-source is the dev path (rsync + go build + a dev unit).

Nothing here reaches a write. The checks are validation paths and text scans of
the installer, so the suite is safe on a box that already runs a panel.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
SETUID = shutil.which("setpriv")


def _installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def _from_source() -> str:
    body = _installer()
    start = body.index("do_from_source() {")
    end = body.index("\ndo_install() {", start)
    return body[start:end]


def _function(name: str) -> str:
    body = _installer()
    start = body.index(f"{name}() {{")
    end = body.index("\n}\n", start)
    return body[start:end]


def run(args, *, as_nobody=False, cwd=None):
    cmd = ["bash", str(INSTALLER), *args]
    env = {**os.environ, "HOME": "/tmp"}
    if as_nobody and os.geteuid() == 0:
        if not SETUID:
            pytest.skip("setpriv unavailable for the non-root checks")
        cmd = [SETUID, "--reuid=65534", "--regid=65534", "--clear-groups", *cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                          env=env, cwd=cwd, stdin=subprocess.DEVNULL)


def test_syntax():
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_help_lists_the_dev_flags():
    r = run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "--from-source" in r.stdout and "--dest" in r.stdout


def test_version_script_reports_the_installer():
    r = run(["version-script"])
    assert r.returncode == 0, r.stderr
    assert "installer  v" in r.stdout


def test_unknown_flag_dies():
    r = run(["--definitely-not-a-flag"])
    assert r.returncode != 0
    assert "Unknown option" in r.stderr


def test_missing_go_tree_dies(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    r = run(["--from-source", str(src), "--dest", str(dest)])
    assert r.returncode != 0
    assert "cmd/ovmanager/main.go" in r.stderr
    assert not dest.exists(), "died before any write"


def test_missing_frontend_dist_dies_with_build_hint(tmp_path):
    src = tmp_path / "src"
    (src / "cmd" / "ovmanager").mkdir(parents=True)
    (src / "cmd" / "ovmanager" / "main.go").write_text("package main\n", encoding="utf-8")
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
    assert 'local src="${SRC:-$PWD}"' in _installer()


def test_path_is_isolated_from_release_and_update():
    """The dev path never touches the release or update machinery."""
    fs = _from_source()
    for gone in ("fetch_release", "docker", "acme", "COMPOSE_FILE", "UPDATE_STAGE"):
        assert gone not in fs, f"--from-source must not reach {gone}"


def test_dev_unit_runs_the_go_binary_from_dest():
    """A test --dest writes its own unit and cannot clobber the live panel."""
    fs = _from_source()
    assert 'service="$(basename "$dest").service"' in fs
    assert "ExecStart=$dest/$APP_SLUG" in fs
    assert ".venv/bin" not in fs, "the dev path must not run a Python venv"
    assert "uv sync" not in fs
    assert "install.sh --from-source dev install" in fs
    assert "install-local.sh dev install" not in fs


def test_claim_key_is_minted_once_with_strict_perms():
    fs = _from_source()
    assert '[[ ! -f "$dest/data/owner-claim.key" ]]' in fs, "reruns must never invalidate the key"
    assert 'chmod 600 "$dest/data/owner-claim.key"' in fs, "the key must be private"


def test_never_copies_source_env_credentials():
    fs = _from_source()
    assert 'cp "$src/.env"' not in fs, "dev .env would claim the panel with an unknown password"
    assert "ADMIN_PASSWORD=" not in fs, "generated .env must carry no credential"


def test_no_python_runtime_anywhere():
    body = _installer()
    for gone in ("uv sync", ".venv/bin", "python3", "main.py", "manager.sh", "pip install"):
        assert gone not in body, f"installer still references {gone}"


def test_release_path_fetches_a_checksummed_tarball():
    body = _installer()
    assert "releases/download/v" in body
    assert "sha256sum -c" in body, "the release must be checksum-verified before extraction"
    assert "--strip-components=1" in body, "the archive's version prefix must be stripped"


def test_release_unit_runs_the_binary_and_not_a_dev_layout():
    unit = _function("write_systemd_unit")
    assert "ExecStart=$INSTALL_DIR/$APP_SLUG" in unit
    assert ".venv" not in unit
    assert "install-local.sh dev install" not in unit


def test_health_verify_requires_a_version_match():
    """The v1.6.0 gap: an answer from a stale process must fail the install."""
    body = _installer()
    assert '[[ "$got" == "$want" ]]' in body
    assert 'verify_health "$port" "$VERSION"' in body


def test_env_is_created_once():
    """A rerun must never rotate the operator's .env."""
    body = _installer()
    assert 'if [[ -f "$envfile" ]]; then' in body


def test_update_hands_off_to_the_binary():
    """`bash install.sh update` is what panel/updater.go execs."""
    body = _installer()
    assert 'exec "$INSTALL_DIR/$APP_SLUG" update "$@"' in body
