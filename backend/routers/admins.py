# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import time

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.auth.hash import hash_password
from backend.config import config
from backend.db import crud
from backend.db.engine import get_db
from backend.db.models import AuthSession
from backend.db.models import User as _User
from backend.operations.audit import log_event
from backend.schema import AdminCreate, Admins, AdminStatusUpdate, AdminUpdate, ResponseModel

router = APIRouter(prefix="/admin", tags=["Admins"])


@router.get("/me/defaults", response_model=ResponseModel)
async def get_my_defaults(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """Effective new-user plan for the caller: their override, else the owner's.

    Readable by any signed-in admin (unlike ``GET /server/settings``), so the
    Add User form and the Telegram bot can pre-fill the plan that will actually
    apply instead of the owner-only global.
    """
    username = user.get("username")
    defaults = crud.effective_user_defaults(db, username)
    admin = crud.it_is_admin(db, username) if username else None
    overrides = {
        "days": getattr(admin, "default_days", None) if admin else None,
        "traffic_gb": getattr(admin, "default_traffic_gb", None) if admin else None,
        "max_users": getattr(admin, "default_max_users", None) if admin else None,
    }
    return ResponseModel(
        success=True,
        msg="Effective new-user defaults",
        data={
            "admin": username,
            "role": user.get("type"),
            "effective": defaults,
            "overrides": overrides,
            "source": "admin" if any(v is not None for v in overrides.values()) else "owner",
        },
    )


@router.get("/", response_model=ResponseModel)
async def get_all_admins(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    # Single GROUP BY query instead of O(n×m) Python loop
    counts = dict(db.query(_User.owner, func.count(_User.id)).group_by(_User.owner).all())
    result = crud.get_all_admins(db)
    admin_list = []
    for admin in result:
        admin_data = Admins.model_validate(admin)
        admin_data.users_count = counts.get(admin.username, 0)
        admin_data.effective_defaults = crud.effective_user_defaults(db, admin.username)
        admin_list.append(admin_data)

    return ResponseModel(
        success=True,
        msg="Admins retrieved successfully",
        data=admin_list,
    )


@router.post("/", response_model=ResponseModel)
async def create_admin(
    admin: AdminCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=admin.username)
    if existing_admin:
        return ResponseModel(success=False, msg="Admin with this username already exists", data=None)

    new_admin = crud.create_admin(db, admin)
    log_event(db, "admin.create", actor=user.get("username"), target=new_admin.username)
    data = Admins.model_validate(new_admin)
    data.users_count = 0
    data.effective_defaults = crud.effective_user_defaults(db, new_admin.username)
    return ResponseModel(
        success=True,
        msg="Admin created successfully",
        data=data,
    )


@router.put("/")
async def update_admin(
    admin: AdminUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=admin.username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    if admin.password:
        existing_admin.password = hash_password(admin.password)
    if admin.telegram_id is not None:
        existing_admin.telegram_id = admin.telegram_id
    elif "telegram_id" in admin.model_dump(exclude_unset=True) and admin.telegram_id is None:
        existing_admin.telegram_id = None
    # Per-admin new-user defaults: an explicit null clears the override.
    provided = admin.model_dump(exclude_unset=True)
    for attr in ("default_days", "default_traffic_gb", "default_max_users"):
        if attr in provided:
            setattr(existing_admin, attr, getattr(admin, attr))

    if admin.username_prefix is not None:
        existing_admin.username_prefix = admin.username_prefix
    elif "username_prefix" in admin.model_dump(exclude_unset=True) and admin.username_prefix is None:
        existing_admin.username_prefix = None

    db.commit()
    db.refresh(existing_admin)

    # A password change must end the admin's live sessions: a stolen bearer
    # token would otherwise keep working until idle expiry.
    if admin.password:
        from backend.auth.sessions import revoke_user_sessions

        revoke_user_sessions(db, existing_admin.username)

    log_event(db, "admin.update", actor=user.get("username"), target=existing_admin.username)
    data = Admins.model_validate(existing_admin)
    counts = db.query(_User.id).filter(_User.owner == existing_admin.username).count()
    data.users_count = counts
    data.effective_defaults = crud.effective_user_defaults(db, existing_admin.username)
    return ResponseModel(
        success=True,
        msg="Admin updated successfully",
        data=data,
    )


@router.delete("/{username}")
async def delete_admin(
    username: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    # Kill the admin's live sessions immediately — deleting the row alone
    # would leave their bearer tokens valid until idle expiry.
    from backend.auth.sessions import revoke_user_sessions

    revoke_user_sessions(db, username)
    crud.delete_admin(db, existing_admin)
    log_event(db, "admin.delete", actor=user.get("username"), target=username)
    return ResponseModel(
        success=True,
        msg="Admin deleted successfully",
        data=None,
    )


@router.put("/{username}/status", response_model=ResponseModel)
async def set_admin_status(
    username: str,
    payload: AdminStatusUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    # The owner lives in .env, not the admins table, and must never be
    # lockable through this surface.
    if username == config.ADMIN_USERNAME:
        return ResponseModel(success=False, msg="The owner account status cannot be changed", data=None)

    existing_admin = crud.get_admin_by_username(db, username=username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    existing_admin.disabled = not payload.status
    db.commit()
    db.refresh(existing_admin)

    # Disabling must kill every live bearer token at once; enabling does not
    # need to because disabled admins cannot authenticate in the first place.
    revoked = 0
    if existing_admin.disabled:
        from backend.auth.sessions import revoke_user_sessions

        revoked = revoke_user_sessions(db, existing_admin.username)

    log_event(
        db,
        "admin.disable" if existing_admin.disabled else "admin.enable",
        actor=user.get("username"),
        target=existing_admin.username,
    )
    return ResponseModel(
        success=True,
        msg="Admin disabled successfully" if existing_admin.disabled else "Admin enabled successfully",
        data={"disabled": existing_admin.disabled, "revoked_sessions": revoked},
    )


@router.get("/{username}/sessions", response_model=ResponseModel)
async def get_admin_sessions(
    username: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    now = time.time()
    sessions = db.query(AuthSession).filter(AuthSession.username == username).order_by(AuthSession.id).all()
    # Never expose token_hash: the response is id + metadata only.
    data = [
        {
            "id": session.id,
            "ip": session.ip,
            "user_agent": session.user_agent,
            "created_at": session.created_at,
            "last_seen_at": session.last_seen_at,
            "expires_at": session.expires_at,
        }
        for session in sessions
        if now < session.expires_at and now - (session.last_seen_at or 0) <= config.SESSION_IDLE_SECONDS
    ]
    return ResponseModel(success=True, msg="Admin sessions retrieved successfully", data=data)


@router.post("/{username}/sessions/revoke", response_model=ResponseModel)
async def revoke_admin_sessions(
    username: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_owner),
):
    existing_admin = crud.get_admin_by_username(db, username=username)
    if not existing_admin:
        return ResponseModel(success=False, msg="Admin not found", data=None)

    from backend.auth.sessions import revoke_user_sessions

    revoked = revoke_user_sessions(db, username)
    log_event(db, "admin.sessions_revoke", actor=user.get("username"), target=username)
    return ResponseModel(
        success=True,
        msg=f"Revoked {revoked} session(s)",
        data={"revoked": revoked},
    )
