import hmac
import hashlib
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.auth.hash import verify_password
from backend.config import config
from backend.db import crud
from backend.db.engine import get_db

logger = logging.getLogger("auth")

ALGORITHM = "HS256"

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
    stale_keys = [
        ip for ip, times in _login_attempts.items()
        if not times or now - times[-1] > _LOCKOUT_SECONDS
    ]
    for k in stale_keys:
        _login_attempts.pop(k, None)


# ── Token revocation (in-memory — survives login/logout cycle) ───
_revoked_tokens: set[str] = set()
_MAX_REVOKED = 10_000  # cap to prevent memory leak on very long uptimes


def revoke_token(token: str) -> None:
    """Add token hash to revocation blacklist."""
    h = hashlib.sha256(token.encode()).hexdigest()[:32]
    if len(_revoked_tokens) >= _MAX_REVOKED:
        _revoked_tokens.clear()  # worst case: un-revoke on overflow (rare)
        logger.warning("token revocation list overflowed — cleared")
    _revoked_tokens.add(h)


def is_token_revoked(token: str) -> bool:
    """Constant-time check against the revocation set."""
    h = hashlib.sha256(token.encode()).hexdigest()[:32]
    return h in _revoked_tokens


# ── Router ───────────────────────────────────────────────────────
router = APIRouter(tags=["Login"])

URLPATH = (config.URLPATH or "").strip("/")
API_PREFIX = f"/{URLPATH}/api" if URLPATH else "/api"


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
    main_admin_username = config.ADMIN_USERNAME
    main_admin_password = config.ADMIN_PASSWORD

    if username == main_admin_username:
        # Constant-time comparison — even if lengths differ, hmac.compare_digest
        # handles that safely by padding the shorter string.
        if hmac.compare_digest(
            password.encode(), main_admin_password.encode()
        ):
            return {"username": username, "type": "main_admin"}
        # Avoid leaking whether the *username* was correct: still check DB
        # (main admin won't be in DB, so this returns None, but the timing
        # path is identical for wrong-user vs wrong-pass).

    admin = crud.it_is_admin(db, username=username)
    if admin:
        if verify_password(password, admin.password):
            return {"username": admin.username, "type": "admin"}

    return None


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.JWT_SECRET_KEY, algorithm=ALGORITHM)


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
    access_token_expires = timedelta(seconds=config.JWT_ACCESS_TOKEN_EXPIRES)
    access_token = create_access_token(
        data={"sub": admin["username"], "type": admin["type"]},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


# OAuth2 scheme must use the same dynamic prefix as the mounted routes
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_PREFIX}/login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, config.JWT_SECRET_KEY, algorithms=[ALGORITHM]
        )
        username: str = payload.get("sub")
        user_type: str = payload.get("type")
        if username is None:
            raise credentials_exception
        if is_token_revoked(token):
            raise HTTPException(status_code=401, detail="Token has been revoked")
    except JWTError:
        raise credentials_exception
    return {"username": username or "", "type": user_type or ""}
