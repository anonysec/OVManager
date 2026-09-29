# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm status` in Python: same rows as manager.sh do_status."""

from __future__ import annotations

import os

from cli.env import Install
from cli.probes import fetch_health, primary_ip, service_state


def collect(install: Install, service: str | None = None, public_ip: str | None = None) -> dict:
    """Gather status without printing (tests assert on this dict).

    `service` overrides the detected state word. Inside the panel container
    there is no docker CLI to ask, so manager.sh passes what it saw on the
    host; the mode still comes from the compose file, which is mounted.
    """
    if not os.path.isdir(install.install_dir):
        return {"ok": False, "installed": False, "error": f"Not installed ({install.install_dir} missing)"}
    mode, detected = service_state(install.compose_file)
    if service is None:
        service = detected
    reachable, version = fetch_health(install.health_url, timeout=5.0, cafile=install.cafile)
    health = "ok" if reachable else "unreachable (check logs)"
    return {
        "ok": reachable,
        "installed": True,
        "mode": mode,
        "service": service,
        "health": health,
        "version": version,
        "url": install.public_url(public_ip or primary_ip()),
        "install_dir": install.install_dir,
        "data_dir": install.data_dir,
        "port": install.port,
    }


def render_text(data: dict, show_all: bool = False) -> str:
    """Human rows matching manager.sh do_status (kv layout)."""
    if not data.get("installed"):
        return f"  Error: {data.get('error')}\n"
    lines = [
        f"  {'Service':<14} {data['service']}",
        f"  {'Health':<14} {data['health']}",
        f"  {'Version':<14} v{data['version']}",
        f"  {'Open':<14} {data['url']}",
    ]
    if show_all:
        lines += [
            f"  {'Mode':<14} {data['mode']}",
            f"  {'Port':<14} {data['port']}",
            f"  {'Data':<14} {data['data_dir']}",
            f"  {'Install':<14} {data['install_dir']}",
        ]
    return "\n".join(lines) + "\n"
