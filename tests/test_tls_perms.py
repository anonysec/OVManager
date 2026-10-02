"""The TLS key must be readable by whoever actually serves TLS.

`secure_tls_files` used to chown the private key to uid 1000 and chmod it 600
unconditionally — an arrangement written for the Docker image, whose appuser is
uid 1000 and reads the key through a read-only mount. On a native install the
panel is a *service account* that reads through the group, and nothing on that
path runs as root on its behalf, so the key ended up unreadable by the one
process that needed it. `ovm https --self` (and Let's Encrypt renewals, through
the acme reloadcmd) then restarted the panel into a bare PermissionError from
inside uvicorn.

Both deployments have to be served correctly, and the reloadcmd has to branch
the same way because it runs later, alone, with these variables long gone.
"""

import grp
import os
import subprocess
from pathlib import Path

import inline_lib
import pytest

LIB = inline_lib.path("tls.sh")


def _current_group() -> str:
    """Resolves on any host, including CI; chgrp only needs a real group."""
    return grp.getgrgid(os.getgid()).gr_name


def _base_env(**over: str) -> dict[str, str]:
    return {**os.environ, "PANEL_USER": os.environ.get("PANEL_USER") or _current_group(), **over}


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _secure(directory: Path, env: dict[str, str]) -> tuple[Path, Path, subprocess.CompletedProcess]:
    key = directory / "privkey.pem"
    cert = directory / "fullchain.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
    cert.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    script = 'set -euo pipefail\n. "' + str(LIB) + '"\n' + f'secure_tls_files "{key}" "{cert}"\n'
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, env=env)
    return key, cert, done


def test_a_native_install_shares_the_key_with_the_service_group(tmp_path):
    key, cert, done = _secure(tmp_path, _base_env(MODE="native"))
    assert done.returncode == 0, done.stderr
    assert _mode(key) == 0o640, f"key is {oct(_mode(key))} — the service group cannot read it"
    assert key.stat().st_gid == os.getgid(), "a native key must be readable by the service group"
    assert _mode(cert) == 0o644


def test_a_docker_install_does_not_grant_a_group_read(tmp_path):
    """Ownership is what lets the container in — not the group.

    The mode is the portable half of that: 0600 means only the owner can open
    it, which is the point of chowning to the appuser. (The chown itself needs
    privilege, so it is asserted separately below.)
    """
    key, cert, done = _secure(tmp_path, _base_env(MODE="docker"))
    assert done.returncode == 0, done.stderr
    assert _mode(key) == 0o600, f"key is {oct(_mode(key))} — uid 1000 cannot read it"
    assert _mode(cert) == 0o644


@pytest.mark.skipif(
    os.geteuid() != 0,
    reason="chown to another uid needs privilege; the runner is not root, so the "
    "code's `|| true` skips it and the owner stays the test user",
)
def test_a_docker_install_hands_the_key_to_the_container_uid(tmp_path):
    key, _, done = _secure(tmp_path, _base_env(MODE="docker"))
    assert done.returncode == 0, done.stderr
    assert key.stat().st_uid == 1000


def test_the_compose_file_decides_when_the_manager_is_the_caller(tmp_path):
    """`ovm https` has no MODE: the installer sets it, the manager does not."""
    compose = tmp_path / "ovmanager-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    key, _, done = _secure(tmp_path, _base_env(COMPOSE_FILE=str(compose)))
    assert done.returncode == 0, done.stderr
    assert _mode(key) == 0o600, "a compose file means a container reads this key"

    native = tmp_path / "no-compose"
    native.mkdir()
    key, _, done = _secure(native, _base_env(COMPOSE_FILE=str(tmp_path / "absent-compose.yml")))
    assert done.returncode == 0, done.stderr
    assert _mode(key) == 0o640, "no compose file means the native service account reads it"


def test_a_missing_file_is_not_an_error(tmp_path):
    script = 'set -euo pipefail\n. "' + str(LIB) + f'"\nsecure_tls_files "{tmp_path / "nope.pem"}" "{tmp_path / "nope.crt"}"\n'
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, env=_base_env())
    assert done.returncode == 0, done.stderr


def test_the_renewal_hook_branches_the_same_way():
    """acme runs this string alone, so it cannot call secure_tls_files."""
    hook = next(line for line in LIB.read_text(encoding="utf-8").splitlines() if "--reloadcmd" in line)
    assert "chown 1000:1000" in hook and "chmod 600" in hook, "the container case must survive"
    assert "chgrp" in hook and "chmod 640" in hook, (
        "renewals must grant the service group, or a native panel breaks every renewal"
    )
    assert "COMPOSE_FILE" in hook, "the hook has to decide the mode by itself"
