# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""TLS pinning for node connections (PasarGuard's server_ca idea).

The panel stores the node's certificate (PEM) the first time it sees it
(trust on first use, during an explicit operator add/update) and then
verifies HTTPS against exactly that certificate. A self-signed node is
therefore as safe as a Let's Encrypt one — the unverified-TLS fallback
disappears once a pin exists.

Certificate files live under ``DATA_DIR/node-certs/`` (0600), one per
node id, regenerated when the pinned PEM changes.
"""

from __future__ import annotations

import os
import ssl

from backend.data_paths import DATA_DIR

_CERT_DIR = DATA_DIR / "node-certs"


def fetch_server_cert(address: str, port: int, timeout: float = 10.0) -> str | None:
    """Fetch the TLS certificate PEM served by ``address:port``.

    Trust-on-first-use fetch: verification is intentionally off (we are
    collecting the cert to pin). Returns PEM text or None on any failure.
    """
    try:
        pem = ssl.get_server_certificate((address, int(port)), timeout=timeout)
        return pem if "BEGIN CERTIFICATE" in pem else None
    except Exception:
        return None


def ca_file_for(node_id: int, server_ca: str | None) -> str | None:
    """Materialize the pinned CA for ``node`` and return its path.

    Writes/overwrites ``DATA_DIR/node-certs/{id}.pem`` (0600) only when the
    content changed. Returns None when there is no pin or the PEM is not a
    certificate — callers then fall back to the default verify policy.
    """
    if not server_ca or "BEGIN CERTIFICATE" not in server_ca:
        return None
    _CERT_DIR.mkdir(parents=True, exist_ok=True)
    path = _CERT_DIR / f"{int(node_id)}.pem"
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != server_ca:
        path.write_text(server_ca, encoding="utf-8")
        os.chmod(path, 0o600)
    return str(path)
