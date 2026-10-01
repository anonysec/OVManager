# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm doctor` read-only checks in Python (no --fix: that stays in bash).

Each check returns a (name, ok, detail, fix_hint) tuple; collect() runs
them all without printing so tests assert on data, not output.
"""

from __future__ import annotations

import datetime
import fcntl
import grp
import json
import os
import pwd
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from cli import render
from cli.env import SYSTEMD_SERVICE, Install
from cli.probes import fetch_health, service_state


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def check_service(install: Install, service: str | None = None) -> Check:
    mode, state = service_state(install.compose_file)
    if service is not None:
        state = service
    ok = state in ("running", "running (docker)", "active")
    return Check(
        "Service",
        ok,
        f"{state} ({mode})",
        "" if ok else "ovm restart",
    )


def check_autostart(install: Install) -> Check:
    import subprocess

    if os.path.isfile(install.compose_file):
        return Check("Auto start", True, "docker (restart policy)", "")
    try:
        out = subprocess.run(
            ["systemctl", "is-enabled", SYSTEMD_SERVICE],
            capture_output=True,
            text=True,
            timeout=10,
        )
        enabled = out.stdout.strip() == "enabled"
    except Exception:
        enabled = False
    return Check("Auto start", enabled, "enabled" if enabled else "disabled", "" if enabled else "ovm enable")


def _default_unit_path() -> str:
    """Where the panel's unit lives. A seam so tests can point it at a fixture.

    The real one is the host's, which says whatever that machine happens to
    run — a test asserting a healthy install cannot depend on that.
    """
    return f"/etc/systemd/system/{SYSTEMD_SERVICE}"


def check_service_account(install: Install, in_container: bool = False) -> Check:
    """Is the panel running as something other than root?

    The panel is a network-facing service that parses untrusted input, so this
    is the check that says whether a compromise of the web app is a compromise
    of the host. Docker has its own appuser inside the image, so there is
    nothing to see from the host.
    """
    if in_container or os.path.isfile(install.compose_file):
        return Check("Service account", True, "container-managed", "")
    try:
        with open(_default_unit_path(), encoding="utf-8") as fh:
            user = next((line.split("=", 1)[1].strip() for line in fh if line.startswith("User=")), "root")
    except OSError:
        return Check("Service account", True, "no unit file (not a systemd install)", "")
    if user == "root":
        return Check(
            "Service account",
            False,
            "the panel runs as root",
            f"ovm doctor --fix   # moves it onto the {PANEL_USER} account",
        )
    return Check("Service account", True, f"panel runs as {user}", "")


def check_env_perms(install: Install, in_container: bool = False) -> Check:
    path = os.path.join(install.install_dir, ".env")
    if in_container:
        # The host .env is passed in as environment variables, not mounted, so
        # there is no file here to stat. Its mode is the host manager's business.
        return Check("Config perms", True, "n/a (host-managed)", "")
    if not os.path.isfile(path):
        return Check("Config perms", False, ".env missing", "reinstall")
    if os.path.isfile(install.compose_file):
        return _check_env_shared_with_container(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    gid = os.stat(path).st_gid
    # 0600 is correct whatever the group: only the owner can read it. Keying
    # this on gid == 0 looked harmless and was not — a file owned by a
    # non-root group was reported as a misconfiguration, which is exactly what
    # happened the moment the suite ran as nobody.
    if mode == 0o600:
        return Check("Config perms", True, f".env is {oct(mode)}", "")
    # The native panel runs as a service account and reads .env through the
    # group, so 0640 root:ovmanager is the correct arrangement, not a lax one:
    # no local account other than that service can read the admin hash, the
    # JWT key or the secret URL path. A group bit is only acceptable when the
    # group is that account.
    service = _unit_user()
    if service is not None and mode == 0o640 and _group_name(gid) == service:
        return Check("Config perms", True, f"{oct(mode)}, shared with {service}", "")
    return Check(
        "Config perms",
        False,
        f".env is {oct(mode)} owned by group {gid} ({_group_name(gid) or 'unknown'})"
        + (f", expected 0640 group {service}" if service else ", expected 0600"),
        f"chgrp {service} .env && chmod 640 .env" if service else "chmod 600 .env",
    )


def check_tls_key_perms(install: Install, in_container: bool = False) -> Check:
    """Can the account that serves TLS actually open its own private key?

    Existence is not enough, and neither is checking the certificate. uvicorn
    opens the key while building its SSL context, so a key this account cannot
    read passes every other check in this file and then kills the panel with a
    bare PermissionError from inside uvicorn — no name, no advice.

    That is not hypothetical: OVNode writes the same /etc/ssl/self-signed pair
    this panel uses, and installing it on the panel's host replaced this key
    and chmod-ed it 600. The panel kept serving from the context it had already
    loaded, so nothing looked wrong until the next restart or reboot, and
    `ovm doctor` reported no problems throughout.
    """
    if in_container:
        # The container's own uid 1000 reads it through a read-only mount; the
        # host file's mode is the host manager's business.
        return Check("TLS key", True, "n/a (container-mounted)", "")
    key = _env_file(install).get("SSL_KEYFILE", "").strip()
    if not key:
        return Check("TLS key", True, "n/a (panel-managed or not set)", "")
    try:
        info = os.stat(key)
    except OSError:
        return Check("TLS key", False, f"{key} is missing", "ovm https --self")
    mode = stat.S_IMODE(info.st_mode)
    service = _unit_user()
    if service is None:
        # Root, or a unit we cannot read: root opens anything, so there is
        # nothing here to get wrong.
        return Check("TLS key", True, f"{oct(mode)} (panel runs as root)", "")
    # Mode alone does not settle it. A 0600 key owned by some *other* account
    # is unreadable by this one — that was the observed breakage — so the bit
    # only counts when it is the bit that grants access to this account.
    if _owner_name(info.st_uid) == service and mode & 0o400:
        return Check("TLS key", True, f"{oct(mode)}, owner {service}", "")
    if _group_name(info.st_gid) == service and mode & 0o040:
        return Check("TLS key", True, f"{oct(mode)}, shared with {service}", "")
    owner = _owner_name(info.st_uid) or info.st_uid
    group = _group_name(info.st_gid) or info.st_gid
    return Check(
        "TLS key",
        False,
        f"{key} is {oct(mode)} {owner}:{group}, so {service} cannot read it",
        f"chgrp {service} {key} && chmod 640 {key}",
    )


def _unit_user() -> str | None:
    """The account the unit runs as, or None if that is root or unreadable.

    Read from the unit rather than hard-coded, so a renamed account is not
    reported as a misconfiguration.
    """
    try:
        with open(_default_unit_path(), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("User="):
                    user = line.split("=", 1)[1].strip()
                    return None if user == "root" else user
    except OSError:
        return None
    return None


def _group_name(gid: int) -> str | None:
    try:
        import grp

        return grp.getgrgid(gid).gr_name
    except (ImportError, KeyError):
        return None


def _owner_name(uid: int) -> str | None:
    """The owning account's name, or None for a uid no account claims."""
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def _check_env_shared_with_container(path: str) -> Check:
    """On docker the .env is bind-mounted, so the container must be able to read it.

    compose cannot pass it as `env_file` — it would expand $NAME inside the
    value and truncate the bcrypt password hash — so the file is mounted and
    must carry the group bit. A root group would mean root can read it and the
    panel cannot, which is the failure this check exists to catch before the
    panel crash-loops on boot.
    """
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        gid = os.stat(path).st_gid
    except OSError as exc:
        return Check("Config perms", False, f".env unreadable: {exc}", "reinstall")
    if mode & 0o040 and gid != 0:
        return Check("Config perms", True, f"shared with the container ({oct(mode)}, gid {gid})", "")
    return Check(
        "Config perms",
        False,
        f"unreadable by the container (mode {oct(mode)}, gid {gid})",
        "sudo ovm update, or chgrp <image ovpanel gid> .env && chmod 640 .env",
    )


