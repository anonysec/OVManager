# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm status` in Python: same rows and JSON shape as manager.sh do_status."""

from __future__ import annotations

import json
import os

from cli.env import Install
from cli.probes import fetch_health, primary_ip, service_state


def collect(install: Install) -> dict:
    """Gather status without printing (tests assert on this dict)."""
    if not os.path.isdir(install.install_dir):
        return {"ok": False, "installed": False, "error": f"Not installed ({install.install_dir} missing)"}
    mode, service = service_state(install.compose_file)
    reachable, version = fetch_health(install.health_url, timeout=5.0)
    health = "ok" if reachable else "unreachable (check logs)"
    return {
        "ok": reachable,
        "installed": True,
        "mode": mode,
        "service": service,
        "health": health,
        "version": version,
        "url": install.public_url(primary_ip()),
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


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
