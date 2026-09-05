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

# One silent retry — ip-api.com free tier rate-limits (429) and the node
# add/edit path must not persist a failure as if it were a location.
_MAX_ATTEMPTS = 2


def _valid_result(data: dict) -> dict | None:
    """Validate an ip-api payload; return the normalized dict or None."""
    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    code = str(data.get("countryCode") or "").strip().upper()
    if len(code) not in (2, 3) or not code.isalpha():
        return None
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"country_code": code, "latitude": lat, "longitude": lon}


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

    last_error = None
    for _ in range(_MAX_ATTEMPTS):
        try:
            # NOTE: plain HTTP on purpose — ip-api.com's free tier answers
            # 403 "SSL unavailable" on HTTPS. No secret crosses the wire
            # (just the public server IP being asked about).
            resp = httpx2.get(
                f"http://ip-api.com/json/{ip}",
                timeout=_TIMEOUT,
                params={"fields": "status,message,countryCode,lat,lon"},
            )
            result = _valid_result(resp.json())
            if result:
                _geo_cache[host] = {"data": result, "_ts": _time.time()}
                return result
            last_error = "lookup returned no usable location"
            break  # well-formed "fail" response (e.g. private IP) — no retry
        except Exception as e:
            last_error = e
    logger.warning("Geolocation failed for %s: %s", host, last_error)

    return None
