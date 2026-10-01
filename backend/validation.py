"""Central input validators: one regex per concept, shared by API and bot.

Error messages stay at the call sites so API and bot UX keep their own wording.
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


# The owner chooses a password from the installer, `ovm auth reset` or the
# browser claim, so the rule lives once here.
PASSWORD_MIN_LENGTH = 8
PASSWORD_PLACEHOLDERS = ("change-me", "changeme", "change_me", "password123", "admin123")


def password_problem(value: str) -> str | None:
    """Return a human reason when ``value`` is unacceptable, else None."""
    if not value:
        return "must not be empty"
    if "\n" in value or "\r" in value:
        return "must be a single line"
    if len(value) < PASSWORD_MIN_LENGTH:
        return f"must be at least {PASSWORD_MIN_LENGTH} characters (the panel requires >= {PASSWORD_MIN_LENGTH})"
    lowered = value.lower()
    if any(placeholder in lowered for placeholder in PASSWORD_PLACEHOLDERS):
        return "looks like a placeholder — choose a strong password"
    return None
