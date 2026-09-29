"""The panel must notice when it cannot read its own TLS private key.

A key the service account cannot open passes every other check in the doctor
and then kills the panel inside uvicorn's SSL context build with a bare
PermissionError — no filename, no advice. That is not hypothetical: OVNode
writes the same /etc/ssl/self-signed pair, and installing it on the panel's
host replaced this key and chmod-ed it 600. The panel kept serving from the
context it had already loaded, so nothing looked wrong until the next restart
or reboot, and `ovm doctor` reported "Problems 0" the whole time.

Mode alone does not settle it: a 0600 key owned by some *other* account is
exactly as unreadable as a 0640 one owned by a foreign group, and the first
of those is the case that actually happened.
"""

import os
import stat
from types import SimpleNamespace

import pytest

from cli import doctor
from cli.env import Install


def _install(tmp_path, *, key_mode: int | None = 0o600, key_name: str = "privkey.pem"):
    """A fake install whose .env names a real key file, or names nothing."""
    install_dir = tmp_path / "opt"
    install_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ovmanager.db").write_bytes(b"")

    key = tmp_path / key_name
    env = "PORT=2095\n"
    if key_mode is not None:
        key.write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
        key.chmod(key_mode)
        env += f"SSL_KEYFILE={key}\n"
    (install_dir / ".env").write_text(env, encoding="utf-8")
    (install_dir / ".env").chmod(0o600)
    return Install.detect(install_dir=str(install_dir), data_dir=str(data_dir)), key


def _as_service_account(monkeypatch, *, owner: str, group: str) -> None:
    monkeypatch.setattr(doctor, "_unit_user", lambda: "ovmanager")
    monkeypatch.setattr(doctor, "_owner_name", lambda uid: owner)
    monkeypatch.setattr(doctor, "_group_name", lambda gid: group)


def test_a_key_owned_by_the_service_account_is_fine(tmp_path, monkeypatch):
    install, _ = _install(tmp_path, key_mode=0o600)
    _as_service_account(monkeypatch, owner="ovmanager", group="ovmanager")
    check = doctor.check_tls_key_perms(install)
    assert check.ok, check.detail


def test_a_group_read_by_the_service_account_is_fine(tmp_path, monkeypatch):
    """0640 root:ovmanager is the arrangement the installer creates."""
    install, _ = _install(tmp_path, key_mode=0o640)
    _as_service_account(monkeypatch, owner="root", group="ovmanager")
    check = doctor.check_tls_key_perms(install)
    assert check.ok, check.detail


def test_a_key_owned_by_another_account_fails_even_at_0600(tmp_path, monkeypatch):
    """The regression that started this: 0600, owner uid 1000, service uid 999.

    Checking the mode alone would pass this, which is exactly why the check
    asks who the mode actually grants access to.
    """
    install, _ = _install(tmp_path, key_mode=0o600)
    _as_service_account(monkeypatch, owner="somebody-else", group="ovmanager")
    check = doctor.check_tls_key_perms(install)
    assert not check.ok
    assert "cannot read it" in check.detail
    assert "chgrp ovmanager" in check.fix


def test_a_foreign_group_read_fails(tmp_path, monkeypatch):
    install, _ = _install(tmp_path, key_mode=0o640)
    _as_service_account(monkeypatch, owner="somebody-else", group="someday-group")
    check = doctor.check_tls_key_perms(install)
    assert not check.ok


def test_an_unset_key_is_not_a_problem(tmp_path):
    """Panel-managed TLS lives in DATA_DIR/tls and names no SSL_KEYFILE."""
    install, _ = _install(tmp_path, key_mode=None)
    check = doctor.check_tls_key_perms(install)
    assert check.ok, check.detail


def test_a_missing_key_names_the_way_out(tmp_path):
    install, key = _install(tmp_path, key_mode=0o600)
    key.unlink()
    check = doctor.check_tls_key_perms(install)
    assert not check.ok
    assert check.fix == "ovm https --self"


def test_fix_grants_the_group_read_and_rechecks(tmp_path, monkeypatch):
    """--fix must repair it, not merely report it."""
    install, key = _install(tmp_path, key_mode=0o600)
    _as_service_account(monkeypatch, owner="somebody-else", group="ovmanager")
    monkeypatch.setattr(doctor.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    monkeypatch.setattr(doctor.os, "chown", lambda path, uid, gid: None)

    before = doctor.check_tls_key_perms(install)
    assert not before.ok

    after = doctor.fix(before, install)
    assert after.ok, after.detail
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o640


def test_startup_reports_a_missing_key_with_advice(tmp_path):
    from main import _require_readable

    with pytest.raises(SystemExit) as excinfo:
        _require_readable(str(tmp_path / "absent.pem"), "key")
    message = str(excinfo.value)
    assert "absent.pem" in message
    assert "chgrp" in message and "ovm doctor" in message


def test_startup_reports_a_path_it_cannot_open(tmp_path):
    """The exists-but-unopenable branch, reachable even as root.

    A directory stands in for an unreadable key: root opens a 0000 file
    regardless, so the denial itself cannot be reproduced here, but `open`
    on a directory fails for everyone and lands in the same handler.
    """
    from main import _require_readable

    with pytest.raises(SystemExit) as excinfo:
        _require_readable(str(tmp_path), "key")
    assert "not readable" in str(excinfo.value)
    assert "chgrp" in str(excinfo.value)


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root opens a 0000 file regardless, so the denial cannot be reproduced",
)
def test_startup_reports_a_key_it_cannot_read(tmp_path):
    from main import _require_readable

    key = tmp_path / "privkey.pem"
    key.write_text("x", encoding="utf-8")
    key.chmod(0o000)
    with pytest.raises(SystemExit) as excinfo:
        _require_readable(str(key), "key")
    assert "not readable" in str(excinfo.value)
