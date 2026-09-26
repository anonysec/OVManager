#!/usr/bin/env python3
"""
Start OVManager panel.
"""

import os
import sys
from pathlib import Path

import uvicorn

from backend.config import config

APP_DIR = "/app" if Path("/app").is_dir() else str(Path(__file__).resolve().parent)
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)


def _migrate_owner_password(env_file: str | None = None):
    """Hash the plaintext owner password on first boot (best effort).

    Installs start with legacy ADMIN_PASSWORD in .env. Once the venv is up
    we can hash it: rewrite .env with ADMIN_PASSWORD_HASH= and drop the
    plaintext line. Never blocks startup — a read-only .env (Docker images
    with baked env files) just keeps working in plaintext mode.
    """
    from backend.auth.hash import hash_password
    from backend.logger import logger

    if config.ADMIN_PASSWORD_HASH or not config.ADMIN_PASSWORD:
        return
    path = Path(env_file) if env_file else Path(config.model_config.get("env_file") or "")
    if path is None or not path.is_file():
        logger.info("Owner password stays in the environment (no .env file) — run install.sh reset-password to hash it")
        return
    try:
        new_hash = hash_password(config.ADMIN_PASSWORD)
        lines = path.read_text().splitlines(keepends=True)
        out, wrote_hash = [], False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("ADMIN_PASSWORD="):
                continue
            if stripped.startswith("ADMIN_PASSWORD_HASH="):
                out.append(f"ADMIN_PASSWORD_HASH={new_hash}\n")
                wrote_hash = True
            else:
                out.append(line)
        if not wrote_hash:
            out.append(f"ADMIN_PASSWORD_HASH={new_hash}\n")
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(out))
        tmp.chmod(0o600)
        tmp.replace(path)
        logger.info("Owner password migrated to ADMIN_PASSWORD_HASH in %s", path)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not hash the owner password in .env (%s) — it stays in plaintext mode", e)


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
        from backend.urlpath import reset_urlpath

        if reset_urlpath():
            print("URLPATH cleared — the panel is served at root (/) again.")
            raise SystemExit(0)
        print("Could not reset URLPATH (database unavailable?). Start the panel once, then retry.", file=sys.stderr)
        raise SystemExit(1)

    _migrate_owner_password()

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
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
