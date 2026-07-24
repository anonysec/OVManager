from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import hashlib

from backend.auth.hash import verify_password
from backend.db.engine import get_db
from backend.config import config
from backend.db import crud
import time

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# In-memory rate limiter with IP extraction: {ip_hash: [timestamps]}
_login_attempts: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes

# Token blacklist for logout/revocation (in-memory, resets on restart)
_revoked_tokens: set[str] = set()

router = APIRouter(tags=["Login"])

# === Dynamic API prefix support (for URLPATH subpath installs) ===
URLPATH = (config.URLPATH or "").strip("/")
API_PREFIX = f"/{URLPATH}/api" if URLPATH else "/api"


def _client_ip_hash(request: Request) -> str:
    """Extract and hash client IP for rate limiting (no PII in memory)."""
    # Check X-Forwarded-For first (reverse proxy), fallback to direct client
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    # Hash to avoid storing raw IPs
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def authenticate_user(db: Session, username: str, password: str):
    main_admin_username = config.ADMIN_USERNAME
    main_admin_password = config.ADMIN_PASSWORD
    if username == main_admin_username and password == main_admin_password:
        return {"username": username, "type": "main_admin"}

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


def revoke_token(token: str) -> None:
    """Add token to revocation blacklist (e.g. on logout)."""
    _revoked_tokens.add(token)


def is_token_revoked(token: str) -> bool:
    """Check if token has been revoked."""
    # Hash token before checking (don't store raw tokens)
    hasher = hashlib.sha256()
    hasher.update(token.encode())
    token_hash = hasher.hexdigest()[:32]
    return token_hash in _revoked_tokens


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # Rate limiting by client IP (hashed)
    ip_hash = _client_ip_hash(request)
    now = time.time()
    _login_attempts[ip_hash] = [t for t in _login_attempts.get(ip_hash, []) if now - t < _LOCKOUT_SECONDS]
    if len(_login_attempts[ip_hash]) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(_LOCKOUT_SECONDS)},
        )

    admin = authenticate_user(db, form_data.username, form_data.password)
    if not admin:
        _login_attempts[ip_hash].append(now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The username or password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _login_attempts.pop(ip_hash, None)
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
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[ALGORITHM])

        username: str = payload.get("sub")
        user_type: str = payload.get("type")
        if username is None:
            raise credentials_exception
        if is_token_revoked(token):
            raise HTTPException(status_code=401, detail="Token has been revoked")
    except JWTError:
        raise credentials_exception
    return {"username": username or "", "type": user_type or ""}
