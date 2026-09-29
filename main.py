#!/usr/bin/env python3
"""
Start OVManager panel.
"""

import getpass
import os
import sys
from pathlib import Path

import uvicorn

from backend.config import config

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


def _require_readable(path: str, what: str) -> None:
    """Fail with the actual problem when the service cannot open ``path``.

    ``os.path.isfile`` only needs directory traversal, so a key this account
    cannot read passes it and then dies inside uvicorn's SSL context build as
    a bare PermissionError with no hint of which file or why.

    This is a real failure mode, not a hypothetical: OVNode keeps its
    certificate in the same /etc/ssl/self-signed pair, and installing it on
    the panel's host rewrote the key and chmod-ed it 600. The panel kept
    serving from the context it had already loaded, so the damage only showed
    up on the next restart.
    """
    try:
        with open(path, "rb"):
            pass
    except OSError as exc:
        account = getpass.getuser()
        raise SystemExit(
            f"SSL {what} is not readable by '{account}': {path} ({exc}).\n"
            "Another service on this host may have replaced or tightened it.\n"
            f"Fix with:  chgrp {account} {path} && chmod 640 {path}\n"
            "Or check the panel's own diagnosis:  ovm doctor"
        ) from exc


def main():
    """Run OVManager panel."""
    if any(a == "--reset-urlpath" for a in sys.argv[1:]):
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
    if key:
        _require_readable(key, "key")
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
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
