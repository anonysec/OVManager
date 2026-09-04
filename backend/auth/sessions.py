# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Opaque, DB-backed session tokens (replaces JWT auth).

Design:
- The raw token is 256 bits of ``secrets`` entropy; only its SHA-256 digest
  is stored, so a leaked DB yields no usable bearer tokens.
- Two timeouts: an absolute cap (``SESSION_MAX_SECONDS`` from creation) and a
  sliding idle timeout (``SESSION_IDLE_SECONDS`` relative to ``last_seen_at``).
  Active users stay logged in; idle ones are logged out — the behavior admins
  expect from a session, without any refresh-token machinery.
- Sliding updates are throttled to at most one row write per
  ``TOUCH_THROTTLE_SECONDS`` per session so read-heavy pages stay cheap.
- Currency of role membership is still enforced by callers
  (``_role_is_current``), and deleting an admin revokes their sessions
  outright (see ``revoke_user_sessions``).
"""

import hashlib
import secrets
import time

from sqlalchemy.orm import Session as SASession

from backend.db.models import AuthSession

TOKEN_BYTES = 32  # 256-bit → 43-char urlsafe token
TOUCH_THROTTLE_SECONDS = 300  # max one last_seen write per 5 min per session


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(
    db: SASession,
    username: str,
    role: str,
    *,
    max_seconds: int | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    """Issue a new session and return the RAW token (shown to the client once)."""
    from backend.config import config

    raw = secrets.token_urlsafe(TOKEN_BYTES)
    now = time.time()
    ttl = max_seconds if max_seconds is not None else config.SESSION_MAX_SECONDS
    db.add(
        AuthSession(
            token_hash=_hash(raw),
            username=username,
            role=role,
            created_at=now,
            expires_at=now + ttl,
            last_seen_at=now,
            user_agent=(user_agent or "")[:256] or None,
            ip=(ip or "")[:64] or None,
        )
    )
    db.commit()
    return raw


def verify_session(db: SASession, raw: str, *, idle_seconds: int | None = None) -> AuthSession | None:
    """Resolve a raw bearer token to its session, or None when invalid/expired.

    Expired rows are deleted eagerly (self-cleaning); valid sessions get a
    throttled sliding touch.
    """
    from backend.config import config

    if not raw:
        return None
    idle = idle_seconds if idle_seconds is not None else config.SESSION_IDLE_SECONDS
    session = db.query(AuthSession).filter(AuthSession.token_hash == _hash(raw)).first()
    if session is None:
        return None
    now = time.time()
    if now >= session.expires_at or now - (session.last_seen_at or 0) > idle:
        db.delete(session)
        db.commit()
        return None
    if now - session.last_seen_at >= TOUCH_THROTTLE_SECONDS:
        session.last_seen_at = now
        try:
            db.commit()
        except Exception:
            db.rollback()  # a failed touch must never break the request
    return session


def revoke_token(db: SASession, raw: str) -> bool:
    """Delete the session backing this raw token. Returns True if one existed."""
    if not raw:
        return False
    deleted = db.query(AuthSession).filter(AuthSession.token_hash == _hash(raw)).delete()
    db.commit()
    return deleted > 0


def revoke_user_sessions(db: SASession, username: str) -> int:
    """Delete every session of a user (e.g. when the admin is removed)."""
    deleted = db.query(AuthSession).filter(AuthSession.username == username).delete()
    db.commit()
    return deleted


def purge_expired(db: SASession, *, idle_seconds: int | None = None) -> int:
    """Delete dead sessions (absolute cap OR idle timeout). Called at login."""
    from backend.config import config

    idle = idle_seconds if idle_seconds is not None else config.SESSION_IDLE_SECONDS
    now = time.time()
    stale = [s for s in db.query(AuthSession).all() if now >= s.expires_at or now - (s.last_seen_at or 0) > idle]
    for s in stale:
        db.delete(s)
    if stale:
        db.commit()
    return len(stale)
