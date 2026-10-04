"""Panel authentication: login rate-limiting + opaque session tokens.

``/login`` exchanges credentials for a random opaque bearer token backed by the
``sessions`` table (see backend/auth/sessions.py). There is no JWT anywhere —
token verification is one indexed DB lookup, revocation is a row delete that
survives restarts, and expiry is sliding-idle + absolute cap.
"""

import hashlib
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.auth.hash import hash_password, needs_rehash, verify_password
from backend.auth.sessions import create_session, purge_expired, revoke_token, verify_session
from backend.config import config
from backend.db import crud
from backend.db.engine import SessionLocal, get_db

logger = logging.getLogger("auth")

_login_attempts: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5  # per (IP, username) per window
_MAX_PER_IP = 20  # per IP across usernames per window
# Per USERNAME, independent of source address. Both other buckets key on the IP,
# so a botnet or proxy pool gave every request a brand-new pair of buckets and
# the owner's password could be tried without limit. Deliberately generous: this
# bucket is the one an attacker cannot avoid, so a low ceiling would also let
# anyone lock a known account out by failing against it on purpose.
_MAX_PER_USER = 60  # per username across all addresses per window
_LOCKOUT_SECONDS = 300
_CLEANUP_INTERVAL = 600
_last_cleanup: float = 0.0


def _get_bucket(key_hash: str) -> list[float]:
    now = time.time()
    bucket = _login_attempts.get(key_hash, [])
    fresh = [t for t in bucket if now - t < _LOCKOUT_SECONDS]
    if len(fresh) != len(bucket):
        _login_attempts[key_hash] = fresh
    return fresh


def _put_bucket(key_hash: str, times: list[float]) -> None:
    _login_attempts[key_hash] = times


def _purge_stale_attempts() -> None:
    """Remove buckets with no recent attempts to bound memory growth."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    stale_keys = [k for k, times in _login_attempts.items() if not times or now - times[-1] > _LOCKOUT_SECONDS]
    for k in stale_keys:
        _login_attempts.pop(k, None)


router = APIRouter(tags=["Login"])


def _client_ip(request: Request) -> str:
    """Extract the client IP, honouring X-Forwarded-For only from a trusted
    proxy and only its rightmost entry (the one the proxy appended)."""
    from backend.client_ip import client_ip

    return client_ip(request)


def _ip_hash(ip: str) -> str:
    """Hash IP for rate-limit storage (no PII in memory)."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _rate_key(ip: str, username: str) -> str:
    """Per (IP, username) bucket — isolates users behind shared NAT/proxy."""
    return hashlib.sha256(f"{ip}\0{(username or '').lower()}".encode()).hexdigest()[:16]


def _user_key(username: str) -> str:
    """Per username, no address in the key — see _MAX_PER_USER."""
    return hashlib.sha256(f"user\0{(username or '').lower()}".encode()).hexdigest()[:16]


# A real bcrypt hash of a value nobody can supply, verified against on every
# failure path. Without this the unknown-username branch returns before bcrypt
# runs, so a 401 costs microseconds for a name that does not exist and ~100ms
# for one that does — which enumerates accounts through the login endpoint.
# Generated rather than pasted so it cannot be mistaken for a real credential.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def _waste_verify(password: str) -> None:
    """Spend the same bcrypt time a real credential would, and discard it."""
    try:
        verify_password(password, _DUMMY_HASH)
    except Exception:
        pass


def authenticate_user(db: Session, username: str, password: str):
    """Authenticate against the ``admins`` table — the only credential store.

    The owner is a normal row whose username matches ``ADMIN_USERNAME``; their
    bcrypt hash lives in the database like every other admin's, so ``.env``
    holds no credential.
    """
    admin = crud.it_is_admin(db, username=username)
    if not admin or not admin.password:
        _waste_verify(password)
        return None
    if admin.disabled:
        _waste_verify(password)
        return None
    if not verify_password(password, admin.password):
        return None

    try:
        if needs_rehash(admin.password):
            admin.password = hash_password(password)
            db.commit()
    except Exception:
        db.rollback()

    role = "owner" if username == config.ADMIN_USERNAME else "admin"
    return {"username": admin.username, "type": role}


def role_is_current(db: Session, username: str, role: str) -> bool:
    if role == "owner":
        return username == config.ADMIN_USERNAME
    if role != "admin":
        return False
    admin = crud.get_admin_by_username(db, username=username)
    return admin is not None and not admin.disabled


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    _purge_stale_attempts()

    ip = _client_ip(request)
    now = time.time()
    user_key = _rate_key(ip, form_data.username)
    ip_key = _ip_hash(ip)
    name_key = _user_key(form_data.username)

    attempts = _get_bucket(user_key)
    ip_attempts = _get_bucket(ip_key)
    name_attempts = _get_bucket(name_key)

    if (
        len(attempts) >= _MAX_ATTEMPTS
        or len(ip_attempts) >= _MAX_PER_IP
        or len(name_attempts) >= _MAX_PER_USER
    ):
        from backend.operations.observability.audit import log_event

        log_event(db, "auth.lockout", actor=form_data.username, target=ip, detail="Too many login attempts")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(_LOCKOUT_SECONDS)},
        )

    admin = authenticate_user(db, form_data.username, form_data.password)
    if not admin:
        attempts.append(now)
        _put_bucket(user_key, attempts)
        ip_attempts.append(now)
        _put_bucket(ip_key, ip_attempts)
        name_attempts.append(now)
        _put_bucket(name_key, name_attempts)
        from backend.operations.observability.audit import log_event

        log_event(db, "auth.login_fail", actor=form_data.username, target=ip, detail="Bad credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The username or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _login_attempts.pop(user_key, None)
    _login_attempts.pop(name_key, None)
    return issue_session(request, db, admin["username"], admin["type"])


def issue_session(request: Request, db: Session, username: str, role: str):
    """Open a session and return the login-shaped response: token + cookie.

    The one place a session is handed out, so the first-run owner claim returns
    a response the frontend can store exactly like a login.
    """
    purge_expired(db)
    raw_token = create_session(
        db,
        username,
        role,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    from fastapi.responses import JSONResponse as _JSONResponse

    secure = request.url.scheme == "https"
    if config.TRUSTED_PROXY and request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https":
        secure = True
    resp = _JSONResponse(
        {
            "access_token": raw_token,
            "refresh_token": None,
            "token_type": "bearer",
            "username": username,
            "role": role,
        }
    )
    resp.set_cookie(
        key="ovm_session",
        value=raw_token,
        max_age=config.SESSION_MAX_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    """Revoke the presented session token (row delete — survives restarts)."""
    from fastapi.responses import JSONResponse as _JSONResponse

    raw = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw = auth_header[7:]
    if not raw:
        raw = request.cookies.get("ovm_session")
    if raw:
        db = SessionLocal()
        try:
            revoke_token(db, raw)
        finally:
            db.close()
    resp = _JSONResponse({"detail": "Logged out"})
    resp.delete_cookie(key="ovm_session", path="/")
    return resp


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login", auto_error=False)


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


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw = token or request.cookies.get("ovm_session")
    user = verify_session_token(raw, db) if raw else None
    if user is None or user["type"] not in ("admin", "owner"):
        raise credentials_exception
    if not role_is_current(db, user["username"], user["type"]):
        raise credentials_exception
    return user
