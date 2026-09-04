# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Password hashing with bcrypt.

``passlib`` was dropped as a dependency: its last release was in 2020, it is
unmaintained, and it breaks outright against ``bcrypt >= 4.1`` (it reads the
removed ``bcrypt.__about__`` and then feeds a >72-byte probe password to
``hashpw``, which now raises instead of truncating). Depending on an abandoned
shim in front of the password database is not a good supply-chain position, so
the thin wrapper below talks to ``bcrypt`` directly.

Compatibility notes:

* Existing hashes written by passlib are standard ``$2b$12$...`` bcrypt hashes
  and verify unchanged — no rehash-on-login or user-visible migration needed.
* ``gensalt()`` defaults to 12 rounds, matching passlib's bcrypt default, so
  new hashes are directly comparable to old ones.
* bcrypt truncates at 72 bytes. The cut is made on a UTF-8 character boundary
  so a multibyte password is never split mid-sequence; hashing and verifying
  apply the identical transform, so results stay consistent.
"""

from __future__ import annotations

import bcrypt

# bcrypt only considers the first 72 bytes of the input.
_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    """Encode a password for bcrypt, truncating on a character boundary."""
    raw = (password or "").encode("utf-8")
    if len(raw) <= _MAX_BYTES:
        return raw
    # Drop the trailing partial sequence rather than feeding bcrypt invalid
    # UTF-8, then re-encode to land on a boundary.
    truncated = raw[:_MAX_BYTES].decode("utf-8", errors="ignore")
    return truncated.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` (12 rounds, ``$2b$`` prefix)."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against a stored hash.

    Returns ``False`` — never raises — for a malformed or foreign hash, so a
    corrupt row or a hand-edited database yields a failed login rather than a
    500 that leaks internals.
    """
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain_password), hashed_password.encode("ascii"))
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True when the stored hash is weaker than the current policy.

    Used to upgrade legacy hashes (lower round count, or the ``$2a$``/``$2y$``
    prefixes some other tools emit) the next time the user logs in.
    """
    if not hashed_password:
        return True
    parts = hashed_password.split("$")
    # Expected shape: ['', '2b', '12', '<22 chars salt><31 chars digest>']
    if len(parts) < 4 or parts[1] not in ("2b", "2a", "2y", "2x"):
        return True
    try:
        return int(parts[2]) < 12
    except ValueError:
        return True
