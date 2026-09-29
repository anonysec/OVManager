# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Probe helpers: HTTP health, systemd/docker state. All injectable for tests."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import urllib.request


def _tls_context(cafile: str | None) -> ssl.SSLContext | None:
    """SSL context for probing the panel's own HTTPS endpoint.

    The panel's certificate is usually self-signed (the installer default), so
    default verification fails against a perfectly healthy panel. When the
    installed cert is readable we pin to it: the chain must still match that
    exact certificate, but the hostname is not checked — the installer's cert
    carries the public IP as its CN and no SANs, while the probe dials
    127.0.0.1, so a name check fails on a healthy panel ("IP address
    mismatch"). Identity comes from the pinned certificate, which is the same
    rule the node transport uses for the mirror-image case.

    With no readable cert we mirror the bash path's `curl -k` so both agree on
    what "healthy" means. Plain HTTP gets no context.
    """
    if cafile and os.path.isfile(cafile):
        try:
            context = ssl.create_default_context(cafile=cafile)
            context.check_hostname = False
            return context
        except Exception:
            pass
    return ssl._create_unverified_context()


def fetch_health(url: str, timeout: float = 5.0, cafile: str | None = None) -> tuple[bool, str]:
    """Return (reachable, version-or-'?') for a /health URL."""
    kwargs: dict = {"timeout": timeout}
    if url.startswith("https://"):
        context = _tls_context(cafile)
        if context is not None:
            kwargs["context"] = context
    try:
        with urllib.request.urlopen(url, **kwargs) as resp:
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
