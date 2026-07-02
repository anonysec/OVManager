from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.operations.daily_checks import enforce_user_limits
from backend.schema.output import ResponseModel, Users
from backend.schema._input import CreateUser, UpdateUser
from backend.db.engine import get_db
from backend.db import crud
from backend.auth.auth import get_current_user
from backend.node.task import (
    delete_user_on_all_nodes,
    change_user_status_on_all_nodes,
    set_user_limit_on_all_nodes,
    get_active_connection_counts,
    get_user_session_diagnostics,
    disconnect_user_on_all_nodes,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=ResponseModel)
async def get_all_users(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    active_counts = await get_active_connection_counts(db)

    def serialize(db_user):
        item = Users.model_validate(db_user).model_dump()
        item["active_connections"] = int(active_counts.get(db_user.name, 0) or 0)
        item["online"] = item["active_connections"] > 0
        return item

    if user["type"] == "main_admin":
        all_users = crud.get_all_users(db)
        users_list = [serialize(u) for u in all_users]
        return ResponseModel(
            success=True,
            msg="Users retrieved successfully",
            data=users_list,
        )

    elif user["type"] == "admin":
        admin_users = crud.get_users_by_admin(db, admin_username=user["username"])
        users_list = [serialize(u) for u in admin_users]
        return ResponseModel(
            success=True,
            msg="Users retrieved successfully",
            data=users_list,
        )

    return ResponseModel(
        success=False,
        msg="Unauthorized access",
    )


@router.get("/{uuid}", response_model=ResponseModel)
async def reset_user_usage(uuid: str, db: Session = Depends(get_db)):
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
        return ResponseModel(
            success=False, msg="User with this name already exists", data=None
        )

    owner = user["username"] if user["type"] == "admin" else "owner"
    new_user = crud.create_user(db, request, owner)

    # Do NOT synchronously create the user on every node here. The OpenVPN client
    # generation script is slow and can make the Add User popup look stuck.
    # The node-side client/config is created lazily when Download is clicked.
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
    result = crud.update_user(db, uuid, request)
    if result:
        user = crud.get_user_by_uuid(db, uuid)
        used = user.used or 0
        # total=None means unlimited traffic, so it is never "exceeded".
        not_expired = user.expiry_date >= datetime.today().date()
        has_traffic = user.total is None or user.total > used
        if not_expired and has_traffic:
            await change_user_status_on_all_nodes(uuid, request.name, True, db)
        else:
            await change_user_status_on_all_nodes(uuid, request.name, False, db)
        # Push the (possibly updated) simultaneous-login limit to all nodes.
        await set_user_limit_on_all_nodes(user.name, user.max_logins, db)
    # enforce_user_limits is async; must be awaited or it silently never runs.
    await enforce_user_limits()
    return ResponseModel(success=True, msg="User updated successfully", data=result)


@router.put("/{uuid}/status", response_model=ResponseModel)
async def change_user_status(
    uuid: str,
    request: UpdateUser,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await change_user_status_on_all_nodes(uuid, request.name, request.status, db)
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
    if user["type"] == "admin" and db_user.owner != user["username"]:
        return ResponseModel(success=False, msg="Unauthorized access", data=None)
    data = await get_user_session_diagnostics(db_user.name, db, hours=hours)
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
    if user["type"] == "admin" and db_user.owner != user["username"]:
        return ResponseModel(success=False, msg="Unauthorized access", data=None)
    data = await disconnect_user_on_all_nodes(db_user.name, db)
    return ResponseModel(success=True, msg="Disconnect command processed", data=data)


@router.delete("/{uuid}", response_model=ResponseModel)
async def delete_user(
    uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    user = crud.get_user_by_uuid(db, uuid)
    if user is None:
        return ResponseModel(success=False, msg="User not found", data=None)

    if await delete_user_on_all_nodes(user.name, db):
        crud.delete_user(db, user.name)
        return ResponseModel(success=True, msg="User deleted successfully")
    return ResponseModel(success=False, msg="Failed to delete user on all nodes")
