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
        env = _read_env_file(os.path.join(install.install_dir, ".env"))
        install.env = env
        try:
            install.port = int(env.get("PORT") or DEFAULT_PORT)
        except ValueError:
            install.port = DEFAULT_PORT
        install.path_prefix = (env.get("URLPATH") or "").strip("/")
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

    def public_url(self, host: str) -> str:
        host = host or "127.0.0.1"
        base = f"{self.scheme}://{host}:{self.port}"
        return f"{base}/{self.path_prefix}/" if self.path_prefix else f"{base}/"
