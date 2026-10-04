# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Install layout + .env parsing shared by every CLI command.

Same sources of truth as manager.sh: INSTALL_DIR from OVM_APP_DIR (tests)
or /opt/ovmanager, PORT/URLPATH/TLS state from the installed .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_PORT = 2095
SYSTEMD_SERVICE = "ovmanager.service"
COMPOSE_FILE_NAME = "ovmanager-compose.yml"


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip().rstrip("\r")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    except OSError:
        pass
    return values


# The keys the CLI resolves the install layout from. Inside a container these
# arrive as environment variables (compose passes the host .env as env_file)
# while the .env file itself is not mounted, so the environment is the only
# source there. The file wins on a native install, where it is the real thing.
_ENV_KEYS = (
    "PORT",
    "URLPATH",
    "SSL_KEYFILE",
    "SSL_CERTFILE",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "ADMIN_PASSWORD_HASH",
)


def _read_install_env(path: str) -> dict[str, str]:
    """Installed .env, backfilled from the environment where it is silent."""
    values = _read_env_file(path)
    for key in _ENV_KEYS:
        if not values.get(key) and os.environ.get(key):
            values[key] = os.environ[key]
    return values


@dataclass
class Install:
    """Resolved install layout (never touches the network or services)."""

    install_dir: str = ""
    data_dir: str = "/var/lib/ovmanager"
    port: int = DEFAULT_PORT
    path_prefix: str = ""
    tls_mode: str = "none"
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def detect(cls, install_dir: str | None = None, data_dir: str | None = None) -> Install:
        install = cls(
            install_dir=install_dir or os.environ.get("OVM_APP_DIR", "/opt/ovmanager"),
            data_dir=data_dir or "/var/lib/ovmanager",
        )
        env = _read_install_env(os.path.join(install.install_dir, ".env"))
        install.env = env
        try:
            install.port = int(env.get("PORT") or DEFAULT_PORT)
        except ValueError:
            install.port = DEFAULT_PORT
        install.path_prefix = (env.get("URLPATH") or "").strip("/")
        if env.get("DATA_DIR"):
            install.data_dir = env["DATA_DIR"]
        if env.get("SSL_KEYFILE"):
            install.tls_mode = "self"
        return install

    @property
    def compose_file(self) -> str:
        return os.path.join(self.data_dir, COMPOSE_FILE_NAME)

    @property
    def scheme(self) -> str:
        return "http" if self.tls_mode == "none" else "https"

    @property
    def health_url(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.port}/health"

    @property
    def cafile(self) -> str | None:
        """Installed certificate, for pinning the local health probe."""
        return self.env.get("SSL_CERTFILE") or None

    def live_path_prefix(self) -> str:
        """The prefix the panel is SERVING, which is not always .env's.

        URLPATH in .env is only the seed: `ovm url set` and Settings -> General
        both write the settings row, and nothing writes .env back. Printing the
        seed showed an operator a URL that 404s the moment the prefix changed,
        while `ovm urlpath-show` reported the correct one at the same moment.
        Falls back to the seed if the database cannot be reached.
        """
        try:
            from backend.urlpath import get_urlpath

            return get_urlpath()
        except Exception:
            return self.path_prefix

    def public_url(self, host: str, live: bool = False) -> str:
        """host URL for this panel.

        live=True uses the prefix the panel is actually serving; the default
        keeps the .env seed, which is what the local health probe should keep
        using since it must not depend on a database round-trip.
        """
        host = host or "127.0.0.1"
        base = f"{self.scheme}://{host}:{self.port}"
        prefix = self.live_path_prefix() if live else self.path_prefix
        return f"{base}/{prefix}/" if prefix else f"{base}/"