def check_data_dir(install: Install) -> Check:
    ok = os.path.isdir(install.data_dir)
    return Check("Data dir", ok, install.data_dir, "" if ok else "reinstall")


def check_disk(path: str = "/var/lib/ovmanager", minimum_mb: int = 200) -> Check:
    try:
        free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    except OSError:
        return Check("Disk", False, f"{path} unreadable", "free disk space")
    ok = free_mb >= minimum_mb
    return Check("Disk", ok, f"{free_mb} MB free", "" if ok else "free disk space")


def check_worker(install: Install) -> Check:
    """Is the scheduled-jobs worker running?

    The worker holds an exclusive flock on <data dir>/scheduler.lock for as
    long as it lives, so the lock is the liveness signal — no pidfile to go
    stale, and it works from the CLI, which is outside the panel process and
    cannot see the worker's Popen.

    This matters more than it looks: if the worker is gone, the daily backup
    and the traffic-limit enforcement silently stop, and the panel looks
    perfectly healthy while both are off.
    """
    lock = Path(install.data_dir) / "scheduler.lock"
    if not lock.exists():
        return Check("Worker", False, "not started (no lock file)", "ovm restart")
    try:
        handle = lock.open("a+")
    except OSError as exc:
        return Check("Worker", False, f"cannot read the lock: {exc}", "ovm logs")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        try:
            pid = lock.read_text().strip()
        except OSError:
            pid = ""
        return Check("Worker", True, f"running{f' (pid {pid})' if pid else ''}", "")
    # We got the lock, so nobody holds it: the worker is gone and left the file.
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()
    return Check(
        "Worker",
        False,
        "not running (stale lock file — the periodic jobs are not running)",
        "ovm restart",
    )


