"""Central input validators: one regex per concept, shared by API and bot.

The panel username rule, the URLPATH rule, and the domain/email rules each
used to live in two or three places with subtly different patterns. They
are defined once here; error messages stay at the call sites so API and
bot UX keep their own wording.
"""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")

URLPATH_RE = re.compile(r"^[A-Za-z0-9_-]+$")
URLPATH_MAX_LENGTH = 64

_DOMAIN_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
DOMAIN_MAX_LENGTH = 253

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(value: str) -> bool:
    """True when ``value`` is a legal panel/bot username."""
    return bool(value) and USERNAME_RE.fullmatch(value) is not None


def validate_urlpath(value: str) -> bool:
    """True when ``value`` is a legal URLPATH prefix (empty = serve at /)."""
    if not value:
        return True
    return len(value) <= URLPATH_MAX_LENGTH and URLPATH_RE.fullmatch(value) is not None


def validate_domain(value: str) -> bool:
    """True when ``value`` is a plausible DNS name for certificate issuance."""
    if not value or len(value) > DOMAIN_MAX_LENGTH:
        return False
    return _DOMAIN_RE.fullmatch(value) is not None


def validate_email(value: str) -> bool:
    """True when ``value`` looks like a deliverable email address."""
    return bool(value) and _EMAIL_RE.fullmatch(value) is not None
