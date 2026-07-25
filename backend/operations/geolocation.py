"""IP-based geolocation using ip-api.com (free, no key needed)."""
from __future__ import annotations

import socket
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Cache: IP → {country_code, lat, lon}
_geo_cache: dict[str, dict] = {}

# Timeout for geolocation requests
_TIMEOUT = 5.0


def resolve_ip(address: str) -> Optional[str]:
    """Resolve a hostname to an IP address."""
    try:
        return socket.gethostbyname(address)
    except (socket.gaierror, OSError):
        return None


def geolocate(address: str) -> Optional[dict]:
    """Look up country code + coordinates for an address (hostname or IP).

    Returns dict with keys: country_code, latitude, longitude
    or None if lookup fails.
    """
    # Extract hostname from address (strip port if present)
    host = address.split(":")[0].strip()
    if not host:
        return None

    # Check cache
    if host in _geo_cache:
        return _geo_cache[host]

    # Resolve hostname to IP
    ip = resolve_ip(host)
    if not ip:
        return None

    try:
        resp = httpx.get(
            f"http://ip-api.com/json/{ip}",
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
            _geo_cache[host] = result
            return result
    except Exception as e:
        logger.error("Geolocation failed for %s: %s", host, e)

    return None
