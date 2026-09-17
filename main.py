# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

#!/usr/bin/env python3
"""
Start OVManager panel.
"""

import os
import sys
from pathlib import Path

import uvicorn

from backend.config import config

# Use script's directory for native installs, /app for Docker
APP_DIR = "/app" if Path("/app").is_dir() else str(Path(__file__).resolve().parent)
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)


def _resolve_ssl_paths() -> tuple[str | None, str | None]:
    """Return the active (key, cert) pair for uvicorn.

    Panel-managed files written by /api/tls (DATA_DIR/tls/) win when both are
    present; SSL_KEYFILE/SSL_CERTFILE from the environment are the fallback.
    """
    from backend.data_paths import DATA_DIR

    managed_dir = Path(DATA_DIR) / "tls"
    managed_key = managed_dir / "privkey.pem"
    managed_cert = managed_dir / "fullchain.pem"
    if managed_key.is_file() and managed_cert.is_file():
        return str(managed_key), str(managed_cert)
    return config.SSL_KEYFILE or None, config.SSL_CERTFILE or None


def main():
    """Run OVManager panel."""
    if any(a == "--reset-urlpath" for a in sys.argv[1:]):
        # Emergency recovery: operator forgot the panel path. Clears it in the
        # DB (panel returns to root) without touching anything else.
        from backend.urlpath import reset_urlpath

        if reset_urlpath():
            print("URLPATH cleared — the panel is served at root (/) again.")
            raise SystemExit(0)
        print("Could not reset URLPATH (database unavailable?). Start the panel once, then retry.", file=sys.stderr)
        raise SystemExit(1)

    key, cert = _resolve_ssl_paths()
    if key and not os.path.isfile(key):
        raise SystemExit(f"SSL key file not found: {key}")
    if cert and not os.path.isfile(cert):
        raise SystemExit(f"SSL cert file not found: {cert}")
    uvicorn.run(
        "backend.app:api",
        host=str(config.HOST),
        port=config.PORT,
        reload=False,
        workers=1,
        limit_concurrency=200,
        timeout_keep_alive=20,
        access_log=False,
        server_header=False,
        date_header=False,
        ssl_keyfile=key or None,
        ssl_certfile=cert or None,
        # Bounded graceful shutdown: without this, an open live/SSE stream
        # keeps uvicorn waiting and `systemctl stop` hangs until systemd's
        # 90-second timeout (observed on uninstall).
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
