"""Shared UUID <-> CN conversion logic.

This module provides the single source of truth for converting between
panel UUIDs (with/without dashes) and OpenVPN Common Names (CNs).

Both OVManager (panel) and OVNode (agent) should import from here.
"""

import re
from typing import Optional

# UUID regex: 8-4-4-4-12 hex digits with optional dashes
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
)

# Strict CN regex: exactly 32 hex chars (UUID without dashes)
_CN_RE = re.compile(r"^[a-fA-F0-9]{32}$")


def is_uuid(value: str) -> bool:
    """Check if a string is a valid UUID (with or without dashes)."""
    return bool(_UUID_RE.match(value))


def cn_from_uid(uid: str) -> str:
    """Derive the OpenVPN CN from a panel UUID.

    - If UID is a UUID (with/without dashes): return UUID without dashes (32 hex chars)
    - Otherwise: return UID as-is (assumed to be a simple ID already safe for CN)
    """
    if is_uuid(uid):
        return uid.replace("-", "")
    return uid


def validate_cn(cn: str) -> str:
    """Validate CN is exactly 32 hex characters. Raises ValueError if invalid."""
    if not _CN_RE.match(cn):
        raise ValueError(f"Invalid CN format: must be 32 hex characters, got '{cn}'")
    return cn


def uid_from_cn(cn: str) -> Optional[str]:
    """Attempt to reverse CN -> UUID with dashes.

    Returns UUID with standard 8-4-4-4-12 format if CN is 32 hex chars,
    otherwise returns None (CN was a simple ID, not a UUID-derived CN).
    """
    if _CN_RE.match(cn):
        return f"{cn[:8]}-{cn[8:12]}-{cn[12:16]}-{cn[16:20]}-{cn[20:]}"
    return None