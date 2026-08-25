# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.


import time as _time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db import crud
from backend.db.engine import get_db
from backend.db.models import User
from backend.node.task import (
    change_user_status_on_all_nodes,
    delete_user_on_all_nodes,
    disconnect_user_on_all_nodes,
    get_active_connection_counts,
    get_user_session_diagnostics,
    set_user_limit_on_all_nodes,
)
from backend.operations.audit import log_event
from backend.schema._input import CreateUser, StatusToggle, UpdateUser
from backend.schema.output import ResponseModel, Users

router = APIRouter(prefix="/users", tags=["Users"])

# ── Undo-delete buffer ────────────────────────────────────────────
# Snapshot recently deleted users in-memory (bounded + TTL) so the UI can
# offer "Undo" for a few seconds after a delete. Restoring re-inserts the
# row with its original UUID; node-side certs regenerate on next download.

_DELETED_TTL = 120  # seconds
_DELETED_MAX = 50
_deleted_users: dict[str, tuple[float, dict]] = {}


def _snapshot_user(u: User) -> dict:
    return {
        "name": u.name,
        "uuid": u.uuid,
        "total": u.total,
        "used": u.used,
        "max_logins": u.max_logins,
        "expiry_date": u.expiry_date.isoformat() if u.expiry_date else None,
        "is_active": u.is_active,
        "owner": u.owner,
    }


def _remember_deleted(u: User) -> None:
    now = _time.monotonic()
    _deleted_users[u.uuid] = (now, _snapshot_user(u))
    # Evict expired + overflow
    for k in [k for k, (ts, _) in _deleted_users.items() if now - ts > _DELETED_TTL]:
        _deleted_users.pop(k, None)
    while len(_deleted_users) > _DELETED_MAX:
        _deleted_users.pop(next(iter(_deleted_users)), None)


def _require_user_access(db_user: User, current_user: dict) -> None:
    """Enforce the same ownership rule for every user operation."""
    if current_user.get("type") == "admin" and db_user.owner != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not have permission to access this resource")


