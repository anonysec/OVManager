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

from cli import render
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
        return render.block([render.heading("HTTPS certificate"), render.kv("Key file", "<none>  plain HTTP")])
    items = [
        ("Key file", data.get("key") or "<none>"),
        ("Cert file", data.get("cert") or "<none>"),
    ]
    if data.get("expiry"):
        items.append(("Expires", data["expiry"]))
    return render.block([render.heading("HTTPS certificate"), *render.rows(items)])


def migrate() -> dict:
    """Move a pre-declaration certificate onto the paths in ``.env``.

    Installs given a certificate before ``.env`` became the declaration keep
    one in ``DATA_DIR/tls``, and the declared paths now win over it. Left alone,
    the panel would quietly fall back to a stale certificate — the one failure
    nobody notices until a browser warns them months later. So this runs before
    the first read of the certificate, and says nothing when there is nothing
    to do.
    """
    try:
        from backend.routers.tls import migrate_legacy_tls
    except Exception as exc:  # the backend may not be importable host-side
        return {"ok": False, "error": f"Could not check for an old certificate: {exc}"}
    return migrate_legacy_tls()


def render_migrate(data: dict) -> str:
    if not data.get("migrated"):
        return ""  # the common case, and it should cost the reader nothing
    return render.block(
        [
            render.ok("moved the existing certificate onto the paths in .env"),
            render.kv("From", data["from"]),
            render.kv("To", data["to"]),
            render.hint("the old copy is left in place; remove it once this serves"),
        ]
    )