def check_health(install: Install) -> Check:
    reachable, version = fetch_health(install.health_url, timeout=5.0, cafile=install.cafile)
    return Check(
        "Panel health",
        reachable,
        f"ok (v{version})" if reachable else "unreachable",
        "" if reachable else "ovm logs",
    )


def check_certificate(install: Install) -> Check:
    """TLS expiry, from the installed certificate. Skipped on plain HTTP."""
    if install.tls_mode == "none":
        return Check("Certificate", True, "not in use (plain HTTP)", "")
    cert = install.cafile
    if not cert or not os.path.isfile(cert):
        return Check("Certificate", False, "not found", "ovm https")
    days_left = _cert_days_left(cert)
    if days_left is None:
        return Check("Certificate", False, "could not read expiry", "ovm https")
    if days_left > 30:
        return Check("Certificate", True, f"expires in {days_left}d", "")
    if days_left > 0:
        return Check("Certificate", False, f"expires in {days_left}d", "ovm https")
    return Check("Certificate", False, "expired", "ovm https")


def _cert_days_left(cert: str) -> int | None:
    """Days until notAfter, or None when openssl cannot say."""
    import re
    import subprocess

    try:
        out = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", cert],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    m = re.match(r"notAfter=(.*)", out.stdout.strip())
    if not m:
        return None
    # openssl prints e.g. "Sep 22 01:30:24 2036 GMT"; email.utils handles it.
    from email.utils import parsedate_to_datetime

    try:
        expiry = parsedate_to_datetime(m.group(1))
    except (TypeError, ValueError):
        return None
    return int((expiry - datetime.datetime.now(datetime.UTC)).total_seconds() // 86400)


def check_update_journal(install: Install) -> Check:
    """An interrupted update leaves a journal or the write-block marker."""
    if os.path.isfile(os.path.join(install.data_dir, "update-maintenance")):
        return Check("Update", False, "recovery required", "ovm update")
    state = os.path.join(install.data_dir, "update-state.json")
    if os.path.isfile(state):
        try:
            with open(state, encoding="utf-8") as fh:
                phase = json.load(fh).get("phase")
        except (OSError, ValueError):
            phase = None
        if phase not in ("committed", "failed_over"):
            return Check("Update", False, "recovery required", "ovm update")
    return Check("Update", True, "no interrupted transaction", "")


def check_backup_age(install: Install, maximum_days: int = 7, legacy_dir: str = "/var/backups") -> Check:
    """Age of the newest backup, in either the .ovmbak or legacy tarball form."""
    candidates: list[str] = []
    backups = os.path.join(install.data_dir, "backups")
    if os.path.isdir(backups):
        candidates += [os.path.join(backups, f) for f in os.listdir(backups) if f.endswith(".ovmbak")]
    if os.path.isdir(legacy_dir):
        candidates += [
            os.path.join(legacy_dir, f) for f in os.listdir(legacy_dir) if f.startswith("panel-") and f.endswith(".tar.gz")
        ]
    if not candidates:
        return Check("Backup", False, "none yet", "ovm backup")
    newest = max(candidates, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    age_days = int((time.time() - os.path.getmtime(newest)) // 86400)
    ok = age_days <= maximum_days
    return Check("Backup", ok, f"{age_days}d old", "" if ok else "ovm backup")


def check_private_permissions(install: Install) -> Check:
    """Data files must not be group/world readable.

    Native only: in Docker the data directory belongs to uid 1000 inside the
    container, so host modes are not the ones that apply.
    """
    if os.path.isfile(install.compose_file):
        return Check("Permissions", True, "container-managed", "")
    loose = []
    if not _is_mode(install.data_dir, 0o700):
        loose.append("data dir")
    backups = os.path.join(install.data_dir, "backups")
    if os.path.isdir(backups) and not _is_mode(backups, 0o700):
        loose.append("backups dir")
    for name in ("ovmanager.db", "update-state.json", "update-maintenance"):
        path = os.path.join(install.data_dir, name)
        if os.path.isfile(path) and not _is_mode(path, 0o600):
            loose.append(name)
    if not loose:
        return Check("Permissions", True, "private", "")
    return Check("Permissions", False, f"loose ({', '.join(loose)})", "ovm doctor --fix")


def _is_mode(path: str, mode: int) -> bool:
    try:
        return stat.S_IMODE(os.stat(path).st_mode) == mode
    except OSError:
        return False


def collect(
    install: Install,
    service: str | None = None,
    in_container: bool = False,
    legacy_backup_dir: str = "/var/backups",
) -> list[Check]:
    return [
        check_service(install, service),
        check_autostart(install),
        check_certificate(install),
        check_update_journal(install),
        check_backup_age(install, legacy_dir=legacy_backup_dir),
        check_private_permissions(install),
        check_disk(install.data_dir),
        check_env_perms(install, in_container),
        check_tls_key_perms(install, in_container),
        check_data_dir(install),
        check_health(install),
        check_worker(install),
        check_service_account(install, in_container),
    ]


def _run(argv: list[str], timeout: float = 30.0) -> bool:
    """Run a fix command; True on exit 0. Never raises."""
    import subprocess

    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout).returncode == 0
    except Exception:
        return False


def fix(check: Check, install: Install, service: str | None = None) -> Check:
    """Attempt one auto-fix, returning the re-checked result.

    Only Service (restart), Auto start (enable), Config perms (chmod) and
    TLS key (group read) are auto-fixable. Disk and health failures need the
    operator.
    """
    import os
    import stat as _stat

    if check.ok:
        return check
    compose = os.path.isfile(install.compose_file)
    if check.name == "Service":
        if compose:
            ok = _run(["docker", "restart", "-t", "10", "ovmanager"])
        else:
            ok = _run(["systemctl", "restart", SYSTEMD_SERVICE])
        return check_service(install, service) if ok else check
    if check.name == "Auto start":
        if compose:
            ok = _run(["docker", "update", "--restart", "unless-stopped", "ovmanager"])
        else:
            ok = _run(["systemctl", "enable", SYSTEMD_SERVICE])
        return check_autostart(install) if ok else check
    if check.name == "Permissions":
        for path, mode in ((install.data_dir, 0o700), (os.path.join(install.data_dir, "backups"), 0o700)):
            if os.path.isdir(path):
                try:
                    os.chmod(path, mode)
                except OSError:
                    pass
        for name in ("ovmanager.db", "update-state.json", "update-maintenance"):
            path = os.path.join(install.data_dir, name)
            if os.path.isfile(path):
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        return check_private_permissions(install)
    if check.name == "Config perms":
        path = os.path.join(install.install_dir, ".env")
        if not os.path.isfile(path):
            return check
        try:
            os.chmod(path, 0o600)
            mode = _stat.S_IMODE(os.stat(path).st_mode)
            if mode == 0o600:
                return Check(check.name, True, ".env is 0o600 (fixed)", "")
        except OSError:
            pass
        return check
    if check.name == "TLS key":
        key = _env_file(install).get("SSL_KEYFILE", "").strip()
        account = _unit_user()
        if not key or account is None or not os.path.isfile(key):
            return check
        try:
            # Group only: the owner is not ours to claim, and a group read is
            # exactly what the service account needs. This is the same repair
            # the installer's grant_panel_access performs.
            os.chown(key, -1, grp.getgrnam(account).gr_gid)
            os.chmod(key, 0o640)
        except (OSError, KeyError):
            return check
        return check_tls_key_perms(install)
    if check.name == "Service account":
        return fix_service_account(install, check)
    return check


PANEL_USER = os.environ.get("OVM_PANEL_USER", "ovmanager")


def fix_service_account(install: Install, check: Check) -> Check:
    """Move the panel off root: create the account, grant it, switch the unit.

    This lives in `ovm doctor --fix` rather than only in the installer's update
    path, because of a bootstrap problem that is easy to miss. `do_update`
    swaps the install tree -- the directory holding the `install.sh` that is
    currently running -- partway through, so the script performing the update
    is always the *previous* one. A migration introduced by the release being
    installed is therefore not in the code that runs, and the first update to
    that release cannot perform it. On a box that jumped 1.0.24 -> 1.0.26 the
    migration was present in the installer on disk and never executed; it would
    have taken a second update, and an operator wondering why, to apply.

    `ovm doctor --fix` is dispatched out of the freshly updated tree, so this
    code is the new code, and the check that reports the problem already exists
    to prompt for it. One explicit operator action is enough.

    The unit is edited, not regenerated. A box's paths can differ from the
    template, and overwriting them would be a worse outcome than the one being
    fixed; only the User= line changes and Group= is inserted beside it. Putting
    Group= at the end of the file would land it in [Install], which systemd
    rejects.

    The unit is snapshotted first and put back if the panel does not come back,
    for the same reason the installer does: it lives outside the tree, so no
    update rollback can reach it.
    """
    user = PANEL_USER
    unit = _default_unit_path()
    if not os.path.isfile(unit):
        return check
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(user).gr_gid
    except KeyError:
        if not _run(
            [
                "useradd",
                "--system",
                "--no-create-home",
                "--home-dir",
                install.data_dir,
                "--shell",
                "/usr/sbin/nologin",
                "--comment",
                "OVManager panel service account",
                user,
            ]
        ):
            return Check(check.name, False, f"could not create the {user} account", f"useradd {user}")
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(user).gr_gid

    with open(unit, encoding="utf-8") as fh:
        body = fh.read()
    if not re.search(r"^User=.*$", body, re.M):
        return Check(check.name, False, f"{unit} sets no User=, so there is nothing to change", f"add User={user}")
    if re.search(r"^Group=", body, re.M):
        return Check(
            check.name,
            False,
            f"{unit} already sets Group=; change it by hand if it is not {user}",
            f"set User={user} and Group={user}",
        )
    new_body = re.sub(r"^User=.*$", f"User={user}\nGroup={user}", body, count=1, flags=re.M)

    # `uv run` re-resolves and rebuilds the project before starting it, which
    # writes into the tree (egg-info, the lock) — so as an unprivileged account
    # it cannot work, and it fails with "Cannot update time stamp of directory
    # 'ovmanager.egg-info'". The venv's own interpreter needs no write access
    # and is what uv ends up executing anyway.
    #
    # This is why the unit cannot simply keep its ExecStart: the panel has never
    # actually run unprivileged before. An earlier feasibility check booted
    # .venv/bin/python3 directly, so it passed without ever exercising the
    # start command the unit actually used.
    venv_python = os.path.join(install.install_dir, ".venv", "bin", "python3")
    current = re.search(r"^ExecStart=(\S+)", new_body, re.M)
    program = current.group(1) if current else ""
    # Already an interpreter from the venv: nothing to do, and no need to guess
    # where uv lives on this box, which is not a fixed path.
    if not re.search(r"/\.venv/bin/python[0-9.]*$", program):
        new_body = re.sub(
            r"^ExecStart=.*$",
            f"ExecStart={venv_python} main.py",
            new_body,
            count=1,
            flags=re.M,
        )

    snapshot = f"{unit}.ovm-backup"
    shutil.copy2(unit, snapshot)
    try:
        with open(unit, "w", encoding="utf-8") as fh:
            fh.write(new_body)
        os.chmod(unit, 0o644)
        # Group-read for the service, owner-only for everything else. 0600 on
        # .env was never the point -- no other local account can read it was.
        _chown(os.path.join(install.install_dir, ".env"), 0, gid, 0o640)
        _chown(install.install_dir, 0, gid, 0o750)
        for path in _tls_paths(install):
            _chown(path, 0, gid, 0o640)
        if os.path.isdir(install.data_dir):
            for root, dirs, files in os.walk(install.data_dir):
                for name in [*dirs, *files]:
                    _chown(os.path.join(root, name), uid, gid, None)
            _chown(install.data_dir, uid, gid, 0o700)
        _run(["systemctl", "daemon-reload"])
        if not _run(["systemctl", "restart", SYSTEMD_SERVICE]):
            raise RuntimeError("systemctl restart failed")
        # 60s, not 30. The first start as the service account is the slowest
        # one there will ever be: the tree is root-owned, so the interpreter
        # cannot write its bytecode cache and recompiles everything on every
        # start, on a cold page cache. Measured at 6s warm, but the first
        # `doctor --fix` on a freshly updated box timed out at 30s, rolled the
        # migration back, and the immediate retry then succeeded — which is a
        # bad way to learn that a window is too tight. This matches the
        # installer's own wait_health timeout in do_update.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if fetch_health(install.health_url, timeout=3.0, cafile=install.cafile)[0]:
                break
            time.sleep(1)
        else:
            raise RuntimeError("the panel did not answer /health within 60s")
        return check_service_account(install)
    except (OSError, RuntimeError) as exc:
        try:
            shutil.copy2(snapshot, unit)
            _run(["systemctl", "daemon-reload"])
            _run(["systemctl", "restart", SYSTEMD_SERVICE])
        except OSError:
            pass
        return Check(check.name, False, f"migration failed ({exc}); the unit was restored", f"inspect {snapshot}")


def _chown(path: str, uid: int, gid: int, mode: int | None) -> None:
    """chown, then chmod, ignoring a path that is not there or not permitted."""
    if not os.path.exists(path):
        return
    try:
        os.chown(path, uid, gid)
        if mode is not None:
            os.chmod(path, mode)
    except OSError:
        pass


def _env_file(install: Install) -> dict[str, str]:
    """The installed .env as a dict; empty when it cannot be read."""
    try:
        with open(os.path.join(install.install_dir, ".env"), encoding="utf-8") as fh:
            return dict(line.split("=", 1) for line in fh if "=" in line and not line.startswith("#"))
    except OSError:
        return {}


def _tls_paths(install: Install) -> list[str]:
    """The TLS key and certificate named in .env, if they are readable paths."""
    env = _env_file(install)
    found = []
    for name in ("SSL_KEYFILE", "SSL_CERTFILE"):
        value = env.get(name, "").strip()
        if value and os.path.isfile(value):
            found.append(value)
    return found


def fix_all(install: Install, service: str | None = None, in_container: bool = False) -> list[Check]:
    """Run every check, auto-fixing what is fixable. Never raises.

    The Service account fix runs first, and the rest are re-collected
    afterwards, because it rewrites the unit that the Config perms check reads.
    In the other order the two fought: Config perms saw the 0640 .env that the
    migration had just granted to the service group, did not yet recognise it,
    and chmod'd it back to 0600 — leaving the panel unable to read its own
    configuration as the account it had just been moved to.
    """
    checks = collect(install, service, in_container)
    for check in checks:
        if check.name == "Service account":
            fix(check, install, service)
            break
    return [fix(c, install, service) for c in collect(install, service, in_container)]


def render_text(checks: list[Check], show_all: bool = False) -> str:
    """Failures first, and only the failures unless asked otherwise.

    Thirteen passing checks spent fifteen lines to say the word "ok", which is
    why this screen was the one nobody read: everything looked equally urgent,
    so nothing did. The problems go to the top with their fixes, and the count
    of what passed goes underneath as one line — present, so a clean run still
    proves it ran, and short enough to skip.

    `show_all` keeps the full list, for pasting into a ticket.
    """
    failed_checks = [c for c in checks if not c.ok]
    passed = len(checks) - len(failed_checks)
    if not failed_checks:
        return render.block(
            [render.ok(f"no problems — {passed} checks passed"), render.hint("detail: ovm doctor --all")]
        )

    lines = [render.failed(f"{len(failed_checks)} problems")]
    lines.append("")
    for c in failed_checks:
        lines.append(render.kv(c.name, c.detail, render.rows_width([(c.name, c.detail)])))
        if c.fix:
            lines.append(render.kv("fix", c.fix, render.rows_width([("fix", "")])))
    if show_all or not passed:
        lines.append("")
        lines.append(render.heading("all checks"))
        width = render.rows_width([(c.name, "") for c in checks])
        for c in checks:
            mark = "ok" if c.ok else "FAIL"
            lines.append(f"  {c.name:<{width}}  {mark}  {c.detail}")
    else:
        lines.append("")
        lines.append(render.hint(f"{passed} other checks passed — detail: ovm doctor --all"))
    return render.block(lines)
