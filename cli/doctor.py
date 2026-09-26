# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm doctor` read-only checks in Python (no --fix: that stays in bash).

Each check returns a (name, ok, detail, fix_hint) tuple; collect() runs
them all without printing so tests assert on data, not output.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass

from cli.env import SYSTEMD_SERVICE, Install
from cli.probes import fetch_health, service_state


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def check_service(install: Install) -> Check:
    mode, state = service_state(install.compose_file)
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


def check_env_perms(install: Install) -> Check:
    path = os.path.join(install.install_dir, ".env")
    if not os.path.isfile(path):
        return Check("Config perms", False, ".env missing", "reinstall")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    ok = mode == 0o600
    return Check(
        "Config perms",
        ok,
        f".env is {oct(mode)}",
        "" if ok else "chmod 600 .env",
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


def check_health(install: Install) -> Check:
    reachable, version = fetch_health(install.health_url, timeout=5.0)
    return Check(
        "Panel health",
        reachable,
        f"ok (v{version})" if reachable else "unreachable",
        "" if reachable else "ovm logs",
    )


def collect(install: Install) -> list[Check]:
    return [
        check_service(install),
        check_autostart(install),
        check_env_perms(install),
        check_data_dir(install),
        check_disk(install.data_dir),
        check_health(install),
    ]


def render_text(checks: list[Check]) -> str:
    lines = ["  Panel health"]
    problems = 0
    for c in checks:
        mark = "ok" if c.ok else "FAIL"
        lines.append(f"  {c.name:<14} {mark}  {c.detail}")
        if not c.ok:
            problems += 1
            if c.fix:
                lines.append(f"  {'Fix':<14} {c.fix}")
    lines.append(f"  {'Problems':<14} {problems}")
    return "\n".join(lines) + "\n"
