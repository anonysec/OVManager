# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""IP-based geolocation using ip-api.com (free, no key needed)."""

from __future__ import annotations

import ipaddress
import logging
import socket
import time as _time
from urllib.parse import urlsplit

import httpx2

logger = logging.getLogger(__name__)

# Cache: IP → {country_code, lat, lon}
_geo_cache: dict[str, dict] = {}
_GEO_CACHE_TTL = 3600  # 1 hour
_GEO_CACHE_MAX = 10_000
_GEO_CACHE_HITS = 0
_GEO_CACHE_MISSES = 0


# Timeout for geolocation requests
_TIMEOUT = 5.0


def _extract_host(address: str) -> str | None:
    """Extract a hostname/IP from hostnames, URLs, host:port, and IPv6 input."""
    raw = str(address or "").strip()
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        pass

    candidate = raw if "://" in raw else f"//{raw}"
    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        host = None
    return host.strip("[]") if host else None


def resolve_ip(address: str) -> str | None:
    """Resolve a hostname to an IP address."""
    try:
        ipaddress.ip_address(address)
        return address
    except ValueError:
        pass
    try:
        return socket.gethostbyname(address)
    except (socket.gaierror, OSError):
        return None


def geolocate(address: str) -> dict | None:
    """Look up country code + coordinates for an address (hostname or IP).

    Returns dict with keys: country_code, latitude, longitude
    or None if lookup fails.
    """
    # Extract hostname/IP safely; splitting on ':' breaks IPv6 and URLs.
    host = _extract_host(address)
    if not host:
        return None

    # Check cache (TTL + size bound)
    if host in _geo_cache:
        entry = _geo_cache[host]
        if entry.get("_ts", 0) > _time.time() - _GEO_CACHE_TTL:
            return entry["data"]
        del _geo_cache[host]

    # Bound cache size: evict oldest entries when over max
    if len(_geo_cache) >= _GEO_CACHE_MAX:
        for k in sorted(_geo_cache, key=lambda k: _geo_cache[k].get("_ts", 0))[:1000]:
            del _geo_cache[k]

    # Resolve hostname to IP
    ip = resolve_ip(host)
    if not ip:
        return None

    try:
        resp = httpx2.get(
            f"https://ip-api.com/json/{ip}",
            timeout=_TIMEOUT,
            params={"fields": "status,countryCode,lat,lon"},
        )
        data = resp.json()
        if data.get("status") == "success":
            result = {
                "country_code": data.get("countryCode", ""),
                "latitude": data.get("lat", 0.0),
                "longitude": data.get("lon", 0.0),
            }
            _geo_cache[host] = {"data": result, "_ts": _time.time()}
            return result
    except Exception as e:
        logger.error("Geolocation failed for %s: %s", host, e)

    return None
