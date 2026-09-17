# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Client address resolution behind an optional reverse proxy.

When ``TRUSTED_PROXY`` is enabled the proxy is the only hop we trust, so the
client address is the RIGHTMOST value of ``X-Forwarded-For`` — the entry that
proxy appended. Earlier entries are attacker-controlled in common configs
(e.g. nginx ``$proxy_add_x_forwarded_for`` keeps a client-supplied prefix),
so they are ignored. Values are validated as IP addresses; anything malformed
falls back to the direct peer address, so a spoofed header can neither bypass
rate limits nor fake audit entries.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from backend.config import config


def client_ip(request: Request) -> str:
    """Return the best-known client IP for ``request``."""
    if config.TRUSTED_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            candidate = forwarded.split(",")[-1].strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    return request.client.host if request.client else "unknown"
