# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Probe helpers: HTTP health, systemd/docker state. All injectable for tests."""

from __future__ import annotations

import json
import subprocess
import urllib.request


def fetch_health(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Return (reachable, version-or-'?') for a /health URL."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception:
        return False, "?"
    try:
        version = json.loads(body).get("version", "?") or "?"
    except Exception:
        version = "?"
    return True, str(version)


def service_state(compose_file: str, service: str = "ovmanager.service") -> tuple[str, str]:
    """Return (mode, state): mode is docker/native, state is a short word."""
    import os

    if os.path.isfile(compose_file):
        try:
            out = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            names = out.stdout.split()
            return "docker", ("running" if "ovmanager" in names else "stopped")
        except Exception:
            return "docker", "unknown"
    try:
        out = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=10,
        )
        state = out.stdout.strip() or "unknown"
        return "native", state
    except Exception:
        return "native", "unknown"


def primary_ip() -> str:
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        first = out.stdout.split()
        if first:
            return first[0]
    except Exception:
        pass
    return "127.0.0.1"