@router.get("/next-username", response_model=ResponseModel)
async def get_next_username(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    admin = crud.get_admin_by_username(db, username=user.get("username"))
    prefix = admin.username_prefix if admin else None
    if not prefix:
        return ResponseModel(success=False, msg="No username prefix configured for this admin")

    # Fetch only names that start with the prefix and end with digits.
    # Limit to 100_000 to bound memory; in practice admins have far fewer users.
    existing = db.query(User.name).filter(User.name.like(f"{prefix}%")).limit(100_000).all()
    taken = {n[0] for n in existing}

    i = 1
    while f"{prefix}{i}" in taken:
        i += 1

    return ResponseModel(
        success=True,
        msg="Next username generated",
        data={"username": f"{prefix}{i}"},
    )


@router.get("/", response_model=ResponseModel)
async def get_all_users(
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # Clamp pagination params
    page = max(1, min(page, 10_000))
    page_size = max(1, min(page_size, 500))

    active_counts = await get_active_connection_counts(db)

    def serialize(db_user):
        item = Users.model_validate(db_user).model_dump()
        item["active_connections"] = int(active_counts.get(db_user.name, 0) or 0)
        item["online"] = item["active_connections"] > 0
        # last_online is updated by the background metrics job, not here.
        # GET endpoints must not modify data.
        item["last_online"] = db_user.last_online.isoformat() if db_user.last_online else None
        return item

    if user["type"] == "owner":
        all_users = crud.get_all_users(db)
        total = len(all_users)
        start = (page - 1) * page_size
        end = start + page_size
        users_list = [serialize(u) for u in all_users[start:end]]
        return ResponseModel(
            success=True,
            msg="Users retrieved successfully",
            data={"users": users_list, "total": total, "page": page, "page_size": page_size},
        )

    elif user["type"] == "admin":
        admin_users = crud.get_users_by_admin(db, admin_username=user["username"])
        total = len(admin_users)
        start = (page - 1) * page_size
        end = start + page_size
        users_list = [serialize(u) for u in admin_users[start:end]]
        return ResponseModel(
            success=True,
            msg="Users retrieved successfully",
            data={"users": users_list, "total": total, "page": page, "page_size": page_size},
        )

    return ResponseModel(
        success=False,
        msg="Unauthorized access",
    )


@router.post("/{uuid}/reset-usage", response_model=ResponseModel)
async def reset_user_usage(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    reset = crud.reset_user_usage(db, uuid)
    if not reset:
        raise HTTPException(status_code=404, detail="User not found")
    return ResponseModel(success=True, msg="User usage reset successfully", data=None)


@router.post("/", response_model=ResponseModel)
async def create_user(
    request: CreateUser,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # Normalize exactly as the DB layer does before checking duplicates and
    # before using the name to create node-side CNs.
    normalized_name = request.name.replace(" ", "_")
    check_user = crud.get_user_by_name(db, normalized_name)
    if check_user is not None:
        return ResponseModel(success=False, msg="User with this name already exists", data=None)

    # Use the actual username as the owner so users created by the panel owner
    # are associated with a real identity, not the generic sentinel "owner".
    owner = user["username"]
    new_user = crud.create_user(db, request, owner)

    # Do NOT synchronously create the user on every node here. The OpenVPN client
    # generation script is slow and can make the Add User popup look stuck.
    # The node-side client/config is created lazily when Download is clicked.
    log_event(db, "user.create", actor=user.get("username"), target=new_user.name, detail="User created")
    return ResponseModel(
        success=True,
        msg="User created successfully. VPN config will be generated on first download.",
        data=Users.model_validate(new_user),
    )


@router.put("/{uuid}/", response_model=ResponseModel, include_in_schema=False)
@router.put("/{uuid}", response_model=ResponseModel)
async def update_user(
    uuid: str,
    request: UpdateUser,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    crud.update_user(db, uuid, request)
    db_user = crud.get_user_by_uuid(db, uuid)
    final_active = bool(db_user.is_active)
    status_synced = await change_user_status_on_all_nodes(db_user.id, db_user.name, final_active, db)
    limit_synced = await set_user_limit_on_all_nodes(db_user.name, db_user.max_logins, db, db_user.id)
    if not status_synced or not limit_synced:
        return ResponseModel(
            success=False,
            msg="User saved locally but one or more nodes failed to synchronize",
            data={"status_synced": status_synced, "limit_synced": limit_synced},
        )
    # enforce_user_limits runs as a daily background job in app.py;
    # calling it per user update is O(n²) — each call queries all expired/exceeded users.
    log_event(db, "user.update", actor=user.get("username"), target=request.name, detail="User updated")
    return ResponseModel(success=True, msg="User updated successfully")


@router.put("/{uuid}/status", response_model=ResponseModel)
async def change_user_status(
    uuid: str,
    request: StatusToggle,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    db_user.is_active = bool(request.status)
    db.commit()
    synced = await change_user_status_on_all_nodes(db_user.id, db_user.name, request.status, db)
    if not synced:
        return ResponseModel(
            success=False,
            msg="User status saved locally but node synchronization failed",
            data={"synced": False},
        )
    log_event(db, "user.status", actor=user.get("username"), target=request.name, detail=f"status={request.status}")
    return ResponseModel(success=True, msg="Changed user status successfully")


@router.get("/{uuid}/sessions", response_model=ResponseModel)
async def user_sessions(
    uuid: str,
    hours: int = 8,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    data = await get_user_session_diagnostics(db_user.id, db, hours=hours)
    return ResponseModel(success=True, msg="User session diagnostics", data=data)


@router.post("/{uuid}/disconnect", response_model=ResponseModel)
async def disconnect_user_sessions(
    uuid: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    data = await disconnect_user_on_all_nodes(db_user.name, db_user.id, db)
    log_event(db, "user.disconnect", actor=user.get("username"), target=db_user.name, detail="Disconnect requested")
    return ResponseModel(success=True, msg="Disconnect command processed", data=data)


@router.delete("/{uuid}", response_model=ResponseModel)
async def delete_user(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        return ResponseModel(success=False, msg="User not found", data=None)
    _require_user_access(db_user, user)

    if await delete_user_on_all_nodes(db_user.name, db_user.id, db):
        name = db_user.name
        _remember_deleted(db_user)  # enable Undo
        crud.delete_user(db, name)
        log_event(db, "user.delete", actor=user.get("username"), target=name, detail="User deleted")
        return ResponseModel(success=True, msg="User deleted successfully")
    return ResponseModel(success=False, msg="Failed to delete user on all nodes")


@router.post("/{uuid}/restore", response_model=ResponseModel)
async def restore_user(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """Undo a recent delete: re-insert the user with its original UUID."""
    entry = _deleted_users.get(uuid)
    if not entry or (_time.monotonic() - entry[0]) > _DELETED_TTL:
        return ResponseModel(success=False, msg="Undo window expired — user can no longer be restored", data=None)
    snap = entry[1]
    if crud.get_user_by_uuid(db, uuid) is not None:
        _deleted_users.pop(uuid, None)
        return ResponseModel(success=False, msg="User already exists", data=None)
    try:
        restored = crud.restore_user(db, snap)
    except Exception as exc:
        return ResponseModel(success=False, msg=f"Restore failed: {exc}", data=None)
    _deleted_users.pop(uuid, None)
    # Re-push the login limit to nodes (best-effort; certs regenerate on download).
    await set_user_limit_on_all_nodes(restored.name, restored.max_logins, db, restored.id)
    log_event(db, "user.restore", actor=user.get("username"), target=restored.name, detail="User restored (undo)")
    return ResponseModel(
        success=True,
        msg="User restored successfully",
        data=Users.model_validate(restored).model_dump(),
    )


class _BulkAdjust(BaseModel):
    action: Literal["extend", "add-traffic"]
    uuids: list[str] = Field(min_length=1)
    days: int = 0
    bytes: int = 0


@router.post("/bulk", response_model=ResponseModel)
async def bulk_adjust_users(
    payload: _BulkAdjust,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Bulk-extend expiry or add traffic quota to selected users."""
    result = crud.bulk_adjust_users(db, payload.uuids, days=payload.days, add_bytes=payload.bytes)
    action = "extend" if payload.action == "extend" else "add-traffic"
    log_event(
        db,
        f"bulk.{action}",
        actor=user.get("username"),
        target=f"{result['updated']} users",
        detail=str(payload.days or payload.bytes),
    )
    return ResponseModel(success=result["updated"] > 0, msg=f"{result['updated']} user(s) updated", data=result)
