#!/usr/bin/env python3
"""
Start OVManager panel.
"""
import sys
import os
from pathlib import Path

# Use script's directory for native installs, /app for Docker
APP_DIR = "/app" if Path("/app").is_dir() else str(Path(__file__).resolve().parent)
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from backend.config import config
import uvicorn


def main():
    """Run OVManager panel."""
    uvicorn.run(
        "backend.app:api",
        host=str(config.HOST),
        port=config.PORT,
        reload=False,
        workers=1,
        limit_max_requests=1000,
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