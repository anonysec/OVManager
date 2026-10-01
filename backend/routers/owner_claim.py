# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""First-run owner claim: a one-time key plus a chosen password makes the owner.

The installer never mints an owner password — it mints a claim key and prints
it. The account does not exist until the browser posts that key, so there is
nothing for scrollback to leak and no plaintext credential in any file. The
password this endpoint writes is a bcrypt hash in the ``admins`` table, never
``.env``.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend import data_paths
from backend.auth.auth import issue_session
from backend.auth.hash import hash_password
from backend.config import config
from backend.db import crud
from backend.db.engine import get_db
from backend.db.models import Admin
from backend.validation import PASSWORD_MIN_LENGTH, password_problem

router = APIRouter(tags=["Owner Claim"])

CLAIM_KEY_FILE = "owner-claim.key"

# The key is 128 bits from /dev/urandom, so guessing is not the threat; the
# limit is here so the endpoint cannot be used as a free bcrypt oracle.
_FAILURES: dict[str, list[float]] = {}
_MAX_FAILURES = 5
_FAILURE_WINDOW = 300


class ClaimRequest(BaseModel):
    claim_key: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)

    @field_validator("password")
    @classmethod
    def _policy(cls, value: str) -> str:
        """The owner password obeys the same rule as every other entry point."""
        problem = password_problem(value)
        if problem:
            raise ValueError(f"Owner password {problem}")
        return value


def claim_key_path():
    """Where the installer and ``ovm auth key`` put the key."""
    return data_paths.DATA_DIR / CLAIM_KEY_FILE


def owner_is_claimed(db: Session) -> bool:
    """True once the owner row carries a hash — a claim is then impossible."""
    row = crud.it_is_admin(db, username=config.ADMIN_USERNAME)
    return bool(row and row.password)


def read_claim_key() -> str | None:
    """The key on this host, or None when there is none.

    Raises when the file is there but unreadable, rather than answering "no
    key": an unreadable key file is a permissions bug and must not look like
    a missing one.
    """
    path = claim_key_path()
    try:
        if path.stat().st_size > 4096:
            raise ValueError(f"{path} is not a claim key file")
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot read {path} ({exc.__class__.__name__}) — re-run: ovm auth key",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return raw.strip() or None


def _rate_key(request: Request) -> str:
    from backend.client_ip import client_ip

    return hashlib.sha256(client_ip(request).encode()).hexdigest()[:16]


def _too_many_failures(key: str) -> bool:
    now = time.time()
    fresh = [t for t in _FAILURES.get(key, []) if now - t < _FAILURE_WINDOW]
    if fresh:
        _FAILURES[key] = fresh
    else:
        _FAILURES.pop(key, None)
    if len(_FAILURES) > 1000:  # bound memory against a spray from many IPs
        for stale in [k for k, times in _FAILURES.items() if not times or now - times[-1] > _FAILURE_WINDOW]:
            _FAILURES.pop(stale, None)
    return len(fresh) >= _MAX_FAILURES


def _note_failure(key: str) -> None:
    _FAILURES.setdefault(key, []).append(time.time())


@router.get("/owner-claim")
async def claim_status(db: Session = Depends(get_db)):
    """Whether a claim is still possible, without disclosing the key."""
    claimed = owner_is_claimed(db)
    key_present = False
    if not claimed:
        try:
            key_present = read_claim_key() is not None
        except HTTPException:
            key_present = True
    return {"claimable": not claimed and key_present}


@router.post("/owner-claim")
async def claim_owner(payload: ClaimRequest, request: Request, db: Session = Depends(get_db)):
    rate = _rate_key(request)
    if _too_many_failures(rate):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(_FAILURE_WINDOW)},
        )

    if owner_is_claimed(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This panel already has an owner. Sign in, or use: ovm auth reset",
        )

    expected = read_claim_key()
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No claim key on this host. Run: ovm auth key",
        )
    # compare_digest, not ==: a timing oracle on the claim key.
    if not hmac.compare_digest(expected, payload.claim_key.strip()):
        _note_failure(rate)
        _audit(db, request, "auth.claim_fail", "Bad claim key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That claim key is not valid")

    row = crud.it_is_admin(db, username=config.ADMIN_USERNAME)
    try:
        if row is None:
            db.add(Admin(username=config.ADMIN_USERNAME, password=hash_password(payload.password), disabled=False))
        else:
            row.password = hash_password(payload.password)
            row.disabled = False
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the owner account"
        ) from exc

    # One-shot: the key is spent the moment it works, so a copy of it that
    # leaks later cannot claim anything.
    try:
        claim_key_path().unlink(missing_ok=True)
    except OSError:
        pass
    _audit(db, request, "auth.claim", "Owner account created")
    return issue_session(request, db, config.ADMIN_USERNAME, "owner")


def _audit(db: Session, request: Request, action: str, detail: str) -> None:
    from backend.client_ip import client_ip
    from backend.operations.observability.audit import log_event

    log_event(db, action, actor=config.ADMIN_USERNAME, target=client_ip(request), detail=detail)
