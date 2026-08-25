# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

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

    if config.SSL_KEYFILE or config.SSL_CERTFILE:
        key = config.SSL_KEYFILE
        cert = config.SSL_CERTFILE
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
        ssl_keyfile=config.SSL_KEYFILE or None,
        ssl_certfile=config.SSL_CERTFILE or None,
    )


if __name__ == "__main__":
    main()
