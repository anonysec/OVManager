# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""`ovm tls status` in Python: installed certificate at a glance.

Read-only. Issuance (self-signed/ACME/LE) stays in bash — it orchestrates
openssl + acme.sh + service restarts as root, where the installer suite
already covers it. This command reports what is installed and when it
expires, which is what operators check 99% of the time.
"""

from __future__ import annotations

import os
import re
import subprocess

from cli.env import Install


def _enddate(cert: str) -> str | None:
    """Parse a PEM cert's notAfter via openssl (one fork, 10s cap)."""
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
    return m.group(1) if m else None


def status(install: Install) -> dict:
    """Installed key/cert/expiry. Never raises."""
    env = install.env
    key = env.get("SSL_KEYFILE") or ""
    cert = env.get("SSL_CERTFILE") or ""
    expiry = _enddate(cert) if cert and os.path.isfile(cert) else None
    return {
        "ok": True,
        "tls": install.tls_mode != "none",
        "key": key or None,
        "cert": cert or None,
        "expiry": expiry,
    }


def render_text(data: dict) -> str:
    if not data.get("tls"):
        return "  HTTPS certificate\n  Key file  <none> (plain HTTP)\n"
    lines = [
        "  HTTPS certificate",
        f"  {'Key file':<14} {data.get('key') or '<none>'}",
        f"  {'Cert file':<14} {data.get('cert') or '<none>'}",
    ]
    if data.get("expiry"):
        lines.append(f"  {'Expires':<14} {data['expiry']}")
    return "\n".join(lines) + "\n"
