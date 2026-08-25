# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Panel authentication: login rate-limiting + opaque session tokens.

Auth model: ``/login`` exchanges credentials for a random opaque bearer token
backed by the ``sessions`` table (see backend/auth/sessions.py). There is no
JWT anywhere — token verification is one indexed DB lookup, revocation is a
row delete that survives restarts, and expiry is sliding-idle + absolute cap.

The HTTP contract is unchanged: clients still send
``Authorization: Bearer <token>`` and /login still returns an
``access_token`` field, so the frontend needed no changes.
"""

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.auth.hash import verify_password
from backend.auth.sessions import create_session, purge_expired, revoke_token, verify_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal, get_db

logger = logging.getLogger("auth")

# ── Rate limiter ──────────────────────────────────────────────────
# In-memory with cleanup; acceptable for a single-process panel.
# Persistent storage adds complexity with diminishing returns.
_login_attempts: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes
_CLEANUP_INTERVAL = 600  # purge stale entries every 10 min
_last_cleanup: float = 0.0


def _purge_stale_attempts() -> None:
    """Remove IPs with no recent attempts to bound memory growth."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    stale_keys = [ip for ip, times in _login_attempts.items() if not times or now - times[-1] > _LOCKOUT_SECONDS]
    for k in stale_keys:
        _login_attempts.pop(k, None)


# ── Router ───────────────────────────────────────────────────────
router = APIRouter(tags=["Login"])


def _client_ip(request: Request) -> str:
    """Extract client IP. Honours X-Forwarded-For only from trusted
    proxies (when running behind a known reverse proxy like nginx/caddy).
    If no proxy headers are present, uses the direct client address.
    """
    # Only trust X-Forwarded-For when a trusted proxy is configured
    if config.TRUSTED_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ip_hash(ip: str) -> str:
    """Hash IP for rate-limit storage (no PII in memory)."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def authenticate_user(db: Session, username: str, password: str):
    """Authenticate against main admin or DB-stored admins.

    Main admin password is compared with constant-time hmac to avoid
    timing side-channels.
    """
    owner_username = config.ADMIN_USERNAME
    owner_password = config.ADMIN_PASSWORD

    if username == owner_username:
        # Constant-time comparison — even if lengths differ, hmac.compare_digest
        # handles that safely by padding the shorter string.
        if hmac.compare_digest(password.encode(), owner_password.encode()):
            return {"username": username, "type": "owner"}
        # Avoid leaking whether the *username* was correct: still check DB
        # (main admin won't be in DB, so this returns None, but the timing
        # path is identical for wrong-user vs wrong-pass).

    admin = crud.it_is_admin(db, username=username)
    if admin:
        if verify_password(password, admin.password):
            return {"username": admin.username, "type": "admin"}

    return None


def _role_is_current(db: Session, username: str, role: str) -> bool:
    if role == "owner":
        return username == config.ADMIN_USERNAME
    return role == "admin" and crud.get_admin_by_username(db, username=username) is not None


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    _purge_stale_attempts()

    ip = _client_ip(request)
    ip_h = _ip_hash(ip)
    now = time.time()

    attempts = _login_attempts.get(ip_h, [])
    attempts = [t for t in attempts if now - t < _LOCKOUT_SECONDS]
    _login_attempts[ip_h] = attempts

    if len(attempts) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(_LOCKOUT_SECONDS)},
        )

    admin = authenticate_user(db, form_data.username, form_data.password)
    if not admin:
        attempts.append(now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The username or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _login_attempts.pop(ip_h, None)
    purge_expired(db)  # opportunistic cleanup of dead sessions
    raw_token = create_session(
        db,
        admin["username"],
        admin["type"],
        user_agent=request.headers.get("user-agent"),
        ip=ip,
    )
    # Contract: frontend stores access_token and uses it as a Bearer token.
    # refresh_token is null — sessions slide on activity instead of rotating.
    return {"access_token": raw_token, "refresh_token": None, "token_type": "bearer"}


@router.post("/logout")
async def logout(request: Request):
    """Revoke the presented session token (row delete — survives restarts)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        db = SessionLocal()
        try:
            revoke_token(db, auth_header[7:])
        finally:
            db.close()
    return {"detail": "Logged out"}


# OAuth2 scheme — tokenUrl is relative; works regardless of URLPATH prefix
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


@router.post("/refresh")
async def refresh_token():
    """Retired endpoint (JWT era). Sessions slide on activity; when a session
    expires the client must log in again. Returning 401 drives the frontend's
    existing forced-logout path."""
    raise HTTPException(status_code=401, detail="Session expired — please log in again")


def verify_session_token(raw: str, db: Session) -> dict | None:
    """Shared Bearer-token verifier (also used by node-facing routers that
    accept panel credentials). Returns the frontend-shaped identity dict."""
    session = verify_session(db, raw)
    if session is None:
        return None
    return {"username": session.username, "type": session.role}


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = verify_session_token(token, db)
    if user is None or user["type"] not in ("admin", "owner"):
        raise credentials_exception
    if not _role_is_current(db, user["username"], user["type"]):
        raise credentials_exception
    return user
